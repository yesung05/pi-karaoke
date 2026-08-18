import time
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.137.123', username='karaoke', password='12345678', timeout=15)

cmd = r'''
pkill -f 'python.*main.py' || true
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000
cd /home/karaoke/pi-karaoke
nohup /home/karaoke/pi-karaoke/venv/bin/python main.py >> /tmp/karaoke.log 2>&1 &
'''
ssh.exec_command(cmd)
time.sleep(5)
check = r'''
echo '--- PS ---'
ps -eo pid,comm,args --no-headers | grep '[m]ain.py' || true
echo '--- LOG LAST ---'
tail -n 25 /tmp/karaoke.log 2>/dev/null || true
'''
stdin, stdout, stderr = ssh.exec_command(check)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
