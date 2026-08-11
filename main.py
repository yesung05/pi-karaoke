import logging
import platform
import tkinter as tk

from audio.dsp    import EchoProcessor, ReverbProcessor
from audio.engine import AudioEngine
from config       import EchoParams
from core.app_state  import AppState
from core.display    import detect_monitors, assign_displays
from core.playback   import PlaybackManager
from media.player    import MpvPlayer
from gui.control_window import ControlWindow
from gui.media_window   import MediaWindow

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)


_ASOUNDRC = """\
pcm.!default {
    type pulse
}
ctl.!default {
    type pulse
}
"""


def _ensure_asoundrc() -> None:
    """Pi 재부팅 후 ~/.asoundrc 가 사라지는 경우를 대비해 앱 시작마다 재생성."""
    import os
    from pathlib import Path
    if platform.system() != 'Linux':
        return
    rc = Path.home() / '.asoundrc'
    if rc.read_text(errors='replace').strip() == _ASOUNDRC.strip() if rc.exists() else False:
        return
    rc.write_text(_ASOUNDRC)
    logging.info('~/.asoundrc 재생성 완료')


def _pick_audio_devices():
    """오디오 장치 인덱스 반환.

    - Windows: WASAPI Scarlett 우선
    - Linux(Pi): ALSA 'pulse' 장치 → PipeWire → Scarlett
      asoundrc 유무와 무관하게 항상 pulse 장치를 명시적으로 지정
    """
    if platform.system() == 'Windows':
        in_dev, out_dev = AudioEngine.best_scarlett_devices()
        return in_dev, out_dev

    # Linux: 'pulse' 장치를 명시적으로 사용 (asoundrc 없이도 PipeWire 경유)
    return 'pulse', 'pulse'


def main():
    _ensure_asoundrc()

    # ── 오디오 엔진 ──────────────────────────────────────────────
    params      = EchoParams()
    echo_proc   = EchoProcessor(params)
    reverb_proc = ReverbProcessor(params)

    in_dev, out_dev = _pick_audio_devices()
    logging.info('오디오 장치: in=%s  out=%s', in_dev, out_dev)

    engine = AudioEngine(echo_proc, reverb_proc, params,
                         input_device=in_dev, output_device=out_dev)

    # ── 공유 상태 ────────────────────────────────────────────────
    app_state             = AppState()
    app_state.echo_params = params

    # ── mpv 플레이어 ─────────────────────────────────────────────
    player            = MpvPlayer()
    app_state.player  = player

    # ── 모니터 감지 및 배분 ───────────────────────────────────────
    monitors            = detect_monitors()
    media_mon, ctrl_mon = assign_displays(monitors)
    logging.info('감지된 모니터: %s', [m.name for m in monitors])
    logging.info('미디어: %s  제어: %s', media_mon, ctrl_mon)

    # ── 재생 관리자 ──────────────────────────────────────────────
    playback = PlaybackManager(player, app_state, media_mon)

    # ── tkinter: 숨겨진 Root ─────────────────────────────────────
    root = tk.Tk()
    root.withdraw()
    root.title('Pi Karaoke Root')

    # ── HDMI1 제어 창 ────────────────────────────────────────────
    ctrl_win = ControlWindow(
        root, app_state, engine,
        monitor=ctrl_mon, playback_mgr=playback,
    )

    # ── HDMI0 미디어 창 ──────────────────────────────────────────
    media_win = MediaWindow(
        root, app_state,
        monitor=media_mon, playback_mgr=playback,
    )

    # 두 창 상호 참조 연결
    ctrl_win.set_media_window(media_win)

    # ── 단일 모니터 폴백 ─────────────────────────────────────────
    if monitors and not ctrl_mon:
        _apply_single_monitor_layout(ctrl_win, media_win, monitors[0])

    root.mainloop()


def _apply_single_monitor_layout(ctrl_win, media_win, mon):
    """단일 모니터: 좌(미디어) / 우(제어)로 분할."""
    half = mon.width // 2
    media_win.overrideredirect(False)
    media_win.geometry(f'{half}x{mon.height}+{mon.x}+{mon.y}')
    ctrl_win.geometry(f'{half}x{mon.height}+{mon.x + half}+{mon.y}')


if __name__ == '__main__':
    main()
