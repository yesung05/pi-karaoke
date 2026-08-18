import paramiko

HOST = '192.168.137.123'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = """
bash -lc '
  pkill -TERM -f "[p]ython.*main.py" || true
  pkill -TERM -f "[m]pv" || true
  pkill -TERM -f "[k]araoke_audio" || true
  pkill -TERM -f "[m]onitor.sh" || true
  pkill -TERM -f "[b]ash .*run.sh" || true
  sleep 2
  pkill -KILL -f "[p]ython.*main.py" || true
  pkill -KILL -f "[m]pv" || true
  pkill -KILL -f "[k]araoke_audio" || true
  pkill -KILL -f "[m]onitor.sh" || true
  pkill -KILL -f "[b]ash .*run.sh" || true
  echo cleaned
  echo --- remaining project processes ---
  pgrep -af "main.py|mpv|karaoke_audio|monitor.sh|run.sh" || true
'
"""
stdin, stdout, stderr = ssh.exec_command(cmd)
print(stdout.read().decode('utf-8', 'replace'))
print(stderr.read().decode('utf-8', 'replace'))
ssh.close()
