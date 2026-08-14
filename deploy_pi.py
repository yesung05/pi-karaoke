import os
import posixpath
import sys
import time
from pathlib import Path

import paramiko

HOST = '192.168.0.60'
USER = 'karaoke'
PASS = '12345678'
REMOTE_BASE = '/home/karaoke/pi-karaoke'
LOCAL_BASE = Path(r'C:\Users\AILAB\Desktop\projects\pi-karaoke')
FILES_TO_SYNC = [
    'main.py',
    'run.sh',
    'core/display.py',
    'core/app_state.py',
    'core/playback.py',
    'gui/control_window.py',
    'gui/media_window.py',
    'gui/widgets.py',
    'audio/dsp.py',
    'audio/engine.py',
    'media/player.py',
    'media/chart.py',
    'media/yt_search.py',
    'config.py',
    'clap.mp3',
]

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=12)
sftp = ssh.open_sftp()

for rel in FILES_TO_SYNC:
    local_path = str(LOCAL_BASE / rel)
    remote_path = posixpath.join(REMOTE_BASE, rel)
    remote_dir = posixpath.dirname(remote_path)
    try:
        sftp.stat(remote_dir)
    except FileNotFoundError:
        parts = remote_dir.split('/')
        cur = ''
        for p in parts:
            if not p:
                continue
            cur = f'{cur}/{p}' if cur else '/' + p
            try:
                sftp.stat(cur)
            except FileNotFoundError:
                sftp.mkdir(cur)
    sftp.put(local_path, remote_path)
    print(f'uploaded {rel}')

stdin, stdout, stderr = ssh.exec_command(
    "pkill -f main.py || true; "
    "nohup bash /home/karaoke/pi-karaoke/run.sh >/tmp/karaoke.log 2>&1 &"
)
stdout.channel.recv_exit_status()
print('started remote run.sh')

time.sleep(8)
stdin, stdout, stderr = ssh.exec_command(
    "echo --- PROCESS ---; "
    "pgrep -af 'python.*main.py|run.sh' || true; "
    "echo --- LOG ---; "
    "tail -n 30 /tmp/karaoke.log 2>/dev/null || true"
)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
sys.stdout.buffer.write(out.encode('utf-8'))
sys.stdout.buffer.write(err.encode('utf-8'))
sys.stdout.buffer.flush()
ssh.close()
