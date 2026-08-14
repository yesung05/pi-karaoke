import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
echo '--- PS ---'
ps -eo pid,comm,args --no-headers | grep -E 'main.py|mpv' | grep -v grep || true
echo '--- KARAOKE LOG ---'
tail -n 140 /tmp/karaoke.log 2>/dev/null || true
echo '--- MPV LOG ---'
tail -n 140 /tmp/mpv_karaoke.log 2>/dev/null || true
echo '--- DNS ---'
getent hosts www.youtube.com || true
getent hosts www.tjmedia.com || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
