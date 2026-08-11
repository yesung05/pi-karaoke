import logging
import threading
import time
from dataclasses import dataclass
from datetime import date
from typing import Callable

import requests

logger = logging.getLogger(__name__)

# (표시 이름, strType 코드)
GENRES: list[tuple[str, str]] = [
    ('종합',     ''),
    ('가요',     '1'),
    ('POP',      '2'),
    ('JPOP',     '3'),
    ('발라드',   '4'),
    ('댄스',     '5'),
    ('트로트',   '6'),
    ('포크',     '7'),
    ('OST',      '8'),
    ('락/메탈',  '9'),
    ('랩/힙합',  '10'),
    ('R&B/어반', '11'),
]


@dataclass
class ChartEntry:
    rank:   int
    title:  str
    artist: str


class TJChartFetcher:
    API_URL   = 'https://www.tjmedia.com/legacy/api/topAndHot100'
    CACHE_TTL = 3600
    HEADERS   = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
        'Content-Type': 'application/json',
        'Referer': 'https://www.tjmedia.com/',
        'Origin': 'https://www.tjmedia.com',
    }

    def __init__(self):
        self._cache:      dict[str, list[ChartEntry]] = {}
        self._cache_time: dict[str, float]            = {}
        self._lock        = threading.Lock()

    def get(self, genre_code: str = '', force: bool = False) -> list[ChartEntry]:
        with self._lock:
            if not force and genre_code in self._cache_time:
                if (time.time() - self._cache_time[genre_code]) < self.CACHE_TTL:
                    return list(self._cache.get(genre_code, []))
        return self._fetch(genre_code)

    def fetch_async(
        self,
        callback:   Callable[[list[ChartEntry]], None],
        genre_code: str = '',
    ) -> None:
        threading.Thread(
            target=lambda: callback(self._fetch(genre_code)), daemon=True
        ).start()

    # ── 내부 ─────────────────────────────────────────────────────────

    @staticmethod
    def _date_range() -> tuple[str, str]:
        today = date.today()
        start = today.replace(day=1).strftime('%Y-%m-%d')
        end   = today.strftime('%Y-%m-%d')
        return start, end

    def _fetch(self, genre_code: str = '') -> list[ChartEntry]:
        start, end = self._date_range()
        payload = {
            'chartType':       'TOP',
            'strType':         genre_code,
            'searchStartDate': start,
            'searchEndDate':   end,
        }
        try:
            resp = requests.post(
                self.API_URL,
                json=payload,
                headers=self.HEADERS,
                timeout=15,
            )
            resp.raise_for_status()
            data  = resp.json()
            items = data.get('resultData', {}).get('items', [])
            entries: list[ChartEntry] = []
            for item in items:
                try:
                    rank   = int(item.get('rank', 0))
                    title  = str(item.get('indexSong', '')).strip()
                    artist = str(item.get('indexTitle', '')).strip()
                    if rank and title:
                        entries.append(ChartEntry(rank=rank, title=title, artist=artist))
                except (ValueError, TypeError):
                    continue
        except Exception as e:
            logger.warning('TJ 차트 불러오기 실패 (genre=%r): %s', genre_code, e)
            with self._lock:
                return list(self._cache.get(genre_code, []))

        entries = entries[:100]
        with self._lock:
            self._cache[genre_code]      = entries
            self._cache_time[genre_code] = time.time()
        return entries
