import re
import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class MonitorInfo:
    name:    str
    x:       int
    y:       int
    width:   int
    height:  int
    rotated: bool   # width < height → 세로 회전


def detect_monitors() -> list[MonitorInfo]:
    """xrandr --query 실행 후 connected 모니터 파싱. 실패 시 []."""
    try:
        r = subprocess.run(
            ['xrandr', '--query'],
            capture_output=True, text=True, timeout=5
        )
        return _parse_xrandr(r.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []


def _parse_xrandr(output: str) -> list[MonitorInfo]:
    pattern = re.compile(
        r'^(\S+)\s+connected\s+(?:primary\s+)?(\d+)x(\d+)\+(\d+)\+(\d+)',
        re.MULTILINE
    )
    return [
        MonitorInfo(
            name    = m.group(1),
            width   = int(m.group(2)),
            height  = int(m.group(3)),
            x       = int(m.group(4)),
            y       = int(m.group(5)),
            rotated = int(m.group(2)) < int(m.group(3)),
        )
        for m in pattern.finditer(output)
    ]


def assign_displays(
    monitors: list[MonitorInfo],
) -> tuple[Optional[MonitorInfo], Optional[MonitorInfo]]:
    """
    (media_mon, ctrl_mon) 반환.
    픽셀 수 기준: 큰 쪽 = HDMI0(미디어), 작은 쪽 = HDMI1(제어).
    모니터 1개 → (monitors[0], None).
    모니터 0개 → (None, None).
    """
    if not monitors:
        return None, None
    by_size = sorted(monitors, key=lambda m: m.width * m.height, reverse=True)
    media_mon = by_size[0]
    ctrl_mon  = by_size[1] if len(by_size) > 1 else None
    return media_mon, ctrl_mon
