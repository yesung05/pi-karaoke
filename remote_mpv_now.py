import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.137.123', username='karaoke', password='12345678', timeout=15)

cmd = r'''
echo '--- PROC ---'
ps -eo pid,comm,args --no-headers | grep -E '[m]pv|[m]ain.py' || true
echo '--- MPV ERR ---'
grep -nE 'HTTP error 403|No video or audio streams selected|Errors when loading file|Failed to open|player_client|ytdl-format|youtube' /tmp/mpv_karaoke.log 2>/dev/null | tail -n 120 || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
