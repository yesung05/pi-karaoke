import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.60', username='karaoke', password='12345678', timeout=15)

cmd = r'''
cd /home/karaoke/pi-karaoke
/home/karaoke/pi-karaoke/venv/bin/python - <<'PY'
import traceback
from main import _pick_audio_devices
from config import EchoParams
from audio.dsp import EchoProcessor, ReverbProcessor
from audio.engine import AudioEngine

in_dev, out_dev = _pick_audio_devices()
print('PICKED:', in_dev, out_dev)

p = EchoParams()
e = AudioEngine(EchoProcessor(p), ReverbProcessor(p), p, input_device=in_dev, output_device=out_dev)
try:
    e.start()
    print('ENGINE_START_OK')
    e.stop()
except Exception as ex:
    print('ENGINE_START_FAIL:', ex)
    traceback.print_exc()
PY
'''
stdin, stdout, stderr = ssh.exec_command(cmd, timeout=80)
out = stdout.read().decode('utf-8', 'replace')
err = stderr.read().decode('utf-8', 'replace')
print(out)
print(err)
ssh.close()
