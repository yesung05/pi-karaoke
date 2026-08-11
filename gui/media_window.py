from __future__ import annotations

import tkinter as tk
from typing import Optional

from core.app_state import AppState, SongInfo
from core.display import MonitorInfo
from media.chart import TJChartFetcher, ChartEntry, GENRES
from media.yt_search import YTSearcher, SearchResult

# 오버레이 패널 높이 비율 (모니터 전체 높이 대비)
PANEL_H_RATIO = 0.30


class MediaWindow(tk.Toplevel):
    """HDMI0 상단 오버레이 패널 (차트 브라우저 + YouTube 검색).

    mpv가 전체 화면으로 배경에 재생되는 동안 이 창이 항상 위에 고정됩니다.
    재생 중에도 숨기지 않으며, 닫기 버튼으로 수동으로 숨길 수 있습니다.
    """

    BG        = '#0d0d18'
    HEADER_BG = '#12122a'
    LIST_BG   = '#080810'
    ACCENT    = '#4466ff'
    GENRE_SEL = '#2244cc'
    ALPHA     = 0.88       # 반투명 (Wayland compositor 지원 시 적용)

    def __init__(self, root: tk.Tk, app_state: AppState,
                 monitor: Optional[MonitorInfo] = None,
                 playback_mgr=None):
        super().__init__(root)
        self.app_state    = app_state
        self._monitor     = monitor
        self._playback    = playback_mgr
        self._chart_fetch = TJChartFetcher()
        self._searcher    = YTSearcher()
        self._chart_data:  list[ChartEntry]   = []
        self._search_data: list[SearchResult] = []
        self._genre_code  = ''
        self._hidden      = False   # 사용자가 수동으로 숨김

        self._configure_geometry()
        self._build_ui()
        self._show_view('chart')
        self._load_chart()

        app_state.add_listener(lambda: self.after(0, self._refresh_status))

    # ── 창 설정 ─────────────────────────────────────────────────

    def _configure_geometry(self):
        self.title('Pi Karaoke - 미디어')
        self.configure(bg=self.BG)
        self.overrideredirect(True)
        # 항상 최상위 (mpv 위)
        self.attributes('-topmost', True)
        try:
            self.attributes('-alpha', self.ALPHA)
        except tk.TclError:
            pass  # X11에서 지원 안 할 수 있음
        self._apply_geometry()
        self.after(300, self._apply_geometry)

    def _apply_geometry(self):
        if self._monitor:
            w  = self._monitor.width
            ph = max(200, int(self._monitor.height * PANEL_H_RATIO))
            x  = self._monitor.x
            y  = self._monitor.y
        else:
            w, ph, x, y = 1280, 240, 480, 0
        self.geometry(f'{w}x{ph}+{x}+{y}')

    # ── UI 빌드 ─────────────────────────────────────────────────

    def _build_ui(self):
        # ── 헤더 바
        hdr = tk.Frame(self, bg=self.HEADER_BG, height=44)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)

        self._title_var = tk.StringVar(value='TJ 미디어 인기차트 TOP 100')
        tk.Label(
            hdr, textvariable=self._title_var,
            bg=self.HEADER_BG, fg='white',
            font=('Helvetica', 15, 'bold'),
        ).pack(side='left', padx=12, pady=6)

        # 닫기 버튼 (패널 숨기기 — 컨트롤러 버튼으로 다시 열기)
        tk.Button(
            hdr, text='✕',
            bg=self.HEADER_BG, fg='#997799',
            font=('Helvetica', 14), relief='flat', padx=8, pady=2,
            cursor='hand2',
            command=self._manual_hide,
        ).pack(side='right', padx=8, pady=4)

        self._status_var = tk.StringVar(value='대기 중')
        tk.Label(
            hdr, textvariable=self._status_var,
            bg=self.HEADER_BG, fg='#9999cc',
            font=('Helvetica', 12),
        ).pack(side='right', padx=10)

        self._back_btn = tk.Button(
            hdr, text='◀ 뒤로',
            bg=self.HEADER_BG, fg='#8888cc',
            font=('Helvetica', 13), relief='flat', cursor='hand2',
            command=self._on_back,
        )

        # ── 장르 탭 바
        genre_bar = tk.Frame(self, bg='#0c0c22', height=38)
        genre_bar.pack(fill='x')
        genre_bar.pack_propagate(False)

        self._genre_btns: dict[str, tk.Button] = {}
        for name, code in GENRES:
            btn = tk.Button(
                genre_bar, text=name,
                font=('Helvetica', 11),
                bg='#181830', fg='#9999dd',
                activebackground=self.GENRE_SEL, activeforeground='white',
                relief='flat', padx=8, pady=4, cursor='hand2',
                command=lambda c=code, n=name: self._on_genre_select(c, n),
            )
            btn.pack(side='left', padx=1, pady=2)
            self._genre_btns[code] = btn
        self._highlight_genre('')

        # ── 검색 입력 바 (항상 표시)
        sbar = tk.Frame(self, bg='#16162e', height=46)
        sbar.pack(fill='x')
        sbar.pack_propagate(False)

        self._search_entry = tk.Entry(
            sbar, font=('Helvetica', 16), bg='#22223c', fg='white',
            insertbackground='white', relief='flat', bd=6,
        )
        self._search_entry.pack(side='left', fill='x', expand=True, padx=8, pady=6)
        self._search_entry.bind('<Return>', lambda e: self._on_manual_search())

        tk.Button(
            sbar, text='검색', font=('Helvetica', 13, 'bold'),
            bg=self.ACCENT, fg='white', relief='flat', padx=12,
            command=self._on_manual_search,
        ).pack(side='right', padx=6, pady=6)

        tk.Button(
            sbar, text='↺', font=('Helvetica', 13),
            bg='#202033', fg='#aaa', relief='flat', padx=8,
            command=lambda: self._load_chart(force=True),
        ).pack(side='right', padx=2, pady=6)

        # ── 콘텐츠 (남은 공간)
        self._content = tk.Frame(self, bg=self.BG)
        self._content.pack(fill='both', expand=True)

        self._chart_frame  = self._build_chart_frame()
        self._search_frame = self._build_search_frame()

    def _build_chart_frame(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=self.BG)
        sb = tk.Scrollbar(f, bg='#333')
        sb.pack(side='right', fill='y')
        self._chart_lb = tk.Listbox(
            f, yscrollcommand=sb.set,
            bg=self.LIST_BG, fg='#ccd',
            selectbackground=self.ACCENT,
            font=('Helvetica', 14), activestyle='none',
            selectmode='single', bd=0, highlightthickness=0,
        )
        self._chart_lb.pack(fill='both', expand=True)
        self._chart_lb.bind('<Double-Button-1>', self._on_chart_select)
        self._chart_lb.bind('<Return>', self._on_chart_select)
        sb.config(command=self._chart_lb.yview)
        return f

    def _build_search_frame(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=self.BG)

        btn_bar = tk.Frame(f, bg=self.BG)
        btn_bar.pack(fill='x', padx=6, pady=4)
        tk.Button(
            btn_bar, text='▶  재생 / 대기열 추가',
            font=('Helvetica', 14, 'bold'),
            bg='#005522', fg='white', relief='flat', pady=6,
            command=self._on_search_select,
        ).pack(fill='x')

        lf = tk.Frame(f, bg=self.BG)
        lf.pack(fill='both', expand=True, padx=6)
        sb = tk.Scrollbar(lf)
        sb.pack(side='right', fill='y')
        self._search_lb = tk.Listbox(
            lf, yscrollcommand=sb.set,
            bg=self.LIST_BG, fg='#ccd',
            selectbackground=self.ACCENT,
            font=('Helvetica', 13), activestyle='none',
            selectmode='single', bd=0, highlightthickness=0,
        )
        self._search_lb.pack(fill='both', expand=True)
        self._search_lb.bind('<Double-Button-1>', self._on_search_select)
        sb.config(command=self._search_lb.yview)
        return f

    # ── 장르 탭 ─────────────────────────────────────────────────

    def _on_genre_select(self, code: str, name: str):
        self._genre_code = code
        self._highlight_genre(code)
        self._title_var.set(f'TJ 미디어 {name} TOP 100')
        self._show_view('chart')
        self._load_chart()

    def _highlight_genre(self, selected_code: str):
        for code, btn in self._genre_btns.items():
            if code == selected_code:
                btn.config(bg=self.GENRE_SEL, fg='white',
                           font=('Helvetica', 11, 'bold'))
            else:
                btn.config(bg='#181830', fg='#9999dd',
                           font=('Helvetica', 11))

    # ── 뷰 전환 ─────────────────────────────────────────────────

    def _show_view(self, view: str) -> None:
        for frame in (self._chart_frame, self._search_frame):
            frame.pack_forget()
        if view == 'chart':
            self._chart_frame.pack(fill='both', expand=True)
            self._back_btn.pack_forget()
        elif view == 'search':
            self._search_frame.pack(fill='both', expand=True)
            self._back_btn.pack(side='left', padx=6)

    def _on_back(self):
        self._show_view('chart')
        short = self._title_var.get()
        for name, code in GENRES:
            if code == self._genre_code:
                self._title_var.set(f'TJ 미디어 {name} TOP 100')
                break

    # ── 차트 ────────────────────────────────────────────────────

    def _load_chart(self, force: bool = False):
        self._chart_lb.delete(0, 'end')
        self._chart_lb.insert('end', '  차트 불러오는 중...')
        self._chart_fetch.fetch_async(
            callback=lambda data: self.after(0, lambda: self._populate_chart(data)),
            genre_code=self._genre_code,
        )

    def _populate_chart(self, entries: list[ChartEntry]):
        self._chart_data = entries
        self._chart_lb.delete(0, 'end')
        if not entries:
            self._chart_lb.insert('end', '  차트를 불러올 수 없습니다. (네트워크 확인)')
            return
        for e in entries:
            self._chart_lb.insert(
                'end',
                f'  {e.rank:3d}.  {e.title}   —   {e.artist}',
            )

    # ── 검색 ────────────────────────────────────────────────────

    def _on_manual_search(self):
        q = self._search_entry.get().strip()
        if q:
            suffix = '' if '노래방' in q else ' 노래방'
            self._do_search(q + suffix)

    def _on_chart_select(self, _event=None):
        idx = self._chart_lb.curselection()
        if not idx or not self._chart_data:
            return
        i = idx[0]
        if i >= len(self._chart_data):
            return
        entry = self._chart_data[i]
        self._do_search(f'{entry.title} {entry.artist} 노래방')

    def _do_search(self, query: str):
        self._show_view('search')
        short_q = query[:50] + ('...' if len(query) > 50 else '')
        self._title_var.set(f'검색 중: {short_q}')
        self._search_lb.delete(0, 'end')
        self._search_lb.insert('end', '  검색 중...')
        self._search_data = []
        self._searcher.search_async(
            query, max_results=10,
            callback=lambda r: self.after(0, lambda: self._on_search_done(r, query)),
        )

    def _on_search_done(self, results: list[SearchResult], query: str):
        self._search_data = results
        short_q = query[:40] + ('...' if len(query) > 40 else '')
        self._title_var.set(f'검색 결과: {short_q}  ({len(results)}개)')
        self._search_lb.delete(0, 'end')
        if not results:
            self._search_lb.insert('end', '  검색 결과가 없습니다.')
            return
        for r in results:
            self._search_lb.insert(
                'end',
                f'  [{r.duration_fmt}]  {r.title}   —   {r.channel}',
            )

    def _on_search_select(self, _event=None):
        idx = self._search_lb.curselection()
        if not idx or not self._search_data:
            return
        i = idx[0]
        if i >= len(self._search_data):
            return
        result = self._search_data[i]
        song = SongInfo(
            title         = result.title,
            artist        = result.channel,
            youtube_url   = result.youtube_url,
            thumbnail_url = result.thumbnail_url,
        )
        if self._playback:
            self._playback.play_or_enqueue(song)
        self._search_lb.itemconfig(i, bg='#003322', fg='#aaffaa')

    # ── 오버레이 API (ControlWindow 호환) ────────────────────────

    def show_overlay(self):
        """컨트롤러 '검색' 버튼에서 호출 — 패널을 다시 표시."""
        self._hidden = False
        self.deiconify()
        self._apply_geometry()
        self.attributes('-topmost', True)
        self.lift()

    def hide_overlay(self):
        """패널 숨기기 (show_overlay로 다시 열 수 있음)."""
        self._manual_hide()

    def _manual_hide(self):
        self._hidden = True
        self.withdraw()

    # ── 상태 갱신 ────────────────────────────────────────────────

    def _refresh_status(self):
        song   = self.app_state.current_song
        status = self.app_state.status

        # 재생 중에도 패널은 숨기지 않음 (오버레이 고정)
        if self._hidden:
            return

        if not self.winfo_ismapped():
            self.deiconify()
            self._apply_geometry()
            self.attributes('-topmost', True)

        if song and status != 'stopped':
            icon = '▶' if status == 'playing' else ('⏸' if status == 'paused' else '⏳')
            self._status_var.set(f'{icon} {song.title[:30]}  —  {song.artist[:20]}')
        else:
            self._status_var.set('대기 중')
