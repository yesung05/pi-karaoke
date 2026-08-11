import math
import tkinter as tk

DB_MIN = -60.0


def rms_to_db(rms: float) -> float:
    return 20.0 * math.log10(max(rms, 1e-9))


def db_to_ratio(db: float) -> float:
    return max(0.0, min(1.0, (db - DB_MIN) / (-DB_MIN)))


class LevelMeter(tk.Canvas):
    def __init__(self, parent, width: int = 260, height: int = 18, **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg='#1e1e1e', highlightthickness=0, **kwargs)
        self._meter_w = width
        self._meter_h = height
        self._bar     = self.create_rectangle(0, 0, 0, height, fill='#00c853', width=0)
        self._peak    = 0.0

    def update_level(self, rms: float) -> None:
        ratio = db_to_ratio(rms_to_db(rms))
        w     = int(ratio * self._meter_w)
        self._peak = ratio if ratio > self._peak else max(0.0, self._peak - 0.03)
        color = '#ff1744' if ratio > 0.9 else '#ffab00' if ratio > 0.7 else '#00c853'
        self.itemconfig(self._bar, fill=color)
        self.coords(self._bar, 0, 0, w, self._meter_h)
