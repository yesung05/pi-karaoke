from __future__ import annotations

import logging
from typing import Optional

from core.app_state import AppState, SongInfo
from core.display import MonitorInfo
from media.player import MpvPlayer

logger = logging.getLogger(__name__)


class PlaybackManager:
    """대기열 관리 + mpv 조율."""

    def __init__(self, player: MpvPlayer, state: AppState,
                 media_mon: Optional[MonitorInfo] = None):
        self._player    = player
        self._state     = state
        self._media_mon = media_mon
        player.set_end_callback(self._on_end)

    # ── 공개 API ─────────────────────────────────────────────────

    def play_or_enqueue(self, song: SongInfo) -> None:
        if self._state.status == 'stopped':
            self._play(song)
        else:
            self._state.enqueue(song)

    def pause(self) -> None:
        self._player.pause()
        self._state.set_status('paused')

    def resume(self) -> None:
        self._player.resume()
        self._state.set_status('playing')

    def toggle_pause(self) -> None:
        status = self._state.status
        if status == 'playing':
            self.pause()
        elif status == 'paused':
            self.resume()

    def skip(self) -> None:
        self._player.skip()

    def stop(self) -> None:
        self._player.stop()
        self._state.set_current(None)
        self._state.set_status('stopped')

    # ── 내부 ─────────────────────────────────────────────────────

    def _play(self, song: SongInfo) -> None:
        self._state.set_current(song)
        self._state.set_status('loading')
        kw: dict = {}
        if self._media_mon:
            kw = dict(
                x      = self._media_mon.x,
                y      = self._media_mon.y,
                width  = self._media_mon.width,
                height = self._media_mon.height,
            )
        logger.info('재생 시작: %s — %s', song.title, song.artist)
        self._player.play(song.youtube_url, **kw)
        self._state.set_status('playing')

    def _on_end(self) -> None:
        """mpv 종료 시 배경 스레드에서 호출됨. GUI 직접 접근 금지."""
        next_song = self._state.dequeue_next()
        if next_song:
            self._play(next_song)
        else:
            self._player.stop()
            self._state.set_current(None)
            self._state.set_status('stopped')
