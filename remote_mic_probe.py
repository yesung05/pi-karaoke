import paramiko

HOST = '192.168.137.123'
USER = 'karaoke'
PASS = '12345678'

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(HOST, username=USER, password=PASS, timeout=15)

cmd = r'''
cd /home/karaoke/pi-karaoke
/home/karaoke/pi-karaoke/venv/bin/python - <<'PY'
import traceback
from config import EchoParams
from audio.dsp import EchoProcessor, ReverbProcessor
from audio.engine import AudioEngine

p = EchoParams()
e = AudioEngine(EchoProcessor(p), ReverbProcessor(p), p, input_device='pulse', output_device='pulse')

print('PROBE_START')
try:
    e.start()
    print('MIC_START_OK')
    e.stop()
except Exception as ex:
    print('MIC_START_FAIL:', ex)
    traceback.print_exc()
print('PROBE_END')
PY
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=45)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
