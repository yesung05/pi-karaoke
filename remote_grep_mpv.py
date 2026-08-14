import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
echo '--- FORMAT HITS ---'
grep -n '"format": "18' /tmp/mpv_karaoke.log | tail -n 5 || true
grep -n '"itag": 18' /tmp/mpv_karaoke.log | tail -n 5 || true
grep -n 'ytdl-format' /tmp/mpv_karaoke.log | tail -n 20 || true
echo '--- ERROR HITS ---'
grep -nE 'HTTP error 403|No video or audio streams selected|Errors when loading file' /tmp/mpv_karaoke.log | tail -n 20 || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
