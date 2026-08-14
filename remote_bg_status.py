import time
import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

ssh.exec_command("pkill -f 'python.*main.py' || true")
ssh.exec_command("bash -lc 'export DISPLAY=:0; export XDG_RUNTIME_DIR=/run/user/1000; cd /home/karaoke/pi-karaoke; nohup /home/karaoke/pi-karaoke/venv/bin/python main.py >/tmp/karaoke.log 2>&1 &' ")

time.sleep(3)
stdin, stdout, stderr = ssh.exec_command("pgrep -af '/home/karaoke/pi-karaoke/venv/bin/python main.py' || true")
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
