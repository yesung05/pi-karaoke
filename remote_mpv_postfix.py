import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
echo '--- MPV PROCESS ---'
ps -eo pid,comm,args --no-headers | grep -E '[m]pv|[m]ain.py' || true
echo '--- MPV LOG LAST ---'
tail -n 120 /tmp/mpv_karaoke.log 2>/dev/null || true
echo '--- MPV ERR SUMMARY ---'
grep -nE '403|Errors when loading file|No video or audio streams selected|Failed to open|Exiting' /tmp/mpv_karaoke.log 2>/dev/null | tail -n 60 || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
