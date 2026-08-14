from core.display import MonitorInfo, assign_displays


def test_assign_displays_uses_x_position_for_left_right_layout():
    monitors = [
        MonitorInfo(name='HDMI-0', x=2560, y=0, width=1920, height=1080, rotated=False),
        MonitorInfo(name='HDMI-1', x=0, y=0, width=2560, height=1600, rotated=False),
    ]

    media, ctrl = assign_displays(monitors)

    assert media is not None and media.name == 'HDMI-1'
    assert ctrl is not None and ctrl.name == 'HDMI-0'
    assert media.x < ctrl.x


def test_assign_displays_keeps_single_monitor_as_media_only():
    monitors = [
        MonitorInfo(name='HDMI-0', x=0, y=0, width=1920, height=1080, rotated=False),
    ]

    media, ctrl = assign_displays(monitors)

    assert media is not None and media.name == 'HDMI-0'
    assert ctrl is None
