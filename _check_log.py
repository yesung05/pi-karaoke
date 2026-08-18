import paramiko

HOST = '192.168.137.123'; USER = 'karaoke'; PASS = '12345678'
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

_, out, _ = ssh.exec_command('tail -40 /tmp/karaoke.log')
print(out.read().decode())

_, out, _ = ssh.exec_command('grep -c "underrun" /tmp/karaoke.log')
print('Total underruns:', out.read().decode().strip())

_, out, _ = ssh.exec_command('grep "underrun" /tmp/karaoke.log | tail -5')
print('Recent underruns:', out.read().decode())

_, out, _ = ssh.exec_command('ps aux | grep -E "(mpv|main.py)" | grep -v grep')
print('Procs:', out.read().decode())

ssh.close()
