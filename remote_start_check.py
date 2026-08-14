import time
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

start_cmd = "pkill -f main.py || true; nohup bash /home/karaoke/pi-karaoke/run.sh >/tmp/karaoke.log 2>&1 &"
ssh.exec_command(start_cmd)

for sec in (3, 8, 14):
    time.sleep(sec)
    cmd = "echo --- T+%d ---; pgrep -af 'main.py|run.sh' || true; tail -n 15 /tmp/karaoke.log 2>/dev/null || true" % sec
    stdin, stdout, stderr = ssh.exec_command(cmd)
    print(stdout.read().decode('utf-8', 'replace'))
    print(stderr.read().decode('utf-8', 'replace'))

ssh.close()
