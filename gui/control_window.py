from __future__ import annotations

import logging
import os
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

        self.bind_all('<Escape>', lambda e: self.master.destroy())
        self.bind_all('<Control-q>', lambda e: self.master.destroy())

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
        self.attributes('-topmost', True)
        self.attributes('-fullscreen', False)
        self._apply_geometry()
        self.update_idletasks()
        self.deiconify()
        self.lift()
        self.after(300, self._apply_geometry)

    def _apply_geometry(self):
        if self._monitor:
            w = min(1024, self._monitor.width)
            h = min(576, self._monitor.height)
            self.geometry(f'{w}x{h}+{self._monitor.x}+{self._monitor.y}')
        else:
            self.geometry('1024x576+0+0')

    # ── UI 빌드 ─────────────────────────────────────────────────

    def _build_ui(self):
        self._build_compact_ui()
        return

        # Legacy scrolling layout retained below for reference.
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

        # 터치 드래그 스크롤
        self._canvas.bind('<ButtonPress-1>',
                          lambda e: self._canvas.scan_mark(e.x, e.y))
        self._canvas.bind('<B1-Motion>',
                          lambda e: self._canvas.scan_dragto(e.x, e.y, gain=1))

        # 마우스 휠 스크롤 (Linux: Button-4=위, Button-5=아래 / Windows: MouseWheel)
        self._canvas.bind('<Button-4>',    lambda e: self._canvas.yview_scroll(-3, 'units'))
        self._canvas.bind('<Button-5>',    lambda e: self._canvas.yview_scroll( 3, 'units'))
        self._canvas.bind('<MouseWheel>',
                          lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), 'units'))

        self._build_now_playing(inner)
        self._build_playback_btns(inner)
        self._build_song_tuning(inner)
        self._build_search_btn(inner)
        self._build_queue_section(inner)
        self._build_mr_volume(inner)
        self._build_audio_sliders(inner)
        self._build_meters(inner)
        self._build_engine_ctrl(inner)
        self._build_input_device_selector(inner)
        self._build_output_device_selector(inner)
        self._build_app_exit(inner)

        # 모든 자식 위젯에 마우스 휠 스크롤 전파 (버튼·슬라이더 위에서도 스크롤)
        self.after(100, lambda: self._bind_scroll_recursive(inner))

    def _build_compact_ui(self):
        outer = tk.Frame(self, bg=self.BG); outer.pack(fill='both', expand=True, padx=4, pady=4)
        top = tk.Frame(outer, bg=self.BG); top.pack(fill='both', expand=True)
        left = tk.Frame(top, bg=self.BG, width=330); left.pack(side='left', fill='both', expand=False, padx=(0, 3)); left.pack_propagate(False)
        mid = tk.Frame(top, bg=self.BG, width=335); mid.pack(side='left', fill='both', expand=False, padx=3); mid.pack_propagate(False)
        right = tk.Frame(top, bg=self.BG, width=330); right.pack(side='left', fill='both', expand=True, padx=(3, 0)); right.pack_propagate(False)
        self._build_song_tuning(left); self._build_meters(left)
        self._title_var=tk.StringVar(value=''); self._artist_var=tk.StringVar(value='')
        self._current_title_full = ''
        self._current_marquee_offset = 0
        now = tk.LabelFrame(left, text='현재 재생 중', bg=self.BG, fg='#8aa8d8', font=self.LBL_FONT)
        now.pack(fill='x', pady=3)
        tk.Label(now, textvariable=self._title_var, bg=self.BG, fg='white',
                 font=('Helvetica', 12, 'bold'), anchor='w', width=36).pack(fill='x', padx=6)
        tk.Label(now, textvariable=self._artist_var, bg=self.BG, fg='#aab6cc',
                 font=('Helvetica', 10), anchor='w').pack(fill='x', padx=6, pady=(0, 3))
        self._pause_btn=tk.Button(mid, text='일시정지', command=self._on_pause_toggle)
        qlf = tk.LabelFrame(mid, text='대기열', bg=self.BG, fg='#8aa8d8', font=self.LBL_FONT); qlf.pack(fill='both', expand=True)
        qbody = tk.Frame(qlf, bg=self.BG); qbody.pack(fill='both', expand=True, padx=4, pady=4)
        qv = tk.Scrollbar(qbody, orient='vertical'); qv.pack(side='right', fill='y')
        qh = tk.Scrollbar(qbody, orient='horizontal'); qh.pack(side='bottom', fill='x')
        self._queue_lb = tk.Listbox(qbody, height=8, bg='#0a0a18', fg='#ccd', font=('Helvetica', 11), bd=0,
                                    xscrollcommand=qh.set, yscrollcommand=qv.set)
        self._queue_lb.pack(side='left', fill='both', expand=True)
        qv.config(command=self._queue_lb.yview); qh.config(command=self._queue_lb.xview)
        self._queue_marquee_offset = 0
        self.after(450, self._queue_marquee)
        lf = tk.LabelFrame(right, text='✥ 선택 / 이동', bg=self.BG, fg='#8aa8d8', font=self.LBL_FONT); lf.pack(fill='x', side='bottom')
        g=tk.Frame(lf,bg=self.BG); g.pack(expand=True)
        def nav(t,r,c,cmd=lambda:None): tk.Button(g,text=t,command=cmd,bg='#202c40',fg='white',relief='flat',font=('Helvetica',16,'bold'),width=4,height=2).grid(row=r,column=c,padx=2,pady=2)
        nav('▲',0,1,lambda: self._move_active(-1)); nav('◀',1,0,lambda: self._move_genre(-1)); nav('OK',1,1,self._confirm_active); nav('▶',1,2,lambda: self._move_genre(1)); nav('▼',2,1,lambda: self._move_active(1))
        lf2=tk.LabelFrame(right,text='# 곡 번호 입력',bg=self.BG,fg='#8aa8d8',font=self.LBL_FONT); lf2.pack(fill='both',expand=True,side='top')
        self._number_var=tk.StringVar(); tk.Entry(lf2,textvariable=self._number_var,font=('Helvetica',16),bg='#0b1725',fg='#66e6ff',insertbackground='white').pack(fill='x',padx=4,pady=3)
        ng=tk.Frame(lf2,bg=self.BG); ng.pack(fill='both', expand=True, padx=2)
        for col in range(3): ng.columnconfigure(col, weight=1)
        for row in range(4): ng.rowconfigure(row, weight=1)
        for i in range(1,10): tk.Button(ng,text=str(i),command=lambda n=i:self._number_var.set(self._number_var.get()+str(n)),bg='#202c40',fg='white',relief='flat',font=('Helvetica',14,'bold')).grid(row=(i-1)//3,column=(i-1)%3,padx=2,pady=2,sticky='nsew')
        tk.Button(ng,text='지움',command=lambda:self._number_var.set(''),bg='#536174',fg='white',relief='flat',width=3,height=1).grid(row=3,column=0,padx=2,pady=2)
        tk.Button(ng,text='0',command=lambda:self._number_var.set(self._number_var.get()+'0'),bg='#202c40',fg='white',relief='flat',width=3,height=1).grid(row=3,column=1,padx=2,pady=2)
        tk.Button(ng,text='검색',command=self._on_show_search,bg='#078acb',fg='white',relief='flat',width=3,height=1).grid(row=3,column=2,padx=2,pady=2)
        bottom=tk.Frame(outer,bg=self.BG); bottom.pack(fill='x',pady=(4,0))
        for text,color,cmd in [('★ 우선예약','#d88700',self._on_priority),('＋ 예약','#2865d7',self._on_reserve),('▣ 예약취소','#d52d2d',self._on_queue_remove),('■ 정지','#596575',self._on_stop),('▶ 시작','#12a34a',self._on_engine_start)]: tk.Button(bottom,text=text,bg=color,fg='white',relief='flat',font=('Helvetica',12,'bold'),height=2,command=cmd).pack(side='left',fill='x',expand=True,padx=2)
        self._engine_status=tk.StringVar(value='정지')
        self._style_touch_controls(outer)
        self.after(380, self._current_title_marquee)

    def _style_touch_controls(self, parent):
        """통일된 터치 피드백과 포커스 표시를 적용한다."""
        for child in parent.winfo_children():
            if isinstance(child, tk.Button):
                child.configure(cursor='hand2', takefocus=0,
                                activeforeground='white')
                bg = str(child.cget('bg'))
                if bg not in ('#078acb', '#12a34a', '#d52d2d'):
                    child.configure(activebackground='#3c5270')
            elif isinstance(child, tk.Listbox):
                child.configure(selectbackground='#087fb5',
                                selectforeground='white', activestyle='none')
            self._style_touch_controls(child)

    def _current_title_marquee(self):
        """긴 현재 곡명만 좌우로 이동시키고 영역 폭은 유지한다."""
        title = getattr(self, '_current_title_full', '')
        limit = 28
        if len(title) > limit:
            span = title + '     '
            n = self._current_marquee_offset % len(span)
            self._title_var.set(span[n:n + limit])
            self._current_marquee_offset += 1
        else:
            self._title_var.set(title)
        self.after(380, self._current_title_marquee)

    def _on_inner_configure(self, event):
        self._canvas.configure(scrollregion=self._canvas.bbox('all'))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._canvas_window, width=event.width)

    def _bind_scroll_recursive(self, widget):
        """자식 위젯에도 마우스 휠 이벤트를 캔버스 스크롤로 연결."""
        widget.bind('<Button-4>',   lambda e: self._canvas.yview_scroll(-3, 'units'))
        widget.bind('<Button-5>',   lambda e: self._canvas.yview_scroll( 3, 'units'))
        widget.bind('<MouseWheel>', lambda e: self._canvas.yview_scroll(-1 * (e.delta // 120), 'units'))
        for child in widget.winfo_children():
            self._bind_scroll_recursive(child)

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

    def _build_song_tuning(self, parent):
        """Large touch controls for song key, tempo and audience effect."""
        lf = tk.LabelFrame(parent, text='곡 조절 / 효과', bg=self.BG, fg='#8aa8d8',
                           font=self.LBL_FONT, pady=6, padx=6)
        lf.pack(fill='x', padx=8, pady=4)
        self._pitch = 0
        self._tempo = 100
        pitch_var = tk.StringVar(value='0')
        tempo_var = tk.StringVar(value='100%')

        def tune(kind, delta):
            if kind == 'pitch':
                self._pitch = max(-6, min(6, self._pitch + delta))
                pitch_var.set(f'{self._pitch:+d}')
                player = getattr(self.app_state, 'player', None)
                if player: player.set_pitch(self._pitch)
            else:
                self._tempo = max(50, min(150, self._tempo + delta))
                tempo_var.set(f'{self._tempo}%')
                player = getattr(self.app_state, 'player', None)
                if player: player.set_speed(self._tempo / 100.0)

        def row(label, var, kind, step):
            f = tk.Frame(lf, bg=self.BG)
            f.pack(fill='x', pady=3)
            tk.Label(f, text=label, bg=self.BG, fg='#ccd8ee',
                     font=('Helvetica', 13, 'bold'), width=8).pack(side='left')
            tk.Button(f, text='−', command=lambda: tune(kind, -step),
                      bg='#26364f', fg='white', font=('Helvetica', 18, 'bold'),
                      relief='flat', width=3, height=1).pack(side='left', padx=3)
            tk.Label(f, textvariable=var, bg='#0d1728', fg='#66d9ff',
                     font=('Helvetica', 18, 'bold'), width=7).pack(side='left', padx=3)
            tk.Button(f, text='+', command=lambda: tune(kind, step),
                      bg='#26364f', fg='white', font=('Helvetica', 18, 'bold'),
                      relief='flat', width=3, height=1).pack(side='left', padx=3)
        row('음정', pitch_var, 'pitch', 1)
        row('템포', tempo_var, 'tempo', 5)

        p = self.app_state.echo_params
        self._packed_stepper(lf, '출력 볼륨', p.volume, 0.0, 1.5, 0.1,
                             lambda v: setattr(p, 'volume', v), decimals=2)
        self._echo_level = 8
        def set_echo(level):
            self._echo_level = max(1, min(10, level))
            ratio = self._echo_level / 10.0
            p.wet = ratio * 0.60; p.feedback = ratio * 0.58
            p.reverb_wet = ratio * 0.25; p.reverb_room = 0.10 + ratio * 0.45
        self._packed_stepper(lf, '에코', 8, 1, 10, 1,
                             lambda v: set_echo(int(v)), decimals=0)
        player = getattr(self.app_state, 'player', None)
        self._packed_stepper(lf, '반주 볼륨', 80, 0, 130, 5,
                             lambda v: player.set_volume(int(v)) if player else None,
                             decimals=0)

        clap = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'clap.mp3')
        tk.Button(lf, text='👏  박수 / 환호', bg='#078acb', fg='white',
                  font=('Helvetica', 17, 'bold'), relief='flat', height=2,
                  command=lambda: self._play_effect(clap)).pack(fill='x', pady=(5, 2))

    def _packed_stepper(self, parent, label, initial, lo, hi, step, callback, decimals=0):
        f = tk.Frame(parent, bg=self.BG); f.pack(fill='x', pady=2)
        value = tk.DoubleVar(value=initial); text = tk.StringVar(value=f'{initial:.{decimals}f}')
        def change(delta):
            v = max(lo, min(hi, round(value.get() + delta, decimals + 1)))
            value.set(v); text.set(f'{v:.{decimals}f}'); callback(v)
        tk.Label(f, text=label, bg=self.BG, fg='#ccd8ee', font=('Helvetica', 12, 'bold'), width=8).pack(side='left')
        tk.Button(f, text='−', command=lambda: change(-step), bg='#26364f', fg='white', relief='flat', font=('Helvetica', 16, 'bold'), width=3).pack(side='left', padx=2)
        tk.Label(f, textvariable=text, bg='#0d1728', fg='#66d9ff', font=('Helvetica', 15, 'bold'), width=7).pack(side='left', padx=2)
        tk.Button(f, text='+', command=lambda: change(step), bg='#26364f', fg='white', relief='flat', font=('Helvetica', 16, 'bold'), width=3).pack(side='left', padx=2)

    def _play_effect(self, path):
        player = getattr(self.app_state, 'player', None)
        if player:
            player.play_effect(path)

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

    def _build_mr_volume(self, parent):
        lf = tk.LabelFrame(parent, text='MR 볼륨', bg=self.BG,
                            fg='#6666aa', font=self.LBL_FONT, pady=4, padx=6)
        lf.pack(fill='x', padx=8, pady=4)
        lf.columnconfigure(1, weight=1)

        self._mr_vol_var = tk.IntVar(value=100)
        val_lbl = tk.Label(lf, text='100', bg=self.BG, fg='white',
                           font=('Helvetica', 14, 'bold'), width=5)

        def _on_mr_vol(v):
            vol = int(float(v))
            val_lbl.config(text=str(vol))
            player = getattr(self.app_state, 'player', None)
            if player is not None:
                player.set_volume(vol)

        tk.Label(lf, text='MR 음량', bg=self.BG, fg='#ccccdd',
                 font=('Helvetica', 12), width=9, anchor='w',
                ).grid(row=0, column=0, sticky='w', padx=4, pady=5)
        tk.Scale(
            lf, from_=0, to=130, variable=self._mr_vol_var, orient='horizontal',
            command=_on_mr_vol, bg=self.BG, fg='white', troughcolor='#334433',
            sliderlength=50, width=26, highlightthickness=0,
            length=270,
        ).grid(row=0, column=1, padx=4, pady=4, sticky='ew')
        val_lbl.grid(row=0, column=2, padx=4)

        btn_row = tk.Frame(lf, bg=self.BG)
        btn_row.grid(row=1, column=0, columnspan=3, pady=(0, 4))

        def _set_vol(v):
            self._mr_vol_var.set(v)
            _on_mr_vol(v)

        for label, val, color in (('50%', 50, '#443322'), ('100%', 100, '#224433'), ('130%', 130, '#223344')):
            tk.Button(
                btn_row, text=label, bg=color, fg='white',
                font=('Helvetica', 12), relief='flat', padx=10, pady=4,
                command=lambda v=val: _set_vol(v),
            ).pack(side='left', padx=5)

    # 에코 레벨 1~10 프리셋 (wet, feedback, reverb_wet, reverb_room, delay_sec, reverb_damp)
    _ECHO_PRESETS = [
        (0.00, 0.00, 0.00, 0.10, 0.20, 0.55),  # 1  드라이
        (0.08, 0.08, 0.02, 0.12, 0.20, 0.55),  # 2
        (0.15, 0.15, 0.04, 0.15, 0.20, 0.55),  # 3
        (0.22, 0.22, 0.06, 0.18, 0.20, 0.55),  # 4
        (0.28, 0.30, 0.08, 0.22, 0.20, 0.55),  # 5
        (0.33, 0.38, 0.10, 0.25, 0.20, 0.55),  # 6
        (0.37, 0.42, 0.11, 0.27, 0.20, 0.55),  # 7
        (0.40, 0.45, 0.12, 0.30, 0.20, 0.55),  # 8  기본값
        (0.50, 0.52, 0.18, 0.40, 0.22, 0.50),  # 9
        (0.60, 0.58, 0.25, 0.55, 0.25, 0.45),  # 10 강한 에코
    ]

    def _build_audio_sliders(self, parent):
        lf = tk.LabelFrame(parent, text='마이크 볼륨', bg=self.BG,
                            fg='#6666aa', font=self.LBL_FONT, pady=4, padx=6)
        lf.pack(fill='x', padx=8, pady=4)
        lf.columnconfigure(1, weight=1)

        p = self.app_state.echo_params
        self._stepper_row(lf, '출력 볼륨', 0.0, 1.5, p.volume,
                          lambda v: setattr(p, 'volume', v), 0.1, 0)
        return

        lf2 = tk.LabelFrame(parent, text='에코 효과', bg=self.BG,
                             fg='#6666aa', font=self.LBL_FONT, pady=6, padx=6)
        lf2.pack(fill='x', padx=8, pady=4)

        self._echo_level = 8
        self._echo_btns: list[tk.Button] = []

        lv_lbl = tk.Label(lf2, text='레벨', bg=self.BG, fg='#9999bb',
                          font=('Helvetica', 11))
        lv_lbl.pack()

        self._echo_lv_var = tk.StringVar(value='8')
        tk.Label(lf2, textvariable=self._echo_lv_var,
                 bg=self.BG, fg='white', font=('Helvetica', 32, 'bold'),
                ).pack()

        row_f = tk.Frame(lf2, bg=self.BG)
        row_f.pack(pady=4)

        def _set_echo(lv: int):
            self._echo_level = lv
            self._echo_lv_var.set(str(lv))
            for i, b in enumerate(self._echo_btns):
                active = (i + 1 == lv)
                b.config(
                    bg='#3355aa' if active else '#222233',
                    relief='solid' if active else 'flat',
                )
            wet, fb, rv_wet, rv_room, delay, rv_damp = self._ECHO_PRESETS[lv - 1]
            p2 = self.app_state.echo_params
            p2.wet         = wet
            p2.feedback    = fb
            p2.reverb_wet  = rv_wet
            p2.reverb_room = rv_room
            p2.delay_sec   = delay
            p2.reverb_damp = rv_damp

        for i in range(10):
            lv = i + 1
            active = (lv == 8)
            b = tk.Button(
                row_f, text=str(lv),
                bg='#3355aa' if active else '#222233',
                fg='white', font=('Helvetica', 14, 'bold'),
                relief='solid' if active else 'flat',
                padx=6, pady=8, width=3,
                command=lambda l=lv: _set_echo(l),
            )
            b.pack(side='left', padx=2)
            self._echo_btns.append(b)

        _set_echo(8)

        # 터치용 에코 레벨 +/- 조절(기존 프리셋 버튼과 동일한 상태를 공유)
        echo_step = tk.Frame(lf2, bg=self.BG)
        echo_step.pack(pady=(2, 4))
        tk.Button(echo_step, text='−', bg='#26364f', fg='white', relief='flat',
                  font=('Helvetica', 16, 'bold'), width=3,
                  command=lambda: _set_echo(max(1, self._echo_level - 1))).pack(side='left', padx=3)
        tk.Label(echo_step, text='에코', bg=self.BG, fg='#ccd8ee',
                 font=('Helvetica', 12, 'bold'), width=6).pack(side='left')
        tk.Button(echo_step, text='+', bg='#26364f', fg='white', relief='flat',
                  font=('Helvetica', 16, 'bold'), width=3,
                  command=lambda: _set_echo(min(10, self._echo_level + 1))).pack(side='left', padx=3)

    def _stepper_row(self, parent, label, lo, hi, init, cmd, step, row):
        f = tk.Frame(parent, bg=self.BG)
        f.grid(row=row, column=0, columnspan=3, sticky='ew', padx=4, pady=4)
        var = tk.DoubleVar(value=init)
        value = tk.StringVar(value=f'{init:.2f}')
        def change(delta):
            v = max(lo, min(hi, round(var.get() + delta, 2)))
            var.set(v); value.set(f'{v:.2f}'); cmd(v)
        tk.Label(f, text=label, bg=self.BG, fg='#ccd8ee', font=('Helvetica', 12, 'bold'), width=9).pack(side='left')
        tk.Button(f, text='−', command=lambda: change(-step), bg='#26364f', fg='white', relief='flat', font=('Helvetica', 16, 'bold'), width=3).pack(side='left', padx=3)
        tk.Label(f, textvariable=value, bg='#0d1728', fg='#66d9ff', font=('Helvetica', 15, 'bold'), width=7).pack(side='left', padx=3)
        tk.Button(f, text='+', command=lambda: change(step), bg='#26364f', fg='white', relief='flat', font=('Helvetica', 16, 'bold'), width=3).pack(side='left', padx=3)

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
        lf.columnconfigure(1, weight=1)

        for row, label in enumerate(('IN', 'OUT')):
            tk.Label(lf, text=label, bg=self.BG, fg='#aaa',
                     font=('Helvetica', 12), width=4, anchor='e',
                    ).grid(row=row, column=0, padx=6)
            meter = LevelMeter(lf, width=230, height=22)
            meter.grid(row=row, column=1, padx=4, pady=6, sticky='ew')
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

    def _build_app_exit(self, parent):
        f = tk.Frame(parent, bg=self.BG, pady=8)
        f.pack(fill='x', padx=8)
        tk.Button(
            f, text='앱 종료',
            font=('Helvetica', 15, 'bold'),
            bg='#331111', fg='#ff6666',
            relief='flat', pady=10, cursor='hand2',
            command=self._on_close,
        ).pack(fill='x')

    # ── 이벤트 핸들러 ────────────────────────────────────────────

    def _on_show_search(self):
        if self._media_win:
            self._media_win.toggle_overlay()

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

    def _move_queue(self, delta):
        size = self._queue_lb.size()
        if not size:
            return
        current = self._queue_lb.curselection()
        index = (current[0] if current else 0) + delta
        index = max(0, min(size - 1, index))
        self._queue_lb.selection_clear(0, 'end')
        self._queue_lb.selection_set(index)
        self._queue_lb.activate(index)
        self._queue_lb.see(index)

    def _queue_marquee(self):
        if hasattr(self, '_queue_lb'):
            items = self.app_state.queue_snapshot()
            self._queue_marquee_offset = (self._queue_marquee_offset + 1) % 100000
            selected = self._queue_lb.curselection()
            self._queue_lb.delete(0, 'end')
            for song in items:
                text = f'  {song.title}  —  {song.artist}'
                if len(text) > 34:
                    span = text + '     '
                    n = self._queue_marquee_offset % len(span)
                    text = span[n:] + span[:n]
                self._queue_lb.insert('end', text)
            if selected and selected[0] < len(items):
                self._queue_lb.selection_set(selected[0]); self._queue_lb.activate(selected[0])
        self.after(450, self._queue_marquee)

    def _confirm_queue(self):
        idx = self._queue_lb.curselection()
        queue = self.app_state.queue_snapshot()
        if idx and idx[0] < len(queue) and self._playback:
            self._playback.play_or_enqueue(queue[idx[0]])
        else:
            self._on_show_search()

    def _selected_song(self):
        return self._media_win.selected_song() if self._media_win else None

    def _move_chart(self, delta):
        if self._media_win:
            self._media_win.move_chart_selection(delta)

    def _confirm_chart(self):
        if self._media_win:
            self._media_win.confirm_chart_selection()

    def _move_active(self, delta):
        if self._media_win:
            self._media_win.move_active_selection(delta)

    def _confirm_active(self):
        if self._media_win:
            self._media_win.confirm_active_selection()

    def _move_genre(self, delta):
        if self._media_win:
            self._media_win.move_genre(delta)

    def _on_reserve(self):
        if self._media_win and self._media_win.reserve_active(priority=False):
            return
        if self._media_win:
            self._media_win.toggle_overlay()

    def _on_priority(self):
        if self._media_win and self._media_win.reserve_active(priority=True):
            return
        if self._media_win:
            self._media_win.toggle_overlay()

    def _on_engine_start(self):
        # With the media panel open, Start applies to the hovered song.
        if self._media_win and self._media_win.is_visible and self._media_win.start_active():
            return
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
            logging.error('마이크 엔진 시작 실패: %s', msg, exc_info=True)
            short = msg.splitlines()[0] if msg else '알 수 없는 오류'
            self.after(0, lambda: self._engine_status.set(f'오류: {short[:42]}'))

    def _on_engine_stop(self):
        self.engine.stop()
        self._engine_status.set('정지')

    def _build_input_device_selector(self, parent):
        sources = AudioEngine.list_audio_sources()
        if not sources:
            return

        lf = tk.LabelFrame(parent, text='마이크 입력 장치', bg=self.BG, fg='#6666aa',
                            font=self.LBL_FONT, pady=6, padx=6)
        lf.pack(fill='x', padx=8, pady=4)

        self._source_names = [s[0] for s in sources]
        self._source_descs = [s[1] for s in sources]

        default_source = AudioEngine.get_default_audio_source()
        self._source_var = tk.StringVar()
        if default_source in self._source_names:
            self._source_var.set(self._source_descs[self._source_names.index(default_source)])
        elif self._source_descs:
            self._source_var.set(self._source_descs[0])

        om = tk.OptionMenu(lf, self._source_var, *self._source_descs,
                           command=self._on_source_change)
        om.config(bg='#222233', fg='white', font=('Helvetica', 13),
                  relief='flat', highlightbackground=self.BG,
                  activebackground='#334466', activeforeground='white', anchor='w')
        om['menu'].config(bg='#222233', fg='white', font=('Helvetica', 12))
        om.pack(fill='x', padx=4, pady=4)

    def _on_source_change(self, desc: str):
        if not hasattr(self, '_source_descs') or desc not in self._source_descs:
            return
        source_name = self._source_names[self._source_descs.index(desc)]
        AudioEngine.set_default_audio_source(source_name)

        if self.engine.is_running:
            self._engine_status.set('전환 중...')
            self.update_idletasks()
            self.engine.stop()
            self.after(300, self._restart_engine_after_sink)

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

        self._current_title_full = song.title if song else '—'
        self._current_marquee_offset = 0
        self._title_var.set(self._current_title_full)
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
