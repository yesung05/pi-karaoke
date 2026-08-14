#!/bin/bash
# 상시 성능 모니터 — 15초 간격, /tmp/karaoke_mon.log (최대 500줄 롤링)
LOG=/tmp/karaoke_mon.log
MAX_LINES=500

while true; do
    TS=$(date '+%H:%M:%S')

    # 온도 / 스로틀
    TEMP=$(vcgencmd measure_temp 2>/dev/null | grep -oP '[\d.]+')
    THROT=$(vcgencmd get_throttled 2>/dev/null | grep -oP '0x\w+')

    # 코어별 CPU 사용률 (1초 평균)
    CPU_LINE=$(top -bn2 -d0.5 | grep "^%Cpu" | tail -1)
    USR=$(echo "$CPU_LINE" | grep -oP '[\d.]+(?= us)')
    SYS=$(echo "$CPU_LINE" | grep -oP '[\d.]+(?= sy)')

    # python / mpv 프로세스 정보
    PYINFO=$(ps -eo psr,pcpu,pid,comm,args --no-headers | grep 'main\.py' | grep -v grep | head -1)
    MPVINFO=$(ps -eo psr,pcpu,pid,comm --no-headers | grep '^[0-9].*mpv' | grep -v grep | head -1)

    # xrun 총계
    XRUN=$(grep -c 'underrun' /tmp/karaoke.log 2>/dev/null || echo 0)

    # RT 클래스 확인 (python 프로세스 스레드 중 FF=SCHED_FIFO)
    PY_PID=$(pgrep -f main.py | head -1)
    RT_CNT=""
    if [ -n "$PY_PID" ]; then
        RT_CNT=$(ps -eLo cls --pid "$PY_PID" 2>/dev/null | grep -c 'FF' || echo 0)
    fi

    LINE="$TS | temp=${TEMP}C throt=$THROT | cpu_usr=${USR}% sys=${SYS}% | xrun=$XRUN | rt_threads=$RT_CNT | py=[${PYINFO:-none}] | mpv=[${MPVINFO:-none}]"
    echo "$LINE" >> "$LOG"

    # 롤링: 500줄 초과 시 앞 100줄 삭제
    LINE_CNT=$(wc -l < "$LOG")
    if [ "$LINE_CNT" -gt "$MAX_LINES" ]; then
        tail -n 400 "$LOG" > "${LOG}.tmp" && mv "${LOG}.tmp" "$LOG"
    fi

    sleep 15
done
