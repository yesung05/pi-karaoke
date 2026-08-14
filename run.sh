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
    # 제어용 서브 모니터의 네이티브 모드(지원되는 경우)를 우선 적용.
    # 일부 어댑터는 1024x600을 보고하지 않으므로 실패해도 기존 모드를 유지한다.
    xenv = {**os.environ, 'DISPLAY': ':0'}
    mode_name = '1024x576'
    mode_result = subprocess.run(['xrandr', '--query'], capture_output=True,
                                 text=True, env=xenv)
    subprocess.run(['xrandr', '--output', right['name'], '--mode', mode_name],
                   check=False, env=xenv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['xrandr', '--output', left['name'], '--pos', '0x0'], check=False, env={**os.environ, 'DISPLAY': ':0'})
    subprocess.run(['xrandr', '--output', right['name'], '--pos', f'{left["w"]}x0'], check=False, env={**os.environ, 'DISPLAY': ':0'})

    touch_id = None
    try:
        xinput_out = subprocess.check_output(['xinput', 'list'], text=True, env={**os.environ, 'DISPLAY': ':0'}, stderr=subprocess.DEVNULL)
        for line in xinput_out.splitlines():
            # QDtech MPI7003처럼 이름에 touch가 없는 USB 터치 패널도 포함한다.
            lname = line.lower()
            if (('touch' in lname or 'qdtech' in lname or 'touchscreen' in lname)
                    and 'xwayland' not in lname):
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
