import paramiko

HOST = '192.168.137.123'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = (
    "export DISPLAY=:0; "
    "export XDG_RUNTIME_DIR=/run/user/1000; "
    "cd /home/karaoke/pi-karaoke; "
    "timeout 25s /home/karaoke/pi-karaoke/venv/bin/python main.py"
)
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=40)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print('--- STDOUT ---')
print(out)
print('--- STDERR ---')
print(err)
print('--- EXIT STATUS ---')
print(stdout.channel.recv_exit_status())
ssh.close()
