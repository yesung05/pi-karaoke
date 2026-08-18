import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.137.123', username='karaoke', password='12345678', timeout=15)

cmd = r'''
cd /home/karaoke/pi-karaoke/audio
echo '--- pulse/pulse ---'
./karaoke_audio pulse pulse 2>&1 | head -n 20 || true
echo EXIT:$?
echo '--- default/default ---'
./karaoke_audio default default 2>&1 | head -n 20 || true
echo EXIT:$?
echo '--- hw0/hw0 ---'
./karaoke_audio hw:0,0 hw:0,0 2>&1 | head -n 20 || true
echo EXIT:$?
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=45)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
