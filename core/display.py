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


def _reposition_monitors(media_name: str, media_width: int, ctrl_name: str) -> None:
    """왼쪽 미디어 / 오른쪽 제어 모니터 배치를 xrandr로 재확정."""
    try:
        r = subprocess.run(
            [
                'xrandr',
                '--output', media_name, '--pos', '0x0',
                '--output', ctrl_name, '--pos', f'{media_width}x0',
            ],
            capture_output=True, text=True, timeout=8,
            env={**__import__('os').environ, 'DISPLAY': ':0'},
        )
        if r.returncode == 0:
            logger.info('xrandr 재배치: %s(0x0) / %s(%dx0)', media_name, ctrl_name, media_width)
        else:
            logger.warning('xrandr 재배치 실패: %s', r.stderr.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning('xrandr 재배치 오류: %s', e)


def configure_16_10_monitor(monitors: list[MonitorInfo]) -> None:
    """왼쪽 모니터를 미디어로 두고, 16:10 비율을 적용한 뒤 위치를 유지한다."""
    if not monitors:
        return

    by_x = sorted(monitors, key=lambda m: m.x)
    if len(by_x) < 2:
        return

    media_mon = by_x[0]
    ctrl_mon = by_x[-1]

    if media_mon.height > 0:
        ratio = media_mon.width / media_mon.height
        if abs(ratio - 16 / 10) < 0.02:
            logger.info('%s 이미 16:10 비율(%dx%d), 위치만 재확정', media_mon.name, media_mon.width, media_mon.height)
            _reposition_monitors(media_mon.name, media_mon.width, ctrl_mon.name)
            return

    try:
        r = subprocess.run(
            ['xrandr', '--query'], capture_output=True, text=True, timeout=5,
            env={**__import__('os').environ, 'DISPLAY': ':0'},
        )
        modes = _parse_xrandr_modes(r.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return

    available = modes.get(media_mon.name, [])
    candidates = [
        (w, h) for w, h in available
        if h > 0 and abs(w / h - 16 / 10) < 0.02
    ]
    if not candidates:
        logger.warning('%s: 16:10 해상도 모드 없음. 사용 가능: %s', media_mon.name, available[:5])
        return

    best_w, best_h = max(candidates, key=lambda wh: wh[0] * wh[1])
    if set_monitor_resolution(media_mon.name, best_w, best_h):
        _reposition_monitors(media_mon.name, best_w, ctrl_mon.name)


def assign_displays(
    monitors: list[MonitorInfo],
) -> tuple[Optional[MonitorInfo], Optional[MonitorInfo]]:
    """
    (media_mon, ctrl_mon) 반환.
    X 좌표 기준: 왼쪽 = 미디어, 오른쪽 = 제어(터치).
    모니터 1개 → (monitors[0], None).
    모니터 0개 → (None, None).
    """
    if not monitors:
        return None, None
    if len(monitors) == 1:
        return monitors[0], None

    by_x = sorted(monitors, key=lambda m: m.x)
    media_mon = by_x[0]
    ctrl_mon = by_x[-1]
    return media_mon, ctrl_mon
