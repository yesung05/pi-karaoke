from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class SongInfo:
    title:         str
    artist:        str
    youtube_url:   str
    thumbnail_url: str = ''


class AppState:
    """두 GUI 창이 공유하는 전체 애플리케이션 상태."""

    def __init__(self):
        self._lock        = threading.Lock()
        self.play_queue:  list[SongInfo]      = []
        self.current_song: Optional[SongInfo] = None
        self.status:      str                 = 'stopped'
        self.echo_params  = None   # EchoParams (main에서 설정)
        self.player       = None   # MpvPlayer  (main에서 설정)
        self._listeners:  list[Callable[[], None]] = []

    # ── 리스너 ────────────────────────────────────────────────────

    def add_listener(self, cb: Callable[[], None]) -> None:
        self._listeners.append(cb)

    def _notify(self) -> None:
        for cb in self._listeners:
            try:
                cb()
            except Exception:
                pass

    # ── 대기열 ───────────────────────────────────────────────────

    def enqueue(self, song: SongInfo) -> None:
        with self._lock:
            self.play_queue.append(song)
        self._notify()

    def enqueue_priority(self, song: SongInfo) -> None:
        with self._lock:
            self.play_queue.insert(0, song)
        self._notify()

    def dequeue_next(self) -> Optional[SongInfo]:
        with self._lock:
            return self.play_queue.pop(0) if self.play_queue else None

    def remove_from_queue(self, index: int) -> None:
        with self._lock:
            if 0 <= index < len(self.play_queue):
                self.play_queue.pop(index)
        self._notify()

    def queue_snapshot(self) -> list[SongInfo]:
        with self._lock:
            return list(self.play_queue)

    # ── 상태 갱신 ────────────────────────────────────────────────

    def set_current(self, song: Optional[SongInfo]) -> None:
        with self._lock:
            self.current_song = song
        self._notify()

    def set_status(self, status: str) -> None:
        with self._lock:
            self.status = status
        self._notify()
