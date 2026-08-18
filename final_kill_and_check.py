import paramiko

HOST = '192.168.137.123'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = """
set -e
pkill -f main.py || true
pkill -f '/home/karaoke/pi-karaoke/venv/bin/python main.py' || true
printf 'CLEANED\\n'
ps -eo pid,comm,args --no-headers | grep -E 'python.*main.py|bash.*run.sh' | grep -v grep || true
printf '\\n--- LOG ---\\n'
tail -n 80 /tmp/karaoke.log 2>/dev/null || true
"""
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
