from __future__ import annotations

import tkinter as tk
from typing import Optional

from core.app_state import AppState, SongInfo
from core.display import MonitorInfo
from media.chart import TJChartFetcher, ChartEntry, GENRES
from media.yt_search import YTSearcher, SearchResult

# 오버레이 패널 높이 비율 (모니터 전체 높이 대비)
PANEL_H_RATIO = 0.30
INACTIVITY_MS = 20_000   # 20초 조작 없으면 자동 닫힘


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
        self._hidden           = False   # 사용자가 수동으로 숨김
        self._inactivity_job   = None    # after() 핸들 (자동 닫힘 타이머)

        self._configure_geometry()
        self._build_ui()
        self.bind_all('<Escape>', lambda e: self.master.destroy())
        self.bind_all('<Control-q>', lambda e: self.master.destroy())
        self._show_view('chart')
        self._load_chart()

        app_state.add_listener(lambda: self.after(0, self._refresh_status))

        # 창 안 어떤 상호작용이든 비활성 타이머 리셋
        self._bind_activity_recursive(self)

    # ── 창 설정 ─────────────────────────────────────────────────

    def _configure_geometry(self):
        self.title('Pi Karaoke - 미디어')
        self.configure(bg=self.BG)
        self.overrideredirect(True)
        # 항상 최상위 (mpv 위)
        self.attributes('-topmost', True)
        self.attributes('-fullscreen', False)
        try:
            self.attributes('-alpha', self.ALPHA)
        except tk.TclError:
            pass  # X11에서 지원 안 할 수 있음
        self._apply_geometry()
        self.update_idletasks()
        self.deiconify()
        self.lift()
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
        genre_bar = tk.Frame(self, bg='#0c0c22', height=48)
        genre_bar.pack(fill='x')
        genre_bar.pack_propagate(False)

        self._genre_btns: dict[str, tk.Button] = {}
        for name, code in GENRES:
            btn = tk.Button(
                genre_bar, text=name,
                font=('Helvetica', 15, 'bold'),
                bg='#181830', fg='#9999dd',
                activebackground=self.GENRE_SEL, activeforeground='white',
                relief='flat', padx=10, pady=7, cursor='hand2',
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
            sbar, font=('Helvetica', 18, 'bold'), bg='#22223c', fg='white',
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
            font=('Helvetica', 20, 'bold'), activestyle='none',
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

        btn_bar.pack_forget()
        lf = tk.Frame(f, bg=self.BG)
        lf.pack(fill='both', expand=True, padx=6)
        sb = tk.Scrollbar(lf)
        sb.pack(side='right', fill='y')
        self._search_lb = tk.Listbox(
            lf, yscrollcommand=sb.set,
            bg=self.LIST_BG, fg='#ccd',
            selectbackground=self.ACCENT,
            font=('Helvetica', 19, 'bold'), activestyle='none',
            selectmode='single', bd=0, highlightthickness=0,
        )
        self._search_lb.pack(fill='both', expand=True)
        self._search_lb.bind('<Double-Button-1>', self._on_search_select)
        sb.config(command=self._search_lb.yview)
        return f

    # ── 비활성 타이머 ────────────────────────────────────────────

    def _bind_activity_recursive(self, widget):
        """위젯과 모든 자식에 상호작용 감지 바인딩 — 스크롤·클릭·키 입력 시 타이머 리셋."""
        for seq in ('<ButtonPress-1>', '<Button-4>', '<Button-5>',
                    '<MouseWheel>', '<Key>'):
            widget.bind(seq, self._on_any_activity, add=True)
        for child in widget.winfo_children():
            self._bind_activity_recursive(child)

    def _on_any_activity(self, _event=None):
        if not self._hidden:
            self._reset_inactivity_timer()

    def _reset_inactivity_timer(self):
        """조작이 감지될 때마다 호출 — 20초 타이머를 재시작."""
        if self._inactivity_job is not None:
            self.after_cancel(self._inactivity_job)
        self._inactivity_job = self.after(INACTIVITY_MS, self._manual_hide)

    # ── 장르 탭 ─────────────────────────────────────────────────

    def _on_genre_select(self, code: str, name: str):
        self._reset_inactivity_timer()
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
        self._reset_inactivity_timer()
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
        self._bind_activity_recursive(self._chart_lb)

    # ── 검색 ────────────────────────────────────────────────────

    def _on_manual_search(self):
        self._reset_inactivity_timer()
        q = self._search_entry.get().strip()
        if q:
            suffix = '' if '노래방' in q else ' 노래방'
            self._do_search(q + suffix)

    def _on_chart_select(self, _event=None):
        self._reset_inactivity_timer()
        idx = self._chart_lb.curselection()
        if not idx or not self._chart_data:
            return
        i = idx[0]
        if i >= len(self._chart_data):
            return
        entry = self._chart_data[i]
        self._do_search(f'{entry.title} {entry.artist} 노래방')

    def _active_chart_query(self):
        """Return the query represented by the currently hovered chart row."""
        idx = self._chart_lb.curselection()
        if not idx or not self._chart_data or idx[0] >= len(self._chart_data):
            return None
        entry = self._chart_data[idx[0]]
        return f'{entry.title} {entry.artist} 노래방'

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
        self._bind_activity_recursive(self._search_lb)

    def _on_search_select(self, _event=None):
        self._reset_inactivity_timer()
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

    @property
    def is_visible(self) -> bool:
        return not self._hidden and self.winfo_ismapped()

    def selected_song(self):
        idx = self._search_lb.curselection()
        if not idx or idx[0] >= len(self._search_data):
            return None
        r = self._search_data[idx[0]]
        return SongInfo(r.title, r.channel, r.youtube_url, r.thumbnail_url)

    def _song_from_result(self, result: SearchResult) -> SongInfo:
        return SongInfo(result.title, result.channel, result.youtube_url,
                        result.thumbnail_url)

    def _search_then(self, query: str, action: str) -> None:
        """Search a chart row and apply an action to result #1."""
        def done(results: list[SearchResult]):
            # 차트 화면은 유지하고, 내부 검색 결과만 액션에 사용한다.
            self._search_data = results
            if not results or not self._playback:
                return
            song = self._song_from_result(results[0])
            if action == 'priority':
                self.app_state.enqueue_priority(song)
            elif action == 'reserve':
                # 예약은 현재 재생 상태와 무관하게 대기열에만 추가한다.
                self.app_state.enqueue(song)
            elif action == 'start':
                self._playback._play(song)

        self._searcher.search_async(
            query, max_results=10,
            callback=lambda r: self.after(0, lambda: done(r)),
        )

    def reserve_active(self, priority: bool = False) -> bool:
        """Reserve hovered item; chart rows automatically use search result #1."""
        if self._search_frame.winfo_ismapped():
            song = self.selected_song()
            if not song or not self._playback:
                return False
            if priority:
                self.app_state.enqueue_priority(song)
            else:
                # 예약 버튼은 즉시 재생하지 않고 항상 대기열에 추가한다.
                self.app_state.enqueue(song)
            return True
        query = self._active_chart_query()
        if not query:
            return False
        self._search_then(query, 'priority' if priority else 'reserve')
        return True

    def start_active(self) -> bool:
        """Play the currently hovered search/chart item immediately."""
        if not self._playback:
            return False
        if self._search_frame.winfo_ismapped():
            song = self.selected_song()
            if not song:
                return False
            self._playback._play(song)
            return True
        query = self._active_chart_query()
        if not query:
            return False
        self._search_then(query, 'start')
        return True

    def move_chart_selection(self, delta: int):
        if not self._chart_data:
            return
        current = self._chart_lb.curselection()
        index = (current[0] if current else 0) + delta
        index = max(0, min(len(self._chart_data) - 1, index))
        self._chart_lb.selection_clear(0, 'end')
        self._chart_lb.selection_set(index)
        self._chart_lb.activate(index)
        self._chart_lb.see(index)

    def confirm_chart_selection(self):
        self._on_chart_select()

    def move_active_selection(self, delta: int):
        lb = self._search_lb if self._search_frame.winfo_ismapped() else self._chart_lb
        count = lb.size()
        if not count:
            return
        current = lb.curselection(); index = (current[0] if current else 0) + delta
        index = max(0, min(count - 1, index))
        lb.selection_clear(0, 'end'); lb.selection_set(index); lb.activate(index); lb.see(index)

    def confirm_active_selection(self):
        if self._search_frame.winfo_ismapped():
            self._on_search_select()
        else:
            self._on_chart_select()

    def move_genre(self, delta: int):
        codes = [code for _, code in GENRES]
        current = codes.index(self._genre_code) if self._genre_code in codes else 0
        index = max(0, min(len(GENRES) - 1, current + delta))
        name, code = GENRES[index]
        self._on_genre_select(code, name)

    def toggle_overlay(self):
        """리모컨 '검색' 버튼 — 열려 있으면 닫고, 닫혀 있으면 연다."""
        if self.is_visible:
            self._manual_hide()
        else:
            self.show_overlay()

    def show_overlay(self):
        """패널 표시 + 비활성 타이머 시작."""
        self._hidden = False
        self.deiconify()
        self._apply_geometry()
        self.attributes('-topmost', True)
        self.lift()
        self._reset_inactivity_timer()

    def hide_overlay(self):
        self._manual_hide()

    def _manual_hide(self):
        self._hidden = True
        if self._inactivity_job is not None:
            self.after_cancel(self._inactivity_job)
            self._inactivity_job = None
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
