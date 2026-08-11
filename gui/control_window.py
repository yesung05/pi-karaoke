from __future__ import annotations

import queue as pyqueue
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional, TYPE_CHECKING

from audio.engine import AudioEngine
from core.app_state import AppState
from core.display import MonitorInfo
from gui.widgets import LevelMeter

if TYPE_CHECKING:
    from gui.media_window import MediaWindow

POLL_MS = 50


class ControlWindow(tk.Toplevel):
    """HDMI1 터치스크린 제어창 (기본 720×1280, 세로 회전 기준)."""

    BG       = '#111118'
    BTN_FONT = ('Helvetica', 20, 'bold')
    LBL_FONT = ('Helvetica', 12)

    def __init__(self, root: tk.Tk, app_state: AppState,
                 engine: AudioEngine,
                 monitor: Optional[MonitorInfo] = None,
                 playback_mgr=None):
        super().__init__(root)
        self.app_state   = app_state
        self.engine      = engine
        self._monitor    = monitor
        self._playback   = playback_mgr
        self._media_win: Optional['MediaWindow'] = None

        self._configure_geometry()
        self._build_ui()

        app_state.add_listener(lambda: self.after(0, self._refresh_state))
        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self.after(POLL_MS, self._poll_audio)

    def set_media_window(self, media_win: 'MediaWindow'):
        self._media_win = media_win

    # ── 창 설정 ─────────────────────────────────────────────────

    def _configure_geometry(self):
        self.title('Pi Karaoke - 제어')
        self.configure(bg=self.BG)
        self.overrideredirect(True)
        self._apply_geometry()
        self.after(300, self._apply_geometry)

    def _apply_geometry(self):
        if self._monitor:
            w = self._monitor.width
            h = self._monitor.height
            self.geometry(f'{w}x{h}+{self._monitor.x}+{self._monitor.y}')
        else:
            self.geometry('480x800+0+0')

    # ── UI 빌드 ─────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=self.BG)
        outer.pack(fill='both', expand=True)

        vbar = tk.Scrollbar(outer, orient='vertical', bg='#333', troughcolor='#222')
        vbar.pack(side='right', fill='y')

        self._canvas = tk.Canvas(outer, bg=self.BG, highlightthickness=0,
                                 yscrollcommand=vbar.set)
        self._canvas.pack(fill='both', expand=True)
        vbar.config(command=self._canvas.yview)

        inner = tk.Frame(self._canvas, bg=self.BG)
        self._canvas_window = self._canvas.create_window(
            (0, 0), window=inner, anchor='nw',
        )
        inner.bind('<Configure>', self._on_inner_configure)
        self._canvas.bind('<Configure>', self._on_canvas_configure)

        # 터치 스크롤
        self._canvas.bind('<ButtonPress-1>',
                          lambda e: self._canvas.scan_mark(e.x, e.y))
        self._canvas.bind('<B1-Motion>',
                          lambda e: self._canvas.scan_dragto(e.x, e.y, gain=1))

        self._build_now_playing(inner)
        self._build_playback_btns(inner)
        self._build_search_btn(inner)
        self._build_queue_section(inner)
        self._build_audio_sliders(inner)
        self._build_meters(inner)
        self._build_engine_ctrl(inner)
        self._build_output_device_selector(inner)

    def _on_inner_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox('all'))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    # ── 섹션 빌드 ────────────────────────────────────────────────

    def _build_now_playing(self, parent):
        f = tk.Frame(parent, bg='#1a1a2a', pady=10)
        f.pack(fill='x')
        tk.Label(f, text='지금 재생 중', bg='#1a1a2a', fg='#6666aa',
                 font=('Helvetica', 11)).pack()
        self._title_var  = tk.StringVar(value='—')
        self._artist_var = tk.StringVar(value='')
        tk.Label(f, textvariable=self._title_var,
                 bg='#1a1a2a', fg='white', font=('Helvetica', 14, 'bold'),
                 wraplength=680).pack(padx=10)
        tk.Label(f, textvariable=self._artist_var,
                 bg='#1a1a2a', fg='#9999bb', font=('Helvetica', 12)).pack()

    def _build_playback_btns(self, parent):
        f = tk.Frame(parent, bg=self.BG, pady=6)
        f.pack(fill='x')

        btn_cfg = dict(relief='flat', cursor='hand2', font=self.BTN_FONT,
                       bd=0, pady=10)

        self._pause_btn = tk.Button(
            f, text='⏸  일시정지', bg='#224488', fg='white',
            command=self._on_pause_toggle, **btn_cfg,
        )
        self._pause_btn.pack(fill='x', padx=10, pady=3)

        tk.Button(
            f, text='⏭  다음 곡', bg='#333344', fg='white',
            command=self._on_skip, **btn_cfg,
        ).pack(fill='x', padx=10, pady=3)

        tk.Button(
            f, text='⏹  정지', bg='#441122', fg='white',
            command=self._on_stop, **btn_cfg,
        ).pack(fill='x', padx=10, pady=3)

    def _build_search_btn(self, parent):
        """재생 중 차트/검색 오버레이 열기 버튼."""
        f = tk.Frame(parent, bg=self.BG, pady=2)
        f.pack(fill='x', padx=10)
        tk.Button(
            f, text='🔍  곡 검색 / 차트',
            font=('Helvetica', 16, 'bold'),
            bg='#1a2a44', fg='#88aaff',
            relief='flat', pady=12, cursor='hand2',
            command=self._on_show_search,
        ).pack(fill='x')

    def _build_queue_section(self, parent):
        lf = tk.LabelFrame(parent, text='대기열', bg=self.BG, fg='#6666aa',
                            font=self.LBL_FONT, pady=4, padx=6)
        lf.pack(fill='x', padx=8, pady=4)

        self._queue_lb = tk.Listbox(
            lf, bg='#0a0a18', fg='#ccd', font=('Helvetica', 13),
            selectbackground='#442244', height=4,
            bd=0, highlightthickness=0, activestyle='none',
        )
        self._queue_lb.pack(fill='x', padx=4, pady=4)

        tk.Button(
            lf, text='선택 항목 제거', bg='#332222', fg='#cc8888',
            font=('Helvetica', 13), relief='flat', pady=6,
            command=self._on_queue_remove,
        ).pack(pady=4)

    def _build_audio_sliders(self, parent):
        lf = tk.LabelFrame(parent, text='볼륨 / 에코 / 리버브', bg=self.BG,
                            fg='#6666aa', font=self.LBL_FONT, pady=4, padx=6)
        lf.pack(fill='x', padx=8, pady=4)
        lf.columnconfigure(1, weight=1)

        p = self.app_state.echo_params
        rows = [
            ('출력 볼륨',   0.0,  1.5,  p.volume,      lambda v: setattr(p, 'volume',      v)),
            ('에코 믹스',   0.0,  1.0,  p.wet,         lambda v: setattr(p, 'wet',         v)),
            ('에코 딜레이', 0.05, 1.5,  p.delay_sec,   lambda v: setattr(p, 'delay_sec',   v)),
            ('에코 피드백', 0.0,  0.85, p.feedback,    lambda v: setattr(p, 'feedback',    v)),
            ('잔향 크기',   0.0,  0.9,  p.reverb_room, lambda v: setattr(p, 'reverb_room', v)),
            ('고음 흡수',   0.0,  1.0,  p.reverb_damp, lambda v: setattr(p, 'reverb_damp', v)),
            ('잔향 믹스',   0.0,  1.0,  p.reverb_wet,  lambda v: setattr(p, 'reverb_wet',  v)),
        ]
        for row, (label, lo, hi, init, fn) in enumerate(rows):
            self._slider_row(lf, label, lo, hi, init, fn, row)

    def _slider_row(self, parent, label, lo, hi, init, cmd, row):
        tk.Label(parent, text=label, bg=self.BG, fg='#ccccdd',
                 font=('Helvetica', 12), width=9, anchor='w',
                ).grid(row=row, column=0, sticky='w', padx=4, pady=5)
        var     = tk.DoubleVar(value=init)
        val_lbl = tk.Label(parent, text=f'{init:.2f}', bg=self.BG, fg='white',
                           font=('Helvetica', 12), width=5)

        def _chg(v, lbl=val_lbl, fn=cmd):
            fv = float(v)
            lbl.config(text=f'{fv:.2f}')
            fn(fv)

        tk.Scale(
            parent, from_=lo, to=hi, variable=var, orient='horizontal',
            command=_chg, bg=self.BG, fg='white', troughcolor='#333344',
            sliderlength=50, width=26, highlightthickness=0,
            length=270,
        ).grid(row=row, column=1, padx=4, pady=4, sticky='ew')
        val_lbl.grid(row=row, column=2, padx=4)

    def _build_meters(self, parent):
        lf = tk.LabelFrame(parent, text='레벨 미터', bg=self.BG, fg='#6666aa',
                            font=self.LBL_FONT, pady=4, padx=6)
        lf.pack(fill='x', padx=8, pady=4)

        for row, label in enumerate(('IN', 'OUT')):
            tk.Label(lf, text=label, bg=self.BG, fg='#aaa',
                     font=('Helvetica', 12), width=4, anchor='e',
                    ).grid(row=row, column=0, padx=6)
            meter = LevelMeter(lf, width=360, height=22)
            meter.grid(row=row, column=1, padx=4, pady=6)
            if row == 0:
                self._in_meter = meter
            else:
                self._out_meter = meter

    def _build_engine_ctrl(self, parent):
        lf = tk.LabelFrame(parent, text='마이크 에코', bg=self.BG, fg='#6666aa',
                            font=self.LBL_FONT, pady=6, padx=6)
        lf.pack(fill='x', padx=8, pady=4)

        self._engine_status = tk.StringVar(value='정지')
        f = tk.Frame(lf, bg=self.BG)
        f.pack()
        tk.Button(f, text='마이크 ON', bg='#114422', fg='white',
                  font=('Helvetica', 14), relief='flat', padx=12, pady=8,
                  command=self._on_engine_start,
                 ).pack(side='left', padx=6, pady=4)
        tk.Button(f, text='마이크 OFF', bg='#441111', fg='white',
                  font=('Helvetica', 14), relief='flat', padx=12, pady=8,
                  command=self._on_engine_stop,
                 ).pack(side='left', padx=6, pady=4)
        tk.Label(lf, textvariable=self._engine_status,
                 bg=self.BG, fg='#aaaacc', font=('Helvetica', 11),
                ).pack(pady=2)

    # ── 이벤트 핸들러 ────────────────────────────────────────────

    def _on_show_search(self):
        if self._media_win:
            self._media_win.show_overlay()

    def _on_pause_toggle(self):
        if not self._playback:
            return
        self._playback.toggle_pause()

    def _on_skip(self):
        if self._playback:
            self._playback.skip()

    def _on_stop(self):
        if self._playback:
            self._playback.stop()

    def _on_queue_remove(self):
        idx = self._queue_lb.curselection()
        if idx:
            self.app_state.remove_from_queue(idx[0])

    def _on_engine_start(self):
        if self.engine.is_running:
            return
        self._engine_status.set('연결 중...')
        self.update_idletasks()
        threading.Thread(target=self._engine_start_bg, daemon=True).start()

    def _engine_start_bg(self):
        try:
            self.engine.start()
            self.after(0, lambda: self._engine_status.set('실행 중'))
        except Exception as e:
            msg = str(e)
            self.after(0, lambda: self._engine_status.set('오류'))
            self.after(0, lambda: messagebox.showerror('오디오 오류', msg, parent=self))

    def _on_engine_stop(self):
        self.engine.stop()
        self._engine_status.set('정지')

    def _build_output_device_selector(self, parent):
        sinks = AudioEngine.list_audio_sinks()
        if not sinks:
            return  # Pi가 아니거나 PipeWire 없음

        lf = tk.LabelFrame(parent, text='오디오 출력 장치', bg=self.BG, fg='#6666aa',
                            font=self.LBL_FONT, pady=6, padx=6)
        lf.pack(fill='x', padx=8, pady=4)

        self._sink_names = [s[0] for s in sinks]
        self._sink_descs = [s[1] for s in sinks]

        default_sink = AudioEngine.get_default_audio_sink()
        self._sink_var = tk.StringVar()
        if default_sink in self._sink_names:
            self._sink_var.set(self._sink_descs[self._sink_names.index(default_sink)])
        elif self._sink_descs:
            self._sink_var.set(self._sink_descs[0])

        om = tk.OptionMenu(lf, self._sink_var, *self._sink_descs,
                           command=self._on_sink_change)
        om.config(bg='#222233', fg='white', font=('Helvetica', 13),
                  relief='flat', highlightbackground=self.BG,
                  activebackground='#334466', activeforeground='white', anchor='w')
        om['menu'].config(bg='#222233', fg='white', font=('Helvetica', 12))
        om.pack(fill='x', padx=4, pady=4)

    def _on_sink_change(self, desc: str):
        if not hasattr(self, '_sink_descs') or desc not in self._sink_descs:
            return
        sink_name = self._sink_names[self._sink_descs.index(desc)]
        AudioEngine.set_default_audio_sink(sink_name)

        player = getattr(self.app_state, 'player', None)
        if player is not None:
            player.audio_device = f'pulse/{sink_name}'

        if self.engine.is_running:
            self._engine_status.set('전환 중...')
            self.update_idletasks()
            self.engine.stop()
            self.after(300, self._restart_engine_after_sink)

    def _restart_engine_after_sink(self):
        try:
            self.engine.start()
            self._engine_status.set('실행 중')
        except Exception as e:
            self._engine_status.set('오류')
            messagebox.showerror('오디오 오류', str(e), parent=self)

    def _on_close(self):
        self.engine.stop()
        if self._playback:
            self._playback.stop()
        self.master.destroy()

    # ── 상태 갱신 ────────────────────────────────────────────────

    def _refresh_state(self):
        song   = self.app_state.current_song
        status = self.app_state.status

        self._title_var.set(song.title if song else '—')
        self._artist_var.set(song.artist if song else '')

        if status == 'playing':
            self._pause_btn.config(text='⏸  일시정지', bg='#224488')
        elif status == 'paused':
            self._pause_btn.config(text='▶  재생',    bg='#226622')
        else:
            self._pause_btn.config(text='▶  재생',    bg='#333344')

        queue_snap = self.app_state.queue_snapshot()
        self._queue_lb.delete(0, 'end')
        for s in queue_snap:
            self._queue_lb.insert('end', f'  {s.title}  —  {s.artist}')

    # ── 오디오 레벨 폴링 ─────────────────────────────────────────

    def _poll_audio(self):
        try:
            while True:
                in_rms, out_rms = self.engine.level_queue.get_nowait()
                self._in_meter.update_level(in_rms)
                self._out_meter.update_level(out_rms)
        except pyqueue.Empty:
            pass
        self.after(POLL_MS, self._poll_audio)
