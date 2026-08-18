"""
audio/engine.py — AudioEngine

- Linux (Pi): C 프로세스(karaoke_audio) 기반 — GIL 완전 격리, SCHED_FIFO 40
- Windows: PortAudio + numpy 기반 (개발/테스트용)

두 구현 모두 동일한 public API를 제공한다:
  start() / stop() / is_running / level_queue / status_queue / latency_queue
"""

import platform
import logging

if platform.system() == 'Linux':
    # ── Linux: C 프로세스 엔진 ──────────────────────────────────
    import dataclasses
    import os
    import queue
    import subprocess
    import threading
    import time
    from pathlib import Path

    from config import EchoParams, CHANNELS_IN, CHANNELS_OUT

    _AUDIO_DIR = Path(__file__).parent
    _BIN       = _AUDIO_DIR / 'karaoke_audio'

    class AudioEngine:
        """C 프로세스(karaoke_audio)를 subprocess로 구동하는 오디오 엔진.

        IPC 프로토콜 (stdin/stdout 라인 기반):
          → START | STOP | QUIT | PARAM key=val ...
          ← READY | LEVEL in_rms out_rms xruns | BYE
        """

        def __init__(self, echo_proc, reverb_proc, params: EchoParams,
                     input_device=None, output_device=None,
                     sample_rate: int = 48000, block_size: int = 0):
            # echo_proc, reverb_proc는 Windows 폴백용 인수 — Linux에서는 사용 안 함
            self._params        = params
            self._input_device  = input_device   # int(카드 인덱스) 또는 str("hw:N,0")
            self._output_device = output_device  # str("scarlett_dmix") 또는 None

            self._proc:         subprocess.Popen | None = None
            self._reader_tid:   threading.Thread | None = None
            self._watcher_tid:  threading.Thread | None = None
            self._stop_watcher: bool = False
            # The helper process remains alive after STOP so it can be
            # restarted cheaply.  Keep the user-visible ON/OFF state
            # separate from process liveness (otherwise ON is ignored after
            # an OFF because the process is still present).
            self._active: bool = False

            self.level_queue:         queue.Queue = queue.Queue(maxsize=20)
            self.status_queue:        queue.Queue = queue.Queue(maxsize=5)
            self.latency_queue:       queue.Queue = queue.Queue(maxsize=10)
            self.exclusive_fail_reason: str = ''

            # 파라미터 감시용 — 마지막으로 C 프로세스에 전송한 파라미터 스냅샷
            self._last_sent: dict | None = None

            # PipeWire suspend 추적
            self._pw_suspended_sources: list[str] = []
            self._pw_suspended_sinks:   list[str] = []

        # ── 빌드 ──────────────────────────────────────────────────

        def _build(self) -> None:
            """C 바이너리가 없으면 make로 빌드."""
            if _BIN.exists():
                return
            result = subprocess.run(
                ['make', '-C', str(_AUDIO_DIR), 'karaoke_audio'],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f'karaoke_audio 빌드 실패:\n{result.stderr}'
                )

        # ── ALSA 장치 문자열 변환 ──────────────────────────────────

        def _alsa_cap_dev(self) -> str:
            d = self._input_device
            if isinstance(d, int):
                return f'hw:{d},0'
            return str(d) if d else 'hw:0,0'

        def _alsa_pb_dev(self) -> str:
            return self._output_device if self._output_device else 'scarlett_dmix'

        # ── 프로세스 시작/정지 ─────────────────────────────────────

        def start(self):
            """C 오디오 프로세스를 시작(또는 이미 실행 중이면 START 커맨드만 전송)."""
            if platform.system() != 'Linux':
                return

            self._suspend_pipewire_scarlett()

            if self._proc is None or self._proc.poll() is not None:
                self._build()
                self._spawn_proc()

            self._send_params()
            self._send('START')
            self._active = True

        def stop(self):
            """C 프로세스에 STOP을 보내고 PipeWire를 복원한다."""
            self._send('STOP')
            self._active = False
            self._resume_pipewire_scarlett()

        def _spawn_proc(self):
            """C 프로세스를 새로 시작하고 READY를 기다린다."""
            err_log = open('/tmp/karaoke_audio.err', 'a', encoding='utf-8')
            self._proc = subprocess.Popen(
                [str(_BIN), self._alsa_cap_dev(), self._alsa_pb_dev()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=err_log,
                text=True,
                bufsize=1,
            )

            # READY 수신 대기 (최대 5초)
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                line = self._proc.stdout.readline().strip()
                if line == 'READY':
                    break
                if self._proc.poll() is not None:
                    raise RuntimeError('karaoke_audio 프로세스가 시작 직후 종료됨')
            else:
                self._proc.kill()
                raise RuntimeError('karaoke_audio READY 응답 없음 (5초 초과)')

            # stdout 리더 스레드
            self._reader_tid = threading.Thread(
                target=self._reader, daemon=True)
            self._reader_tid.start()

            # 파라미터 감시 스레드 (슬라이더 변경 → C 프로세스에 실시간 전송)
            self._stop_watcher = False
            self._watcher_tid = threading.Thread(
                target=self._param_watcher, daemon=True)
            self._watcher_tid.start()

        # ── IPC ──────────────────────────────────────────────────

        def _send(self, cmd: str):
            if self._proc and self._proc.poll() is None:
                try:
                    self._proc.stdin.write(cmd + '\n')
                    self._proc.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass

        def _send_params(self):
            p = self._params
            cmd = (
                f'PARAM delay_sec={p.delay_sec:.4f} feedback={p.feedback:.4f}'
                f' wet={p.wet:.4f} volume={p.volume:.4f}'
                f' reverb_room={p.reverb_room:.4f} reverb_damp={p.reverb_damp:.4f}'
                f' reverb_wet={p.reverb_wet:.4f}'
            )
            self._send(cmd)
            self._last_sent = dataclasses.asdict(self._params)

        def _reader(self):
            """C 프로세스 stdout을 읽어 큐로 전달한다."""
            while self._proc and self._proc.poll() is None:
                line = self._proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if line.startswith('LEVEL '):
                    parts = line.split()
                    if len(parts) >= 3:
                        try:
                            in_rms  = float(parts[1])
                            out_rms = float(parts[2])
                            if len(parts) >= 4:
                                xruns = int(parts[3])
                                if xruns:
                                    logging.warning('오디오 XRUN 감지: %d회', xruns)
                            if not self.level_queue.full():
                                self.level_queue.put_nowait((in_rms, out_rms))
                        except ValueError:
                            pass
                elif line.startswith('XRUN') or line.startswith('ERROR'):
                    if not self.status_queue.full():
                        self.status_queue.put_nowait(line)

            if not self.status_queue.full():
                self.status_queue.put_nowait('engine_stopped')
            self._active = False

        def _param_watcher(self):
            """50ms 간격으로 EchoParams 변경 감지 → PARAM 커맨드 전송."""
            while not self._stop_watcher:
                time.sleep(0.05)
                if self._proc and self._proc.poll() is None:
                    current = dataclasses.asdict(self._params)
                    if current != self._last_sent:
                        self._send_params()

        # ── 상태 ──────────────────────────────────────────────────

        @property
        def is_running(self) -> bool:
            return self._active and self._proc is not None and self._proc.poll() is None

        # ── PipeWire 정지/복원 ─────────────────────────────────────

        def _suspend_pipewire_scarlett(self) -> None:
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            self._pw_suspended_sources = []
            self._pw_suspended_sinks   = []
            try:
                for list_cmd, store in [
                    (['pactl', 'list', 'sources', 'short'], self._pw_suspended_sources),
                    (['pactl', 'list', 'sinks',   'short'], self._pw_suspended_sinks),
                ]:
                    res = subprocess.run(
                        list_cmd, capture_output=True, text=True, timeout=5, env=env)
                    for line in res.stdout.splitlines():
                        parts = line.split()
                        if len(parts) < 2:
                            continue
                        name = parts[1]
                        if ('scarlett' in name.lower() or 'focusrite' in name.lower()) \
                                and 'monitor' not in name.lower():
                            store.append(name)

                for name in self._pw_suspended_sources:
                    subprocess.run(['pactl', 'suspend-source', name, '1'],
                                   capture_output=True, timeout=5, env=env)
                for name in self._pw_suspended_sinks:
                    subprocess.run(['pactl', 'suspend-sink', name, '1'],
                                   capture_output=True, timeout=5, env=env)
                if self._pw_suspended_sources or self._pw_suspended_sinks:
                    time.sleep(0.15)
            except Exception:
                pass

        def _resume_pipewire_scarlett(self) -> None:
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                for name in self._pw_suspended_sources:
                    subprocess.run(['pactl', 'suspend-source', name, '0'],
                                   capture_output=True, timeout=5, env=env)
                for name in self._pw_suspended_sinks:
                    subprocess.run(['pactl', 'suspend-sink', name, '0'],
                                   capture_output=True, timeout=5, env=env)
            except Exception:
                pass
            self._pw_suspended_sources = []
            self._pw_suspended_sinks   = []

        # ── 정적 유틸 (main.py 호환) ───────────────────────────────

        @staticmethod
        def list_devices():
            import sounddevice as sd
            hostapis = sd.query_hostapis()
            result = []
            for i, d in enumerate(sd.query_devices()):
                api        = hostapis[d['hostapi']]['name'] if d['hostapi'] < len(hostapis) else '?'
                in_lat_ms  = d['default_low_input_latency']  * 1000
                out_lat_ms = d['default_low_output_latency'] * 1000
                result.append((i, d['name'], d['max_input_channels'],
                               d['max_output_channels'], api, in_lat_ms, out_lat_ms))
            return result

        @staticmethod
        def best_scarlett_devices():
            import sounddevice as sd
            hostapis   = sd.query_hostapis()
            wasapi_idx = next((i for i, h in enumerate(hostapis)
                               if 'WASAPI' in h['name']), None)
            best_in = best_out = None
            best_in_lat = best_out_lat = float('inf')
            for i, d in enumerate(sd.query_devices()):
                name = d['name'].lower()
                if 'focusrite' not in name and 'scarlett' not in name:
                    continue
                is_wasapi = (wasapi_idx is not None and d['hostapi'] == wasapi_idx)
                lat = d['default_low_input_latency']
                if d['max_input_channels'] > 0 and (is_wasapi or lat < best_in_lat):
                    best_in = i; best_in_lat = lat
                lat = d['default_low_output_latency']
                if d['max_output_channels'] > 0 and (is_wasapi or lat < best_out_lat):
                    best_out = i; best_out_lat = lat
            return best_in, best_out

        @staticmethod
        def find_scarlett_alsa_card():
            import re
            from pathlib import Path
            try:
                text  = Path('/proc/asound/cards').read_text()
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    m = re.match(r'\s*(\d+)\s+\[', line)
                    if m:
                        card_idx = int(m.group(1))
                        context  = '\n'.join(lines[i:i + 3])
                        if 'scarlett' in context.lower() or 'focusrite' in context.lower():
                            return card_idx
            except OSError:
                pass
            return None

        @staticmethod
        def list_audio_sources():
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                res = subprocess.run(['pactl', 'list', 'sources'],
                                     capture_output=True, text=True, timeout=5, env=env)
                sources: list[tuple[str, str]] = []
                current_name = ''
                for line in res.stdout.splitlines():
                    s = line.strip()
                    if s.startswith('Name:'):
                        current_name = s.split(':', 1)[1].strip()
                    elif s.startswith('Description:') and current_name:
                        desc = s.split(':', 1)[1].strip()
                        if 'monitor' not in current_name.lower():
                            sources.append((current_name, desc))
                        current_name = ''
                return sources
            except Exception:
                return []

        @staticmethod
        def get_default_audio_source():
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                r = subprocess.run(['pactl', 'get-default-source'],
                                   capture_output=True, text=True, timeout=5, env=env)
                return r.stdout.strip()
            except Exception:
                return ''

        @staticmethod
        def set_default_audio_source(source_name: str):
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                subprocess.run(['pactl', 'set-default-source', source_name],
                               capture_output=True, timeout=5, env=env)
            except Exception:
                pass

        @staticmethod
        def list_audio_sinks():
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                res = subprocess.run(['pactl', 'list', 'sinks'],
                                     capture_output=True, text=True, timeout=5, env=env)
                sinks: list[tuple[str, str]] = []
                current_name = ''
                for line in res.stdout.splitlines():
                    s = line.strip()
                    if s.startswith('Name:'):
                        current_name = s.split(':', 1)[1].strip()
                    elif s.startswith('Description:') and current_name:
                        desc = s.split(':', 1)[1].strip()
                        sinks.append((current_name, desc))
                        current_name = ''
                return sinks
            except Exception:
                return []

        @staticmethod
        def get_default_audio_sink():
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                r = subprocess.run(['pactl', 'get-default-sink'],
                                   capture_output=True, text=True, timeout=5, env=env)
                return r.stdout.strip()
            except Exception:
                return ''

        @staticmethod
        def set_default_audio_sink(sink_name: str):
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            try:
                subprocess.run(['pactl', 'set-default-sink', sink_name],
                               capture_output=True, timeout=5, env=env)
            except Exception:
                pass

else:
    # ── Windows: 기존 PortAudio + numpy 엔진 ──────────────────────
    import concurrent.futures
    import os
    import queue
    import re
    import subprocess
    import time
    from pathlib import Path

    import numpy as np
    import sounddevice as sd
    from config import EchoParams, CHANNELS_IN, CHANNELS_OUT, DTYPE

    class AudioEngine:
        def __init__(self, echo_proc, reverb_proc, params: EchoParams,
                     input_device=None, output_device=None,
                     sample_rate: int = 48000, block_size: int = 0):
            self._echo   = echo_proc
            self._reverb = reverb_proc
            self._params = params
            self._stream: sd.Stream | None = None
            self._rt_applied: bool = False
            self.level_queue:           queue.Queue = queue.Queue(maxsize=20)
            self.status_queue:          queue.Queue = queue.Queue(maxsize=5)
            self.latency_queue:         queue.Queue = queue.Queue(maxsize=10)
            self.exclusive_fail_reason: str = ''

            self._kwargs = dict(
                samplerate        = sample_rate,
                blocksize         = block_size,
                dtype             = DTYPE,
                channels          = (CHANNELS_IN, CHANNELS_OUT),
                device            = (input_device, output_device),
                callback          = self._callback,
                finished_callback = self._on_finished,
                latency           = 'low',
            )

            self._wasapi_exclusive = False
            try:
                wasapi = sd.WasapiSettings(exclusive=True)
                self._kwargs['extra_settings'] = wasapi
                self._wasapi_exclusive = True
            except Exception:
                pass

        def _callback(self, indata, outdata, frames, time, status):
            if status and not self.status_queue.full():
                self.status_queue.put_nowait(str(status))
            processed = self._echo.process(indata)
            processed = self._reverb.process(processed)
            outdata[:] = np.repeat(processed, CHANNELS_OUT, axis=1)
            rms     = float(np.sqrt(np.mean(indata    ** 2)))
            out_rms = float(np.sqrt(np.mean(outdata   ** 2)))
            if not self.level_queue.full():
                self.level_queue.put_nowait((rms, out_rms))
            rt_ms = (time.outputBufferDacTime - time.inputBufferAdcTime) * 1000
            if rt_ms > 0 and not self.latency_queue.full():
                self.latency_queue.put_nowait(rt_ms)

        def _on_finished(self):
            pass

        def _open_stream(self, kwargs):
            stream = sd.Stream(**kwargs)
            stream.start()
            return stream

        def start(self):
            if self._stream and self._stream.active:
                return
            if self._echo:   self._echo.reset()
            if self._reverb: self._reverb.reset()
            self.exclusive_fail_reason = ''
            kwargs = dict(self._kwargs)
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as exe:
                    self._stream = exe.submit(self._open_stream, kwargs).result(timeout=6.0)
                return
            except Exception as e:
                self.exclusive_fail_reason = str(e)
                kwargs = {k: v for k, v in kwargs.items() if k != 'extra_settings'}
                self._wasapi_exclusive = False
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as exe:
                    self._stream = exe.submit(self._open_stream, kwargs).result(timeout=6.0)
            except Exception as e:
                raise RuntimeError(f'오디오 스트림 열기 실패: {e}') from e

        def stop(self):
            if self._stream:
                self._stream.stop()
                self._stream.close()
                self._stream = None
            self._rt_applied = False

        @property
        def is_running(self) -> bool:
            return self._stream is not None and self._stream.active

        @staticmethod
        def list_devices():
            hostapis = sd.query_hostapis()
            result = []
            for i, d in enumerate(sd.query_devices()):
                api        = hostapis[d['hostapi']]['name'] if d['hostapi'] < len(hostapis) else '?'
                in_lat_ms  = d['default_low_input_latency']  * 1000
                out_lat_ms = d['default_low_output_latency'] * 1000
                result.append((i, d['name'], d['max_input_channels'],
                               d['max_output_channels'], api, in_lat_ms, out_lat_ms))
            return result

        @staticmethod
        def best_scarlett_devices():
            hostapis   = sd.query_hostapis()
            wasapi_idx = next((i for i, h in enumerate(hostapis)
                               if 'WASAPI' in h['name']), None)
            best_in = best_out = None
            best_in_lat = best_out_lat = float('inf')
            for i, d in enumerate(sd.query_devices()):
                name = d['name'].lower()
                if 'focusrite' not in name and 'scarlett' not in name:
                    continue
                is_wasapi = (wasapi_idx is not None and d['hostapi'] == wasapi_idx)
                lat = d['default_low_input_latency']
                if d['max_input_channels'] > 0 and (is_wasapi or lat < best_in_lat):
                    best_in = i; best_in_lat = lat
                lat = d['default_low_output_latency']
                if d['max_output_channels'] > 0 and (is_wasapi or lat < best_out_lat):
                    best_out = i; best_out_lat = lat
            return best_in, best_out

        @staticmethod
        def find_scarlett_alsa_card():
            import re
            from pathlib import Path
            try:
                text  = Path('/proc/asound/cards').read_text()
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    m = re.match(r'\s*(\d+)\s+\[', line)
                    if m:
                        card_idx = int(m.group(1))
                        context  = '\n'.join(lines[i:i + 3])
                        if 'scarlett' in context.lower() or 'focusrite' in context.lower():
                            return card_idx
            except OSError:
                pass
            return None

        @staticmethod
        def list_audio_sources():
            return []

        @staticmethod
        def get_default_audio_source():
            return ''

        @staticmethod
        def set_default_audio_source(source_name: str):
            pass

        @staticmethod
        def list_audio_sinks():
            return []

        @staticmethod
        def get_default_audio_sink():
            return ''

        @staticmethod
        def set_default_audio_sink(sink_name: str):
            pass
