import concurrent.futures
import os
import platform
import queue
import re
import subprocess
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
        self.level_queue:   queue.Queue = queue.Queue(maxsize=20)
        self.status_queue:  queue.Queue = queue.Queue(maxsize=5)
        self.latency_queue: queue.Queue = queue.Queue(maxsize=10)

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

        # Windows: WASAPI Exclusive 모드
        self._wasapi_exclusive = False
        if platform.system() == 'Windows':
            try:
                wasapi = sd.WasapiSettings(exclusive=True)
                self._kwargs['extra_settings'] = wasapi
                self._wasapi_exclusive = True
            except Exception:
                pass

    def _callback(self, indata: np.ndarray, outdata: np.ndarray,
                  frames: int, time, status):
        if status and not self.status_queue.full():
            self.status_queue.put_nowait(str(status))

        processed = self._echo.process(indata)
        processed = self._reverb.process(processed)
        outdata[:] = np.repeat(processed, CHANNELS_OUT, axis=1)

        rms     = float(np.sqrt(np.mean(indata ** 2)))
        out_rms = float(np.sqrt(np.mean(outdata ** 2)))
        if not self.level_queue.full():
            self.level_queue.put_nowait((rms, out_rms))

        rt_ms = (time.outputBufferDacTime - time.inputBufferAdcTime) * 1000
        if rt_ms > 0 and not self.latency_queue.full():
            self.latency_queue.put_nowait(rt_ms)

    def _on_finished(self):
        pass

    def _open_stream(self, kwargs: dict) -> sd.Stream:
        """별도 스레드에서 호출 — ALSA 초기화 행업 방지."""
        stream = sd.Stream(**kwargs)
        stream.start()
        return stream

    def start(self):
        if self._stream and self._stream.active:
            return
        self._echo.reset()
        self._reverb.reset()
        self.exclusive_fail_reason = ''

        # WASAPI Exclusive 시도 (Windows)
        kwargs = dict(self._kwargs)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as exe:
                future = exe.submit(self._open_stream, kwargs)
                self._stream = future.result(timeout=6.0)
            return
        except concurrent.futures.TimeoutError:
            raise RuntimeError(
                '오디오 장치 열기 시간 초과 (6초).\n'
                'PipeWire/PulseAudio가 장치를 점유 중일 수 있습니다.\n'
                'run.sh 에서 pasuspender 사용 여부를 확인하세요.'
            )
        except Exception as e:
            self.exclusive_fail_reason = str(e)
            # extra_settings 제거 후 폴백
            kwargs = {k: v for k, v in kwargs.items() if k != 'extra_settings'}
            self._wasapi_exclusive = False

        # 폴백 스트림 시도
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as exe:
                future = exe.submit(self._open_stream, kwargs)
                self._stream = future.result(timeout=6.0)
        except concurrent.futures.TimeoutError:
            raise RuntimeError(
                '오디오 장치 열기 시간 초과 (6초).\n'
                'PipeWire/PulseAudio가 장치를 점유 중일 수 있습니다.\n'
                'run.sh 에서 pasuspender 사용 여부를 확인하세요.'
            )
        except Exception as e:
            raise RuntimeError(
                f'오디오 스트림 열기 실패: {e}\n\n'
                '해결 방법:\n'
                '1. Scarlett이 USB로 연결되어 있는지 확인\n'
                '2. run.sh 에서 pasuspender 사용 여부 확인\n'
                '   예) pasuspender -- venv/bin/python main.py'
            ) from e

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    @property
    def is_running(self) -> bool:
        return self._stream is not None and self._stream.active

    @staticmethod
    def list_devices():
        """[(index, name, max_in_ch, max_out_ch, hostapi_name, in_lat_ms, out_lat_ms), ...]"""
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
        """Scarlett 장치 인덱스 반환 (Windows: WASAPI 우선, Linux: ALSA 이름 매칭).
        없으면 (None, None)."""
        hostapis = sd.query_hostapis()
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
                best_in = i
                best_in_lat = lat
            lat = d['default_low_output_latency']
            if d['max_output_channels'] > 0 and (is_wasapi or lat < best_out_lat):
                best_out = i
                best_out_lat = lat
        return best_in, best_out

    @staticmethod
    def find_scarlett_alsa_card() -> int | None:
        """Linux에서 /proc/asound/cards 로 Scarlett ALSA 카드 번호를 찾는다."""
        try:
            text = Path('/proc/asound/cards').read_text()
            lines = text.splitlines()
            for i, line in enumerate(lines):
                m = re.match(r'\s*(\d+)\s+\[', line)
                if m:
                    card_idx = int(m.group(1))
                    context = '\n'.join(lines[i:i + 3])
                    if 'scarlett' in context.lower() or 'focusrite' in context.lower():
                        return card_idx
        except OSError:
            pass
        return None

    @staticmethod
    def list_audio_sinks() -> list[tuple[str, str]]:
        """PipeWire/PulseAudio 출력 싱크 목록. [(name, description), ...]"""
        if platform.system() != 'Linux':
            return []
        try:
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            result = subprocess.run(
                ['pactl', 'list', 'sinks'],
                capture_output=True, text=True, timeout=5, env=env,
            )
            sinks: list[tuple[str, str]] = []
            current_name = ''
            for line in result.stdout.splitlines():
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
    def get_default_audio_sink() -> str:
        """현재 PipeWire/PulseAudio 기본 출력 싱크 이름 반환."""
        if platform.system() != 'Linux':
            return ''
        try:
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            result = subprocess.run(
                ['pactl', 'get-default-sink'],
                capture_output=True, text=True, timeout=5, env=env,
            )
            return result.stdout.strip()
        except Exception:
            return ''

    @staticmethod
    def set_default_audio_sink(sink_name: str) -> None:
        """PipeWire/PulseAudio 기본 출력 싱크를 변경한다."""
        if platform.system() != 'Linux':
            return
        try:
            env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}
            subprocess.run(
                ['pactl', 'set-default-sink', sink_name],
                capture_output=True, timeout=5, env=env,
            )
        except Exception:
            pass
