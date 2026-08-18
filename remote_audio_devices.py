import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.137.123', username='karaoke', password='12345678', timeout=15)

cmd = r'''
echo '--- arecord -l ---'
arecord -l 2>&1 || true
echo '--- aplay -l ---'
aplay -l 2>&1 || true
echo '--- /proc/asound/cards ---'
cat /proc/asound/cards 2>&1 || true
echo '--- arecord -L (first 80) ---'
arecord -L 2>&1 | head -n 80 || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=45)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
