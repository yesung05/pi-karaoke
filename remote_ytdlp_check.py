import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
cd /home/karaoke/pi-karaoke
./venv/bin/yt-dlp --version || true
./venv/bin/yt-dlp -F "https://www.youtube.com/watch?v=n2FzdvRGXNc" | head -n 30 || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=80)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
