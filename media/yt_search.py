import logging
import threading
from dataclasses import dataclass
from typing import Callable

import yt_dlp

logger = logging.getLogger(__name__)

_SEARCH_OPTS = {
    'quiet':        True,
    'no_warnings':  True,
    'extract_flat': 'in_playlist',
    'skip_download': True,
    'ignoreerrors': True,
}


@dataclass
class SearchResult:
    title:        str
    channel:      str
    duration_sec: int
    video_id:     str
    thumbnail_url: str

    @property
    def youtube_url(self) -> str:
        return f'https://www.youtube.com/watch?v={self.video_id}'

    @property
    def duration_fmt(self) -> str:
        m, s = divmod(max(0, self.duration_sec), 60)
        return f'{m}:{s:02d}'


class YTSearcher:
    def search_async(
        self,
        query:       str,
        max_results: int = 10,
        callback:    Callable[[list[SearchResult]], None] = None,
    ) -> None:
        threading.Thread(
            target=self._worker,
            args=(query, max_results, callback),
            daemon=True,
        ).start()

    def _worker(self, query: str, max_results: int, callback):
        try:
            results = self._search(query, max_results)
        except Exception as e:
            logger.warning('YouTube 검색 실패: %s', e)
            results = []
        if callback:
            callback(results)

    def _search(self, query: str, max_results: int) -> list[SearchResult]:
        url = f'ytsearch{max_results}:{query}'
        with yt_dlp.YoutubeDL(_SEARCH_OPTS) as ydl:
            info = ydl.extract_info(url, download=False) or {}
        results = []
        for entry in (info.get('entries') or []):
            if not entry or not entry.get('id'):
                continue
            results.append(SearchResult(
                title         = entry.get('title', '(제목 없음)'),
                channel       = entry.get('channel') or entry.get('uploader', ''),
                duration_sec  = int(entry.get('duration') or 0),
                video_id      = entry['id'],
                thumbnail_url = entry.get('thumbnail', ''),
            ))
        return results
