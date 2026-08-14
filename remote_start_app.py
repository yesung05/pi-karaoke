import time
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000
cd /home/karaoke/pi-karaoke
nohup /home/karaoke/pi-karaoke/venv/bin/python main.py >> /tmp/karaoke.log 2>&1 &
'''
ssh.exec_command(cmd)

time.sleep(6)
check_cmd = r'''
echo '--- PROCESS ---'
ps -eo pid,comm,args --no-headers | grep '[m]ain.py' || true
echo '--- LOG ---'
tail -n 20 /tmp/karaoke.log 2>/dev/null || true
'''
stdin, stdout, stderr = ssh.exec_command(check_cmd)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
