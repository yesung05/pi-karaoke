import paramiko

HOST = '192.168.137.123'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = r'''
export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000
cd /home/karaoke/pi-karaoke
echo '--- WIFI ---'
nmcli radio wifi 2>/dev/null || true
nmcli device status 2>/dev/null || true
nmcli connection show 2>/dev/null || true
nmcli -f IN-USE,SSID,SIGNAL,SECURITY device wifi list 2>/dev/null | head -n 30 || true

echo '--- REMOTE RUN ---'
ps -eo pid,comm,args --no-headers | grep -E 'python.*main.py|bash.*run.sh' | grep -v grep || true

echo '--- LOG ---'
tail -n 80 /tmp/karaoke.log 2>/dev/null || true

echo '--- XRANDR ---'
xrandr --query 2>/dev/null || true

echo '--- XINPUT ---'
xinput list --name-only 2>/dev/null || true
xinput list --id-only 'QDtech MPI7003' 2>/dev/null || true
xinput list-props 'QDtech MPI7003' 2>/dev/null || true
'''
stdin, stdout, stderr = ssh.exec_command(cmd)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
