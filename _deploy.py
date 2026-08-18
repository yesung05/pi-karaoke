"""
Pi 카라오케 전체 재배포 스크립트
- 기존 디렉토리 삭제 후 전체 파일 업로드
- 시스템 패키지 설치, venv 생성, pip 패키지 설치
- C 오디오 엔진 빌드
- LXDE autostart + X11 설정
"""
import os, paramiko, time, sys
from pathlib import Path

HOST   = '192.168.137.123'
USER   = 'karaoke'
PASS   = '12345678'
REMOTE = '/home/karaoke/pi-karaoke'
BASE   = Path(r'C:\Users\AILAB\Desktop\projects\pi-karaoke')

# ── SSH 연결 ──────────────────────────────────────────────────
for attempt in range(8):
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(HOST, username=USER, password=PASS, timeout=15)
        print('SSH 연결 성공')
        break
    except Exception as e:
        print(f'시도 {attempt+1}: {e}')
        time.sleep(5)
else:
    sys.exit('SSH 연결 실패')

def run(cmd, timeout=60):
    _, o, e = ssh.exec_command(cmd, timeout=timeout)
    out = o.read().decode(errors='replace')
    err = e.read().decode(errors='replace')
    combined = (out + err).strip()
    if combined:
        print(combined)
    return combined

# ── 기존 디렉토리 삭제 ────────────────────────────────────────
print('\n[1/8] 기존 디렉토리 삭제...')
run(f'rm -rf {REMOTE}')
run(f'mkdir -p {REMOTE}/audio {REMOTE}/core {REMOTE}/gui {REMOTE}/media')

# ── 파일 업로드 ───────────────────────────────────────────────
print('\n[2/8] 파일 업로드...')

SH_EXTS = {'.sh'}

# 업로드할 파일 목록 (로컬경로, 원격경로)
files = [
    # 루트
    (BASE / 'main.py',               f'{REMOTE}/main.py'),
    (BASE / 'config.py',             f'{REMOTE}/config.py'),
    (BASE / 'requirements.txt',      f'{REMOTE}/requirements.txt'),
    (BASE / 'run.sh',                f'{REMOTE}/run.sh'),
    (BASE / 'monitor.sh',            f'{REMOTE}/monitor.sh'),
    # audio
    (BASE / 'audio/__init__.py',     f'{REMOTE}/audio/__init__.py'),
    (BASE / 'audio/dsp.py',          f'{REMOTE}/audio/dsp.py'),
    (BASE / 'audio/engine.py',       f'{REMOTE}/audio/engine.py'),
    (BASE / 'audio/karaoke_audio.c', f'{REMOTE}/audio/karaoke_audio.c'),
    (BASE / 'audio/Makefile',        f'{REMOTE}/audio/Makefile'),
    # core
    (BASE / 'core/__init__.py',      f'{REMOTE}/core/__init__.py'),
    (BASE / 'core/app_state.py',     f'{REMOTE}/core/app_state.py'),
    (BASE / 'core/display.py',       f'{REMOTE}/core/display.py'),
    (BASE / 'core/playback.py',      f'{REMOTE}/core/playback.py'),
    # gui
    (BASE / 'gui/__init__.py',       f'{REMOTE}/gui/__init__.py'),
    (BASE / 'gui/app.py',            f'{REMOTE}/gui/app.py'),
    (BASE / 'gui/control_window.py', f'{REMOTE}/gui/control_window.py'),
    (BASE / 'gui/media_window.py',   f'{REMOTE}/gui/media_window.py'),
    (BASE / 'gui/widgets.py',        f'{REMOTE}/gui/widgets.py'),
    # media
    (BASE / 'media/__init__.py',     f'{REMOTE}/media/__init__.py'),
    (BASE / 'media/chart.py',        f'{REMOTE}/media/chart.py'),
    (BASE / 'media/player.py',       f'{REMOTE}/media/player.py'),
    (BASE / 'media/yt_search.py',    f'{REMOTE}/media/yt_search.py'),
]

sftp = ssh.open_sftp()
for local, remote in files:
    local = Path(local)
    if not local.exists():
        print(f'  건너뜀 (없음): {local.name}')
        continue
    data = local.read_bytes()
    if local.suffix in SH_EXTS:
        data = data.replace(b'\r\n', b'\n')  # CRLF -> LF
    with sftp.open(remote, 'wb') as rf:
        rf.write(data)
    print(f'  -> {remote}')
sftp.close()

run(f'chmod +x {REMOTE}/run.sh {REMOTE}/monitor.sh')

# ── 시스템 패키지 설치 ────────────────────────────────────────
print('\n[3/8] 시스템 패키지 설치...')
run(
    'sudo apt-get update -qq && '
    'sudo apt-get install -y '
    'python3 python3-venv python3-tk '
    'mpv wmctrl util-linux '
    'gcc make libasound2-dev '
    'libportaudio2 pulseaudio-utils '
    '2>&1 | tail -5',
    timeout=300,
)

# ── venv 생성 ─────────────────────────────────────────────────
print('\n[4/8] Python venv 생성...')
run(f'python3 -m venv {REMOTE}/venv', timeout=60)
print('venv 생성 완료')

# ── pip 패키지 설치 ───────────────────────────────────────────
print('\n[5/8] pip 패키지 설치 (시간 소요)...')
run(
    f'{REMOTE}/venv/bin/pip install --upgrade pip -q && '
    f'{REMOTE}/venv/bin/pip install -r {REMOTE}/requirements.txt -q && '
    f'echo pip_ok',
    timeout=300,
)

# ── C 오디오 엔진 빌드 ────────────────────────────────────────
print('\n[6/8] C 오디오 엔진 빌드...')
run(f'make -C {REMOTE}/audio karaoke_audio && echo build_ok', timeout=60)

# ── LXDE autostart 등록 ───────────────────────────────────────
print('\n[7/8] autostart 등록...')
run('mkdir -p /home/karaoke/.config/lxsession/LXDE-pi')
run('mkdir -p /home/karaoke/.config/openbox')

# LXDE-pi (lxsession) 용
run(
    f'printf "@bash {REMOTE}/run.sh\\n" '
    f'> /home/karaoke/.config/lxsession/LXDE-pi/autostart && '
    f'echo lxde_autostart_ok'
)
# Openbox 용 (fallback)
run(
    f'printf "bash {REMOTE}/run.sh &\\n" '
    f'> /home/karaoke/.config/openbox/autostart && '
    f'echo openbox_autostart_ok'
)

# ── X11 세션 전환 ─────────────────────────────────────────────
print('\n[8/8] X11 세션 전환 확인...')
result = run('sudo raspi-config nonint do_wayland W1 && echo x11_ok', timeout=30)
if 'x11_ok' not in result:
    print('  (이미 X11이거나 설정 완료)')

# ── sudo 무암호 설정 (run.sh의 governor 설정에 필요) ──────────
run(
    'echo "karaoke ALL=(ALL) NOPASSWD: ALL" | '
    'sudo tee /etc/sudoers.d/karaoke > /dev/null && '
    'echo sudoers_ok'
)

print()
print('=' * 50)
print('배포 완료! Pi를 재부팅하면 앱이 자동 시작됩니다.')
print('재부팅: sudo reboot')
print('=' * 50)

ssh.close()
