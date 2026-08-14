import paramiko

HOST = '192.168.0.60'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = """
bash -lc 'pkill -f main.py || true; pkill -f \"python.*main.py\" || true; pkill -f \"bash .*run.sh\" || true; echo cleaned'
"""
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
