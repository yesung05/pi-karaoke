import queue
import tkinter as tk
from tkinter import ttk, messagebox

from audio.dsp import EchoProcessor, ReverbProcessor
from audio.engine import AudioEngine
from config import EchoParams, SAMPLE_RATE_DEFAULT, BLOCK_SIZE_DEFAULT
from gui.widgets import LevelMeter


POLL_MS  = 50     # 레벨 미터 갱신 주기 (ms)
METER_W  = 260
METER_H  = 18

_LevelMeter = LevelMeter  # 하위 호환 alias


class KaraokeApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Pi Karaoke')
        self.resizable(False, False)
        self.configure(bg='#2b2b2b')

        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TFrame',        background='#2b2b2b')
        style.configure('TLabelframe',   background='#2b2b2b', foreground='#e0e0e0')
        style.configure('TLabelframe.Label', background='#2b2b2b', foreground='#e0e0e0',
                        font=('Helvetica', 9, 'bold'))
        style.configure('TLabel',        background='#2b2b2b', foreground='#e0e0e0')
        style.configure('TScale',        background='#2b2b2b', troughcolor='#555555')
        style.configure('TCombobox',     fieldbackground='#3c3c3c', foreground='#e0e0e0',
                        background='#3c3c3c')
        style.configure('Start.TButton', background='#00897b', foreground='white',
                        font=('Helvetica', 10, 'bold'))
        style.configure('Stop.TButton',  background='#c62828', foreground='white',
                        font=('Helvetica', 10, 'bold'))
        style.configure('TButton',       background='#3c3c3c', foreground='#e0e0e0')
        style.map('Start.TButton', background=[('active', '#00695c')])
        style.map('Stop.TButton',  background=[('active', '#b71c1c')])

        self.params       = EchoParams()
        self.echo_proc    = EchoProcessor(self.params)
        self.reverb_proc  = ReverbProcessor(self.params)
        self.engine       = AudioEngine(self.echo_proc, self.reverb_proc, self.params)

        self._all_devices    = AudioEngine.list_devices()
        self._in_dev_map:  dict[str, int | None] = {}
        self._out_dev_map: dict[str, int | None] = {}
        self._build_device_maps()

        main = ttk.Frame(self, padding=10)
        main.pack()

        self._build_device_frame(main)
        self._build_echo_frame(main)
        self._build_reverb_frame(main)
        self._build_volume_frame(main)
        self._build_meter_frame(main)
        self._build_control_frame(main)

        self.protocol('WM_DELETE_WINDOW', self._on_close)
        self._poll_level()

    # ── 장치 목록 구성 ────────────────────────────────────────────

    def _build_device_maps(self):
        self._in_dev_map  = {'(시스템 기본)': None}
        self._out_dev_map = {'(시스템 기본)': None}

        for idx, name, max_in, max_out, api, in_lat_ms, out_lat_ms in self._all_devices:
            api_short = ('WASAPI' if 'WASAPI' in api else
                         'ASIO'   if 'ASIO'   in api else
                         'DS'     if 'Sound'  in api else
                         'ALSA'   if 'ALSA'   in api else
                         'MME')
            if max_in > 0:
                lat_str = f'{in_lat_ms:.0f}ms' if in_lat_ms > 0 else '<1ms'
                label = f'[{idx}] {api_short} | {name} ({lat_str})'
                self._in_dev_map[label] = idx
            if max_out > 0:
                lat_str = f'{out_lat_ms:.0f}ms' if out_lat_ms > 0 else '<1ms'
                label = f'[{idx}] {api_short} | {name} ({lat_str})'
                self._out_dev_map[label] = idx

        # Scarlett WASAPI 장치를 기본 선택 (가장 낮은 지연)
        best_in_idx, best_out_idx = AudioEngine.best_scarlett_devices()
        self._default_in_label  = '(시스템 기본)'
        self._default_out_label = '(시스템 기본)'
        for label, idx in self._in_dev_map.items():
            if idx == best_in_idx:
                self._default_in_label = label
                break
        for label, idx in self._out_dev_map.items():
            if idx == best_out_idx:
                self._default_out_label = label
                break

    # ── GUI 빌드 헬퍼 ─────────────────────────────────────────────

    def _slider_row(self, parent, label: str, from_: float, to: float,
                    init: float, fmt: str, cmd, row: int):
        ttk.Label(parent, text=label, width=12, anchor='w').grid(
            row=row, column=0, sticky='w', padx=(4, 2))

        var = tk.DoubleVar(value=init)
        val_label = ttk.Label(parent, text=fmt.format(init), width=6, anchor='e')

        def _on_change(v):
            fv = float(v)
            val_label.config(text=fmt.format(fv))
            cmd(fv)

        scale = ttk.Scale(parent, from_=from_, to=to, variable=var,
                          orient='horizontal', length=200, command=_on_change)
        scale.grid(row=row, column=1, padx=4, pady=3)
        val_label.grid(row=row, column=2, padx=(2, 4))
        return var

    def _build_device_frame(self, parent):
        lf = ttk.LabelFrame(parent, text='오디오 장치', padding=8)
        lf.pack(fill='x', pady=(0, 6))

        in_names  = list(self._in_dev_map.keys())
        out_names = list(self._out_dev_map.keys())

        self._in_var  = tk.StringVar(value=self._default_in_label)
        self._out_var = tk.StringVar(value=self._default_out_label)
        self._sr_var  = tk.StringVar(value=str(SAMPLE_RATE_DEFAULT))
        self._bs_var  = tk.StringVar(value='0 (자동)' if BLOCK_SIZE_DEFAULT == 0 else str(BLOCK_SIZE_DEFAULT))

        r = 0
        ttk.Label(lf, text='입력 장치').grid(row=r, column=0, sticky='w', padx=4)
        ttk.Combobox(lf, textvariable=self._in_var, values=in_names,
                     state='readonly', width=35).grid(row=r, column=1, columnspan=3,
                                                      sticky='ew', padx=4, pady=2)
        r += 1
        ttk.Label(lf, text='출력 장치').grid(row=r, column=0, sticky='w', padx=4)
        ttk.Combobox(lf, textvariable=self._out_var, values=out_names,
                     state='readonly', width=35).grid(row=r, column=1, columnspan=3,
                                                      sticky='ew', padx=4, pady=2)
        r += 1
        ttk.Label(lf, text='샘플레이트').grid(row=r, column=0, sticky='w', padx=4)
        ttk.Combobox(lf, textvariable=self._sr_var,
                     values=['44100', '48000'], state='readonly', width=8).grid(
            row=r, column=1, sticky='w', padx=4, pady=2)
        ttk.Label(lf, text='블록 크기').grid(row=r, column=2, sticky='w', padx=4)
        ttk.Combobox(lf, textvariable=self._bs_var,
                     values=['0 (자동)', '48', '64', '128', '256', '512'],
                     state='readonly', width=9).grid(
            row=r, column=3, sticky='w', padx=4, pady=2)

    def _build_echo_frame(self, parent):
        lf = ttk.LabelFrame(parent, text='에코 제어', padding=8)
        lf.pack(fill='x', pady=(0, 6))

        self._delay_var = self._slider_row(
            lf, '딜레이 (s)', 0.05, 1.50, self.params.delay_sec, '{:.2f}',
            lambda v: setattr(self.params, 'delay_sec', v), 0)
        self._feedback_var = self._slider_row(
            lf, '피드백 강도', 0.00, 0.85, self.params.feedback, '{:.2f}',
            lambda v: setattr(self.params, 'feedback', v), 1)
        self._wet_var = self._slider_row(
            lf, '에코 믹스', 0.00, 1.00, self.params.wet, '{:.2f}',
            lambda v: setattr(self.params, 'wet', v), 2)

    def _build_reverb_frame(self, parent):
        lf = ttk.LabelFrame(parent, text='리버브 제어', padding=8)
        lf.pack(fill='x', pady=(0, 6))

        self._reverb_room_var = self._slider_row(
            lf, '잔향 시간', 0.00, 0.90, self.params.reverb_room, '{:.2f}',
            lambda v: setattr(self.params, 'reverb_room', v), 0)
        self._reverb_damp_var = self._slider_row(
            lf, '고음 흡수', 0.00, 1.00, self.params.reverb_damp, '{:.2f}',
            lambda v: setattr(self.params, 'reverb_damp', v), 1)
        self._reverb_wet_var = self._slider_row(
            lf, '잔향 믹스', 0.00, 1.00, self.params.reverb_wet, '{:.2f}',
            lambda v: setattr(self.params, 'reverb_wet', v), 2)

    def _build_volume_frame(self, parent):
        lf = ttk.LabelFrame(parent, text='볼륨', padding=8)
        lf.pack(fill='x', pady=(0, 6))

        self._vol_var = self._slider_row(
            lf, '출력 볼륨', 0.00, 1.50, self.params.volume, '{:.2f}',
            lambda v: setattr(self.params, 'volume', v), 0)

    def _build_meter_frame(self, parent):
        lf = ttk.LabelFrame(parent, text='레벨 미터', padding=8)
        lf.pack(fill='x', pady=(0, 6))

        for row, label in enumerate(('IN', 'OUT')):
            ttk.Label(lf, text=label, width=4, anchor='e').grid(
                row=row, column=0, padx=(4, 6))
            meter = _LevelMeter(lf)
            meter.grid(row=row, column=1, padx=4, pady=3)
            if row == 0:
                self._in_meter  = meter
            else:
                self._out_meter = meter

    def _build_control_frame(self, parent):
        f = ttk.Frame(parent)
        f.pack(fill='x', pady=(4, 0))

        self._status_var = tk.StringVar(value='대기 중')
        ttk.Button(f, text='▶ 시작', style='Start.TButton',
                   command=self._on_start).pack(side='left', padx=4)
        ttk.Button(f, text='■ 정지', style='Stop.TButton',
                   command=self._on_stop).pack(side='left', padx=4)
        ttk.Label(f, textvariable=self._status_var).pack(side='left', padx=8)

    # ── 시작 / 정지 ───────────────────────────────────────────────

    def _on_start(self):
        if self.engine.is_running:
            return

        in_label  = self._in_var.get()
        out_label = self._out_var.get()
        in_dev    = self._in_dev_map.get(in_label)
        out_dev   = self._out_dev_map.get(out_label)
        sr        = int(self._sr_var.get())
        bs        = int(self._bs_var.get().split()[0])   # "0 (자동)" → 0

        self.params.sample_rate = sr
        self.engine = AudioEngine(self.echo_proc, self.reverb_proc, self.params,
                                  in_dev, out_dev, sr, bs)
        try:
            self.engine.start()
            driver_ms = (self.engine._stream.latency[0]
                         + self.engine._stream.latency[1]) * 1000
            mode = 'Exclusive' if self.engine._wasapi_exclusive else 'Shared'
            self._status_var.set(f'실행 중 | {mode} | 드라이버 {driver_ms:.0f}ms')
            reason = getattr(self.engine, 'exclusive_fail_reason', '')
            if reason and not self.engine._wasapi_exclusive:
                messagebox.showwarning(
                    'WASAPI Exclusive 실패 — 공유 모드로 실행 중',
                    'Exclusive 모드를 얻지 못했습니다.\n\n'
                    '지연을 최소화하려면:\n'
                    '1. Focusrite Control 앱을 완전히 종료하세요.\n'
                    '2. 다른 오디오 앱(DAW, 음악 플레이어 등)을 닫으세요.\n'
                    '3. ■ 정지 → ▶ 시작을 다시 누르세요.\n\n'
                    f'오류: {reason[:120]}'
                )
        except Exception as e:
            messagebox.showerror('오류', f'오디오 스트림 시작 실패:\n{e}')
            self._status_var.set('오류')

    def _on_stop(self):
        self.engine.stop()
        self._status_var.set('정지')

    def _on_close(self):
        self.engine.stop()
        self.destroy()

    # ── 레벨 미터 + xrun 폴링 ─────────────────────────────────────

    def _poll_level(self):
        try:
            while True:
                in_rms, out_rms = self.engine.level_queue.get_nowait()
                self._in_meter.update_level(in_rms)
                self._out_meter.update_level(out_rms)
        except queue.Empty:
            pass

        # 실제 왕복 지연 표시 (콜백 측정값)
        try:
            rt_ms = self.engine.latency_queue.get_nowait()
            # 큐를 소진해 최신값만 사용
            while True:
                rt_ms = self.engine.latency_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            cur = self._status_var.get()
            # "실측 Xms" 부분만 교체
            if '실측' in cur:
                cur = cur.rsplit('|', 1)[0].rstrip()
            mode = 'Exclusive' if self.engine._wasapi_exclusive else 'Shared'
            self._status_var.set(f'{cur} | 실측 {rt_ms:.0f}ms')

        try:
            msg = self.engine.status_queue.get_nowait()
            cur = self._status_var.get()
            if 'xrun' not in cur.lower():
                self._status_var.set(cur + ' ⚠ xrun')
        except queue.Empty:
            pass

        self.after(POLL_MS, self._poll_level)
