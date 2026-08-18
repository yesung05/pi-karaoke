import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.137.123', username='karaoke', password='12345678', timeout=15)

cmd = r'''
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000
timeout 25s bash -x /home/karaoke/pi-karaoke/run.sh
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=40)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print('--- STDOUT ---')
print(out)
print('--- STDERR ---')
print(err)
print('--- EXIT ---')
print(stdout.channel.recv_exit_status())
ssh.close()
