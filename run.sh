#!/bin/bash
# Pi Karaoke 실행 스크립트
# - 왼쪽 = 미디어창, 오른쪽 = 제어창(터치)
# - xrandr 위치 유지
# - 터치 입력은 오른쪽 모니터(0번)에만 매핑

cd /home/karaoke/pi-karaoke
sleep 5

for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
    echo performance | sudo tee "$g" >/dev/null 2>&1
done

bash /home/karaoke/pi-karaoke/monitor.sh &

export DISPLAY=:0
export XDG_RUNTIME_DIR=/run/user/1000

# xrandr가 알아낸 연결된 출력들을 좌표 순서로 정렬해
# 왼쪽=미디어, 오른쪽=제어 창으로 배치
python3 - <<'PY'
import os
import re
import subprocess

try:
    out = subprocess.check_output(['xrandr', '--query'], text=True, env={**os.environ, 'DISPLAY': ':0'}, stderr=subprocess.DEVNULL)
except Exception:
    raise SystemExit(0)

monitors = []
for line in out.splitlines():
    m = re.match(r'^(\S+)\s+connected(?:\s+primary)?\s+(\d+)x(\d+)\+(\d+)\+(\d+)', line)
    if m:
        monitors.append({
            'name': m.group(1),
            'w': int(m.group(2)),
            'h': int(m.group(3)),
            'x': int(m.group(4)),
            'y': int(m.group(5)),
        })

if len(monitors) >= 2:
    left, right = sorted(monitors, key=lambda m: m['x'])[:2]
    subprocess.run(['xrandr', '--output', left['name'], '--pos', '0x0'], check=False, env={**os.environ, 'DISPLAY': ':0'})
    subprocess.run(['xrandr', '--output', right['name'], '--pos', f'{left["w"]}x0'], check=False, env={**os.environ, 'DISPLAY': ':0'})

    touch_id = None
    try:
        xinput_out = subprocess.check_output(['xinput', 'list'], text=True, env={**os.environ, 'DISPLAY': ':0'}, stderr=subprocess.DEVNULL)
        for line in xinput_out.splitlines():
            if 'touch' in line.lower() and 'xwayland' not in line.lower():
                m = re.search(r'id=(\d+)', line)
                if m:
                    touch_id = m.group(1)
                    break
    except Exception:
        pass

    if touch_id:
        subprocess.run(['xinput', 'map-to-output', touch_id, right['name']], check=False, env={**os.environ, 'DISPLAY': ':0'})
PY

exec taskset -c 0,1 /home/karaoke/pi-karaoke/venv/bin/python main.py >> /tmp/karaoke.log 2>&1
