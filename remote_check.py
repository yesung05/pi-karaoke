import paramiko

HOST = '192.168.0.60'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = r'''
set -x
echo '--- ps';
ps -eo pid,comm,args --no-headers | grep -E 'python.*main.py|bash.*run.sh' | grep -v grep || true;
echo '--- log';
tail -n 80 /tmp/karaoke.log 2>/dev/null || true;
echo '--- repo';
ls -l /home/karaoke/pi-karaoke | sed -n '1,20p';
'''
import sys
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
sys.stdout.buffer.write(out.encode('utf-8'))
sys.stdout.buffer.write(err.encode('utf-8'))
sys.stdout.buffer.flush()
ssh.close()
