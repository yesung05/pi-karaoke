import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
cd /home/karaoke/pi-karaoke
rm -f /tmp/mpv_karaoke.log
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000
/home/karaoke/pi-karaoke/venv/bin/python - <<'PY'
import time
from media.player import MpvPlayer

p = MpvPlayer()
p.play('https://www.youtube.com/watch?v=n2FzdvRGXNc', x=0, y=0, width=1280, height=720)
time.sleep(8)
p.stop()
print('PROBE_DONE')
PY

echo '--- MPV CMD ---'
grep -n 'Command line options' /tmp/mpv_karaoke.log || true
echo '--- MPV ERR ---'
grep -nE 'HTTP error 403|No video or audio streams selected|Errors when loading file' /tmp/mpv_karaoke.log || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=120)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
