import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


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


def _parse_xrandr_modes(output: str) -> dict[str, list[tuple[int, int]]]:
    """xrandr 출력에서 출력 포트별 지원 해상도 목록 반환."""
    result: dict[str, list[tuple[int, int]]] = {}
    current_output: Optional[str] = None
    for line in output.splitlines():
        m = re.match(r'^(\S+)\s+connected', line)
        if m:
            current_output = m.group(1)
            result[current_output] = []
            continue
        if current_output:
            m2 = re.match(r'^\s+(\d+)x(\d+)', line)
            if m2:
                result[current_output].append((int(m2.group(1)), int(m2.group(2))))
    return result


def set_monitor_resolution(output_name: str, width: int, height: int) -> bool:
    """xrandr로 특정 출력의 해상도를 설정. 성공 시 True."""
    try:
        r = subprocess.run(
            ['xrandr', '--output', output_name, '--mode', f'{width}x{height}'],
            capture_output=True, text=True, timeout=8,
            env={**__import__('os').environ, 'DISPLAY': ':0'},
        )
        if r.returncode == 0:
            logger.info('xrandr: %s → %dx%d 설정 완료', output_name, width, height)
            return True
        logger.warning('xrandr 해상도 설정 실패 (%s): %s', output_name, r.stderr.strip())
        return False
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning('xrandr 실행 오류: %s', e)
        return False


def configure_16_10_monitor(monitors: list[MonitorInfo]) -> None:
    """두 번째 HDMI 포트(미디어 창)를 16:10 최적 해상도로 설정.

    지원 모드 중 16:10 비율(w/h ≈ 1.6)인 것 중 가장 높은 해상도를 선택.
    이미 16:10 해상도면 건드리지 않음.
    """
    if not monitors:
        return

    def _port_num(m: MonitorInfo) -> int:
        digits = ''.join(filter(str.isdigit, m.name))
        return int(digits) if digits else 0

    ordered = sorted(monitors, key=_port_num)
    if len(ordered) < 2:
        return

    target = ordered[1]  # 두 번째 HDMI = media 모니터

    # 이미 16:10 비율이면 스킵
    if target.height > 0:
        ratio = target.width / target.height
        if abs(ratio - 16 / 10) < 0.02:
            logger.info('%s 이미 16:10 비율(%dx%d), 변경 불필요', target.name, target.width, target.height)
            return

    try:
        r = subprocess.run(
            ['xrandr', '--query'], capture_output=True, text=True, timeout=5,
            env={**__import__('os').environ, 'DISPLAY': ':0'},
        )
        modes = _parse_xrandr_modes(r.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return

    available = modes.get(target.name, [])
    # 16:10 비율 필터 (허용 오차 2%)
    candidates = [
        (w, h) for w, h in available
        if h > 0 and abs(w / h - 16 / 10) < 0.02
    ]
    if not candidates:
        logger.warning('%s: 16:10 해상도 모드 없음. 사용 가능: %s', target.name, available[:5])
        return

    best_w, best_h = max(candidates, key=lambda wh: wh[0] * wh[1])
    set_monitor_resolution(target.name, best_w, best_h)


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
