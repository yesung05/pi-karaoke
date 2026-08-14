import paramiko

HOST = '192.168.0.60'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = r'''
set +e
echo '--- PROCESS ---'
pgrep -af 'main.py|python.*main.py' || true
echo '--- LOG TAIL ---'
tail -n 220 /tmp/karaoke.log 2>/dev/null || true
echo '--- LOG MATCH ---'
grep -nE '마이크 엔진 시작 실패|Traceback|ERROR|Exception|PortAudio|ALSA|sounddevice|Invalid|No such file|Device|XRUN' /tmp/karaoke.log 2>/dev/null | tail -n 120 || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
