from __future__ import annotations

import tkinter as tk
from typing import Optional

from core.app_state import AppState, SongInfo
from core.display import MonitorInfo
from media.chart import TJChartFetcher, ChartEntry, GENRES
from media.yt_search import YTSearcher, SearchResult


class MediaWindow(tk.Toplevel):
    """HDMI0 전체화면 미디어 창 (차트 브라우저 + YouTube 검색결과).

    재생 중에는 자동으로 숨겨지며, show_overlay() 로 mpv 위에 오버레이로 표시 가능.
    """

    BG        = '#0d0d14'
    HEADER_BG = '#14142a'
    LIST_BG   = '#0a0a18'
    ACCENT    = '#4466ff'
    GENRE_SEL = '#2244cc'

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
        self._genre_code  = ''          # 현재 선택된 장르 코드
        self._overlay_mode = False      # 재생 중 오버레이로 표시 중인지

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
        self._apply_geometry()
        self.after(300, self._apply_geometry)

    def _apply_geometry(self):
        if self._monitor:
            w, h = self._monitor.width, self._monitor.height
            self.geometry(f'{w}x{h}+{self._monitor.x}+{self._monitor.y}')
        else:
            self.geometry('1280x800+480+0')

    # ── UI 빌드 ─────────────────────────────────────────────────

    def _build_ui(self):
        # ── 헤더
        hdr = tk.Frame(self, bg=self.HEADER_BG, height=60)
        hdr.pack(fill='x')
        hdr.pack_propagate(False)

        self._back_btn = tk.Button(
            hdr, text='◀ 뒤로', bg=self.HEADER_BG, fg='#8888cc',
            font=('Helvetica', 16), relief='flat', cursor='hand2',
            command=self._on_back,
        )

        self._title_var = tk.StringVar(value='TJ 미디어 인기차트 TOP 100')
        tk.Label(
            hdr, textvariable=self._title_var,
            bg=self.HEADER_BG, fg='white',
            font=('Helvetica', 18, 'bold'),
        ).pack(side='left', padx=16, pady=10)

        # 닫기 버튼 (오버레이 모드에서만 의미 있음)
        tk.Button(
            hdr, text='✕ 닫기', bg='#332233', fg='#cc88cc',
            font=('Helvetica', 14), relief='flat', cursor='hand2',
            padx=10,
            command=self.hide_overlay,
        ).pack(side='right', padx=10, pady=8)

        self._status_var = tk.StringVar(value='대기 중')
        tk.Label(
            hdr, textvariable=self._status_var,
            bg=self.HEADER_BG, fg='#aaaacc',
            font=('Helvetica', 13),
        ).pack(side='right', padx=16)

        # ── 장르 탭 바
        genre_bar = tk.Frame(self, bg='#0f0f22', height=48)
        genre_bar.pack(fill='x')
        genre_bar.pack_propagate(False)

        self._genre_btns: dict[str, tk.Button] = {}
        for name, code in GENRES:
            btn = tk.Button(
                genre_bar,
                text=name,
                font=('Helvetica', 13),
                bg='#1a1a30', fg='#aaaaee',
                activebackground=self.GENRE_SEL,
                activeforeground='white',
                relief='flat', padx=10, pady=6,
                cursor='hand2',
                command=lambda c=code, n=name: self._on_genre_select(c, n),
            )
            btn.pack(side='left', padx=2, pady=4)
            self._genre_btns[code] = btn

        # 첫 번째(종합) 강조
        self._highlight_genre('')

        # ── 콘텐츠 영역
        self._content = tk.Frame(self, bg=self.BG)
        self._content.pack(fill='both', expand=True)

        self._chart_frame  = self._build_chart_frame()
        self._search_frame = self._build_search_frame()

    def _build_chart_frame(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=self.BG)

        # 검색창
        sbar = tk.Frame(f, bg='#1a1a2e', height=56)
        sbar.pack(fill='x')
        sbar.pack_propagate(False)

        self._search_entry = tk.Entry(
            sbar, font=('Helvetica', 18), bg='#2a2a3e', fg='white',
            insertbackground='white', relief='flat', bd=8,
        )
        self._search_entry.pack(side='left', fill='x', expand=True, padx=8, pady=8)
        self._search_entry.bind('<Return>', lambda e: self._on_manual_search())

        tk.Button(
            sbar, text='검색', font=('Helvetica', 15, 'bold'),
            bg=self.ACCENT, fg='white', relief='flat', padx=14,
            command=self._on_manual_search,
        ).pack(side='right', padx=8, pady=8)

        tk.Button(
            sbar, text='새로고침', font=('Helvetica', 13),
            bg='#222233', fg='#aaa', relief='flat', padx=10,
            command=lambda: self._load_chart(force=True),
        ).pack(side='right', padx=4, pady=8)

        # 차트 리스트
        lf = tk.Frame(f, bg=self.BG)
        lf.pack(fill='both', expand=True, padx=8, pady=4)
        sb = tk.Scrollbar(lf, bg='#333')
        sb.pack(side='right', fill='y')
        self._chart_lb = tk.Listbox(
            lf, yscrollcommand=sb.set,
            bg=self.LIST_BG, fg='#dde', selectbackground=self.ACCENT,
            font=('Helvetica', 16), activestyle='none',
            selectmode='single', bd=0, highlightthickness=0,
        )
        self._chart_lb.pack(fill='both', expand=True)
        self._chart_lb.bind('<Double-Button-1>', self._on_chart_select)
        self._chart_lb.bind('<Return>', self._on_chart_select)
        sb.config(command=self._chart_lb.yview)
        return f

    def _build_search_frame(self) -> tk.Frame:
        f = tk.Frame(self._content, bg=self.BG)

        lf = tk.Frame(f, bg=self.BG)
        lf.pack(fill='both', expand=True, padx=8, pady=4)
        sb = tk.Scrollbar(lf)
        sb.pack(side='right', fill='y')
        self._search_lb = tk.Listbox(
            lf, yscrollcommand=sb.set,
            bg=self.LIST_BG, fg='#dde', selectbackground=self.ACCENT,
            font=('Helvetica', 16), activestyle='none',
            selectmode='single', bd=0, highlightthickness=0,
        )
        self._search_lb.pack(fill='both', expand=True)
        self._search_lb.bind('<Double-Button-1>', self._on_search_select)
        sb.config(command=self._search_lb.yview)

        btn_bar = tk.Frame(f, bg=self.BG)
        btn_bar.pack(fill='x', padx=8, pady=8)
        tk.Button(
            btn_bar, text='▶  재생 / 대기열 추가',
            font=('Helvetica', 16, 'bold'),
            bg='#006633', fg='white', relief='flat', pady=10,
            command=self._on_search_select,
        ).pack(fill='x')
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
                btn.config(bg=self.GENRE_SEL, fg='white', font=('Helvetica', 13, 'bold'))
            else:
                btn.config(bg='#1a1a30', fg='#aaaaee', font=('Helvetica', 13))

    # ── 뷰 전환 ─────────────────────────────────────────────────

    def _show_view(self, view: str) -> None:
        for frame in (self._chart_frame, self._search_frame):
            frame.pack_forget()

        if view == 'chart':
            self._chart_frame.pack(fill='both', expand=True)
            self._back_btn.pack_forget()
        elif view == 'search':
            self._search_frame.pack(fill='both', expand=True)
            self._back_btn.pack(side='left', padx=8)

    def _on_back(self):
        self._show_view('chart')

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

    # ── 이벤트 핸들러 ────────────────────────────────────────────

    def _on_chart_select(self, _event=None):
        idx = self._chart_lb.curselection()
        if not idx or not self._chart_data:
            return
        i = idx[0]
        if i >= len(self._chart_data):
            return
        entry = self._chart_data[i]
        self._do_search(f'{entry.title} {entry.artist} 노래방')

    def _on_manual_search(self):
        q = self._search_entry.get().strip()
        if q:
            suffix = '' if '노래방' in q else ' 노래방'
            self._do_search(q + suffix)

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

    # ── 오버레이 API ─────────────────────────────────────────────

    def show_overlay(self):
        """재생 중에도 mpv 위에 오버레이로 표시."""
        self._overlay_mode = True
        self.deiconify()
        self._apply_geometry()
        self.lift()
        self.attributes('-topmost', True)

    def hide_overlay(self):
        """오버레이를 닫고 다시 mpv 화면만 보이게."""
        self._overlay_mode = False
        # 재생 중이면 withdraw, 아니면 유지
        if self.app_state.status in ('playing', 'loading', 'paused'):
            self.withdraw()
        else:
            self.attributes('-topmost', False)

    # ── 상태 갱신 (AppState 리스너) ──────────────────────────────

    def _refresh_status(self):
        song   = self.app_state.current_song
        status = self.app_state.status

        if status in ('playing', 'loading') and not self._overlay_mode:
            # mpv가 화면을 점유하므로 숨김
            self.withdraw()
        elif status == 'stopped' and not self.winfo_ismapped():
            # 재생 종료 → 다시 표시
            self._overlay_mode = False
            self.deiconify()
            self.attributes('-topmost', False)
            self._apply_geometry()

        if song and status != 'stopped':
            icon = '▶' if status == 'playing' else ('⏸' if status == 'paused' else '⏳')
            self._status_var.set(f'{icon} {song.title}  —  {song.artist}')
        else:
            self._status_var.set('대기 중')
