import logging
import os
import platform
import time
import tkinter as tk

from audio.dsp    import EchoProcessor, ReverbProcessor
from audio.engine import AudioEngine
from config       import EchoParams
from core.app_state  import AppState
from core.display    import detect_monitors, assign_displays, configure_16_10_monitor
from core.playback   import PlaybackManager
from media.player import MpvPlayer
from gui.control_window import ControlWindow
from gui.media_window   import MediaWindow

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)


def _pick_audio_devices():
    """오디오 장치 반환.

    - Windows: WASAPI Scarlett 우선
    - Linux(Pi): ALSA dmix 공유 재생 + 하드웨어 직접 캡처
      * PipeWire Scarlett 정지 → ALSA가 hw:X,0 접근 가능
      * 입력: 하드웨어 직접 (커널 IRQ, underrun 없음)
      * 출력: scarlett_dmix (mpv와 공유)
    """
    if platform.system() == 'Windows':
        return AudioEngine.best_scarlett_devices()

    import os, re, subprocess
    from pathlib import Path
    import sounddevice as sd
    env = {**os.environ, 'XDG_RUNTIME_DIR': f'/run/user/{os.getuid()}'}

    # ── Step 1: PortAudio 스캔으로 Scarlett 카드 번호 확인 ──────
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass

    card = None
    in_dev_idx = None
    for i, d in enumerate(sd.query_devices()):
        name = d['name']
        if ('scarlett' in name.lower() or 'focusrite' in name.lower()) \
                and 'dmix' not in name.lower() and 'dsnoop' not in name.lower():
            m = re.search(r'hw:(\d+)', name)
            if m and d['max_input_channels'] > 0:
                card = int(m.group(1))
                in_dev_idx = i
                logging.info('Scarlett 하드웨어 장치: [%d] %s (card=%d)', i, name, card)
                break

    if card is None:
        card = AudioEngine.find_scarlett_alsa_card()

    if card is None:
        logging.warning('Scarlett 장치를 찾지 못함 → pulse 폴백')
        return 'pulse', 'pulse'

    # ── Step 2: PipeWire Scarlett 정지 → ALSA 직접 접근 확보 ───
    for list_cmd, suspend_cmd in [
        (['pactl', 'list', 'sources', 'short'], 'suspend-source'),
        (['pactl', 'list', 'sinks',   'short'], 'suspend-sink'),
    ]:
        try:
            res = subprocess.run(list_cmd, capture_output=True, text=True, timeout=5, env=env)
            for line in res.stdout.splitlines():
                parts = line.split()
                if len(parts) < 2:
                    continue
                name = parts[1]
                if ('scarlett' in name.lower() or 'focusrite' in name.lower()) \
                        and 'monitor' not in name.lower():
                    subprocess.run(['pactl', suspend_cmd, name, '1'],
                                   capture_output=True, timeout=5, env=env)
                    logging.info('PipeWire %s 정지: %s', suspend_cmd, name)
        except Exception as e:
            logging.warning('PipeWire suspend 실패: %s', e)

    time.sleep(0.3)  # PipeWire가 장치를 완전히 해제할 시간

    # ── Step 3: scarlett_dmix .asoundrc 생성 (재생 공유용) ──────
    asoundrc = (
        f'pcm.scarlett_dmix {{\n'
        f'    type dmix\n'
        f'    ipc_key 2048\n'
        f'    ipc_key_add_uid yes\n'
        f'    slave {{\n'
        f'        pcm "hw:{card},0"\n'
        f'        rate 48000\n'
        f'        format S32_LE\n'
        f'        period_size 512\n'
        f'        buffer_size 2048\n'
        f'        channels 2\n'
        f'    }}\n'
        f'    bindings {{ 0 0  1 1 }}\n'
        f'    hint {{\n'
        f'        show yes\n'
        f'        description "Scarlett Solo shared playback"\n'
        f'    }}\n'
        f'}}\n'
        f'\n'
        f'pcm.!default {{\n'
        f'    type pulse\n'
        f'}}\n'
        f'ctl.!default {{\n'
        f'    type pulse\n'
        f'}}\n'
    )
    Path.home().joinpath('.asoundrc').write_text(asoundrc)
    logging.info('~/.asoundrc 재생성: dmix card=%d period=512 buf=2048', card)

    # ── Step 4: PortAudio 재초기화 → dmix 장치 인식 ─────────────
    try:
        sd._terminate()
        sd._initialize()
    except Exception as e:
        logging.warning('PortAudio 재초기화 실패: %s', e)

    # C 엔진은 ALSA 문자열을 직접 사용하므로 sounddevice 장치 목록에
    # scarlett_dmix가 보이지 않아도 우선 적용해본다.
    alsa_cap = f'hw:{card},0'
    logging.info('ALSA 모드: in=%s out=scarlett_dmix (dmix 우선)', alsa_cap)
    return alsa_cap, 'scarlett_dmix'


def main():
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
    # out_dev가 pulse 폴백이면 mpv도 pulse, dmix면 alsa/dmix
    if out_dev and out_dev != 'pulse':
        player.audio_device = f'alsa/{out_dev}'
    app_state.player  = player

    # ── 모니터 감지 및 해상도 설정 ─────────────────────────────────
    monitors = detect_monitors()
    if platform.system() == 'Linux':
        os.environ.setdefault('DISPLAY', ':0')
        configure_16_10_monitor(monitors)
        time.sleep(1)  # xrandr 적용 후 화면 좌표 안정화
        monitors = detect_monitors()  # 해상도 변경 후 재감지
    media_mon, ctrl_mon = assign_displays(monitors)
    logging.info('감지된 모니터: %s', [m.name for m in monitors])
    logging.info('미디어: %s  제어: %s', media_mon, ctrl_mon)

    # ── 재생 관리자 ──────────────────────────────────────────────
    playback = PlaybackManager(player, app_state, media_mon)

    # ── tkinter: 숨겨진 Root ─────────────────────────────────────
    root = tk.Tk()
    root.title('Pi Karaoke Root')
    root.withdraw()

    # ── 비디오 배경 창 (mpv --wid 임베드용) ──────────────────────
    # openbox 같은 WM이 mpv 일반 창을 숨기는 문제 우회:
    # overrideredirect=True 창은 WM을 거치지 않아 항상 표시됨.
    if platform.system() == 'Linux' and media_mon:
        video_bg = tk.Toplevel(root)
        video_bg.overrideredirect(True)
        video_bg.geometry(
            f'{media_mon.width}x{media_mon.height}+{media_mon.x}+{media_mon.y}'
        )
        video_bg.configure(bg='black')
        video_bg.lower()  # MediaWindow보다 아래에 위치
        root.update()
        player.video_wid = video_bg.winfo_id()
        logging.info('비디오 배경 창 WID: %d', player.video_wid)
    else:
        video_bg = None

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

    # X11에서 창이 비어 보이거나 가려지지 않도록 보이는 시점에 강제 반영
    root.update_idletasks()
    ctrl_win.update_idletasks()
    media_win.update_idletasks()
    ctrl_win.lift()
    media_win.lift()

    # ── 단일 모니터 폴백 ─────────────────────────────────────────
    if monitors and not ctrl_mon:
        _apply_single_monitor_layout(ctrl_win, media_win, monitors[0])

    # 노래방 시작 시 마이크 엔진을 기본 ON 상태로 준비한다.
    def _start_mic_default():
        try:
            if not engine.is_running:
                engine.start()
                logging.info('마이크 기본 상태: ON')
        except Exception:
            logging.exception('마이크 기본 시작 실패')

    root.after(500, _start_mic_default)
    root.mainloop()


def _apply_single_monitor_layout(ctrl_win, media_win, mon):
    """단일 모니터: 좌(미디어) / 우(제어)로 분할."""
    half = mon.width // 2
    media_win.overrideredirect(False)
    media_win.geometry(f'{half}x{mon.height}+{mon.x}+{mon.y}')
    ctrl_win.geometry(f'{half}x{mon.height}+{mon.x + half}+{mon.y}')


if __name__ == '__main__':
    main()
