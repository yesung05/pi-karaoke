import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)
cmd = "echo READY; pgrep -af main.py || true; echo ---; tail -n 20 /tmp/karaoke.log 2>/dev/null || true"
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print('STDOUT_START')
print(out)
print('STDERR_START')
print(err)
print('STDOUT_END')
ssh.close()
