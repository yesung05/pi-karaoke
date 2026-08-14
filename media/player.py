import json
import logging
import os
import platform
import socket
import subprocess
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

MPV_LOG = '/tmp/mpv_karaoke.log'


class PlayerState:
    STOPPED = 'stopped'
    LOADING = 'loading'
    PLAYING = 'playing'
    PAUSED  = 'paused'


class MpvPlayer:
    """mpv subprocess + Unix IPC 소켓 래퍼."""

    IPC_PATH = '/tmp/mpv-karaoke.sock'

    def __init__(self):
        self._proc:   Optional[subprocess.Popen] = None
        self._state:  str                        = PlayerState.STOPPED
        self._lock    = threading.Lock()
        self._end_cb: Optional[Callable[[], None]] = None
        self._target_geom: tuple[int, int, int, int] = (0, 0, 1920, 1080)
        self.audio_device: str = ''  # 'pulse/<sink_name>'; 빈 문자열이면 PipeWire 기본 싱크
        self._saved_speed = 1.0
        self._saved_pitch = 0
        self._saved_volume = 40

    def set_end_callback(self, cb: Callable[[], None]) -> None:
        self._end_cb = cb

    # ── 재생 제어 ─────────────────────────────────────────────────

    def play(self, youtube_url: str, *,
             x: int = 0, y: int = 0,
             width: int = 1920, height: int = 1080) -> None:
        self.stop()
        self._target_geom = (x, y, width, height)

        env = os.environ.copy()
        env.setdefault('DISPLAY', ':0')
        env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')

        # Pi 4: AV1/VP9 소프트웨어 디코딩 → CPU 과부하. H.264 720p + hwdec + fast 프로파일로 고정.
        # best[ext=mp4] 단독은 사전 합성 스트림만 탐색해 실제론 360p 이하가 선택됨.
        # bestvideo+bestaudio 분리 스트림으로 실질적 720p H.264를 확보한다.
        is_linux = platform.system() == 'Linux'
        ytdl_format = (
            # 병합 스트림 우선: 단일 컨테이너라 오디오·영상 PTS가 이미 정렬됨 → 싱크 안정
            # 분리 스트림(bestvideo+bestaudio)은 DASH 트랙별 초기 PTS가 영상마다 달라
            # 곡마다 딜레이가 달라지는 문제 발생 → 폴백으로만 사용
            # 720p H.264 영상 + 오디오를 우선 사용해 HD 화질을 확보한다.
            # 720p가 없는 영상은 결합 스트림/기존 best로 자동 fallback.
            'bestvideo[height<=720][vcodec^=avc1]+bestaudio'
            '/best[height<=720]'
            '/best'
            if is_linux else
            'bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best'
        )
        cmd = [
            'mpv',
            '--no-terminal',
            '--no-sub',
            '--ytdl',
            f'--ytdl-format={ytdl_format}',
            f'--geometry={width}x{height}+{x}+{y}',
            '--fullscreen',
            '--no-border',
            '--x11-bypass-compositor=yes',
            f'--input-ipc-server={self.IPC_PATH}',
            f'--log-file={MPV_LOG}',
            '--msg-level=all=warn',
            '--profile=fast',
            # dmix의 snd_pcm_delay()가 실제보다 큰 값을 반환하는 알려진 문제로
            # --video-sync=audio 사용 시 오디오 클럭이 느리게 인식돼 영상이 늦음.
            # desync: 오디오·영상 각각 스트림 PTS 기반으로 독립 재생 (dmix 클럭 의존 제거)
            '--video-sync=audio',
            '--audio-pitch-correction=no',
            '--audio-buffer=0.2',
            # 720p 분리 스트림은 네트워크 순간 변동에 민감하므로
            # 재생 중 버퍼를 확보해 끊김을 흡수한다.
            '--cache=yes',
            '--cache-secs=30',
            '--demuxer-readahead-secs=30',
            '--demuxer-max-bytes=200MiB',
        ]
        if is_linux:
            import sys
            venv_ytdlp = str(
                __import__('pathlib').Path(sys.executable).parent / 'yt-dlp'
            )
            cmd += [
                f'--script-opts=ytdl_hook-ytdl_path={venv_ytdlp}',
                '--hwdec=v4l2m2m-copy',      # Pi 4 H.264 하드웨어 디코딩 → RAM 복사 (DMA-BUF 없음 → X11 락 없음)
                '--gpu-context=x11egl',      # EGL on X11 (copy모드라 DMA-BUF import 없음 → 마우스 정상)
                '--ao=alsa',                 # ALSA 직접 출력 (PipeWire 우회)
            ]
            # dmix 장치명: main.py가 설정한 값 사용 (폴백 시 pulse와 일치)
            ao_dev = self.audio_device if self.audio_device else 'alsa/scarlett_dmix'
            cmd.append(f'--audio-device={ao_dev}')
        elif self.audio_device:
            cmd.append(f'--audio-device={self.audio_device}')
        cmd.append(youtube_url)

        # mpv를 코어 2,3에 고정(오디오 코어 0,1과 분리)
        # nice를 제거: 오디오 스레드가 dmix 5.3ms 주기를 지키려면 기본 우선순위 필요
        launch_cmd = (['taskset', '-c', '2,3'] + cmd) if is_linux else cmd

        with self._lock:
            try:
                self._proc = subprocess.Popen(
                    launch_cmd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._state = PlayerState.LOADING
            except FileNotFoundError:
                logger.error('mpv를 찾을 수 없습니다. sudo apt install mpv 로 설치하세요.')
                self._state = PlayerState.STOPPED
                return

        threading.Thread(target=self._monitor_proc, daemon=True).start()
        threading.Thread(
            target=self._fix_window_position,
            args=(x, y, width, height),
            daemon=True,
        ).start()
        threading.Thread(target=self._apply_saved_settings, daemon=True).start()

    def _apply_saved_settings(self) -> None:
        time.sleep(1.0)
        if self._saved_speed != 1.0:
            self.set_speed(self._saved_speed)
        if self._saved_pitch != 0:
            self.set_pitch(self._saved_pitch)
        self.set_volume(self._saved_volume)

    def _fix_window_position(self, x: int, y: int, width: int, height: int) -> None:
        """mpv 창이 뜬 후 wmctrl로 강제 위치 조정 (labwc 재배치 방지)."""
        env = {**os.environ, 'DISPLAY': ':0'}
        for delay in (1.5, 3.0):
            time.sleep(delay)
            if self._proc is None or self._proc.poll() is not None:
                break
            subprocess.run(
                ['wmctrl', '-r', 'mpv', '-e', f'0,{x},{y},{width},{height}'],
                env=env, capture_output=True,
            )
            subprocess.run(
                ['wmctrl', '-r', 'mpv', '-b', 'add,above'],
                env=env, capture_output=True,
            )

    def _monitor_proc(self) -> None:
        proc = self._proc
        if proc:
            proc.wait()
        with self._lock:
            if self._state != PlayerState.STOPPED:
                self._state = PlayerState.STOPPED
        if self._end_cb:
            self._end_cb()

    def pause(self) -> None:
        self._ipc({'command': ['set_property', 'pause', True]})
        with self._lock:
            self._state = PlayerState.PAUSED

    def resume(self) -> None:
        self._ipc({'command': ['set_property', 'pause', False]})
        with self._lock:
            self._state = PlayerState.PLAYING

    def toggle_pause(self) -> None:
        self._ipc({'command': ['cycle', 'pause']})

    def set_volume(self, pct: int) -> None:
        self._saved_volume = max(0, min(130, pct))
        self._ipc({'command': ['set_property', 'volume', self._saved_volume]})

    def set_speed(self, factor: float) -> None:
        """Change song tempo without restarting the current video."""
        self._saved_speed = max(0.5, min(1.5, factor))
        self._ipc({'command': ['set_property', 'speed', self._saved_speed]})

    def set_pitch(self, semitones: int) -> None:
        """Apply a pitch shift to the current song via mpv's lavfi filter."""
        self._saved_pitch = max(-6, min(6, semitones))
        semitones = self._saved_pitch
        # Replace (rather than append) one filter.  atempo compensates for
        # asetrate's duration change, so pitch changes do not alter tempo.
        if not semitones:
            self._ipc({'command': ['af', 'clr', 'all']})
            return
        ratio = 2.0 ** (float(semitones) / 12.0)
        inv = 1.0 / ratio
        self._ipc({'command': ['af', 'set',
                               f'lavfi=[asetrate=48000*{ratio:.6f},aresample=48000,atempo={inv:.6f}]']})

    def play_effect(self, path: str) -> None:
        """Play a short UI effect without interrupting the karaoke video."""
        env = os.environ.copy()
        env.setdefault('DISPLAY', ':0')
        env.setdefault('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}')
        cmd = ['mpv', '--no-video', '--no-terminal', '--really-quiet',
               '--ao=alsa', '--audio-device=alsa/scarlett_dmix', path]
        try:
            subprocess.Popen(cmd, env=env, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError:
            logger.warning('효과음 재생 실패: %s', path)

    def skip(self) -> None:
        self.stop()

    def stop(self) -> None:
        with self._lock:
            proc, self._proc = self._proc, None
            self._state = PlayerState.STOPPED
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        try:
            os.unlink(self.IPC_PATH)
        except OSError:
            pass

    # ── IPC ───────────────────────────────────────────────────────

    def _ipc(self, cmd: dict) -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(self.IPC_PATH)
                s.sendall(json.dumps(cmd).encode() + b'\n')
        except OSError:
            pass

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_playing(self) -> bool:
        return self.state in (PlayerState.LOADING, PlayerState.PLAYING)

    def get_mpv_log(self) -> str:
        try:
            with open(MPV_LOG) as f:
                return f.read()
        except OSError:
            return ''
