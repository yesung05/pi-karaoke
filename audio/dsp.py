import numpy as np
from config import EchoParams


def _buf_read(buf: np.ndarray, pos: int, delay: int, n: int) -> np.ndarray:
    """원형 버퍼에서 n샘플 읽기 (랩어라운드 처리)."""
    rp = (pos - delay) % len(buf)
    if rp + n <= len(buf):
        return buf[rp:rp + n].copy()
    cut = len(buf) - rp
    return np.concatenate([buf[rp:], buf[:n - cut]])


def _buf_write(buf: np.ndarray, pos: int, data: np.ndarray) -> int:
    """원형 버퍼에 data 쓰기, 다음 위치 반환."""
    n  = len(data)
    we = pos + n
    if we <= len(buf):
        buf[pos:we] = data
    else:
        cut = len(buf) - pos
        buf[pos:] = data[:cut]
        buf[:n - cut] = data[cut:]
    return we % len(buf)


class EchoProcessor:
    MAX_DELAY_SEC = 2.0

    def __init__(self, params: EchoParams):
        self.params = params
        self._buf_size = int(self.MAX_DELAY_SEC * params.sample_rate)
        self._buffer: np.ndarray | None = None
        self._write_pos = 0

    def _ensure_buffer(self, n_channels: int):
        if self._buffer is None or self._buffer.shape[1] != n_channels:
            self._buffer = np.zeros((self._buf_size, n_channels), dtype=np.float32)
            self._write_pos = 0

    def reset(self):
        self._buffer = None
        self._write_pos = 0

    def process(self, indata: np.ndarray) -> np.ndarray:
        """indata: (frames, ch) float32 → 에코 적용 후 동일 shape 반환."""
        n_frames, n_ch = indata.shape
        self._ensure_buffer(n_ch)

        p   = self.params
        buf = self._buffer
        wp  = self._write_pos
        dl  = max(n_frames + 1, min(int(p.delay_sec * p.sample_rate), self._buf_size - 1))

        rp = (wp - dl) % self._buf_size
        if rp + n_frames <= self._buf_size:
            delayed = buf[rp:rp + n_frames].copy()
        else:
            cut = self._buf_size - rp
            delayed = np.concatenate([buf[rp:], buf[:n_frames - cut]])

        out     = indata + p.wet * delayed
        written = indata + p.feedback * delayed

        we = wp + n_frames
        if we <= self._buf_size:
            buf[wp:we] = written
        else:
            cut = self._buf_size - wp
            buf[wp:] = written[:cut]
            buf[:n_frames - cut] = written[cut:]

        self._write_pos = we % self._buf_size
        np.multiply(out, p.volume, out=out)
        return np.clip(out, -1.0, 1.0, out=out)


class ReverbProcessor:
    """Freeverb 스타일 리버브: 4 병렬 콤 필터 + 2 직렬 올패스 필터.

    모든 딜레이 > 블록 크기이므로 완전 벡터화 (Python 샘플 루프 없음).
    """

    # Freeverb 원본(44.1kHz) 딜레이 — process() 초기화 시 sample_rate로 스케일
    _COMB_DELAYS_44K = [1116, 1188, 1277, 1356]
    _AP_DELAYS_44K   = [556,  441]
    _AP_G            = 0.5   # 올패스 피드백 계수 (고정)

    def __init__(self, params: EchoParams):
        self.params = params
        self._init(params.sample_rate)

    def _init(self, sr: int):
        scale = sr / 44100
        self._comb_dl = [max(16, int(d * scale)) for d in self._COMB_DELAYS_44K]
        self._ap_dl   = [max(16, int(d * scale)) for d in self._AP_DELAYS_44K]

        self._comb_buf = [np.zeros(d, dtype=np.float32) for d in self._comb_dl]
        self._comb_pos = [0] * len(self._comb_dl)
        self._lp_state = [0.0] * len(self._comb_dl)   # 콤 필터 내부 LP 상태
        self._ap_buf   = [np.zeros(d, dtype=np.float32) for d in self._ap_dl]
        self._ap_pos   = [0] * len(self._ap_dl)

    def reset(self):
        self._init(self.params.sample_rate)

    def _comb(self, i: int, x: np.ndarray, room: float, damp: float) -> np.ndarray:
        """Freeverb 콤 필터: y[n] = x[n] + room * LP(y[n - D]).

        LP(v) = (1-damp)*v + damp*LP_prev  — 고음 흡수, 1-pole IIR.
        딜레이 D >> 블록 크기이므로 LP 적용 후 메인 가산은 완전 벡터화.
        LP 자체만 블록 크기 n의 Python 루프 (n≈48, 부담 없음).
        """
        delayed = _buf_read(self._comb_buf[i], self._comb_pos[i], self._comb_dl[i], len(x))

        # 1-pole LP를 delayed에 적용해 고음 감쇠
        lp = np.empty(len(delayed), dtype=np.float32)
        state = self._lp_state[i]
        a, b = 1.0 - damp, damp
        for j in range(len(delayed)):
            state = a * delayed[j] + b * state
            lp[j] = state
        self._lp_state[i] = state

        y = x + room * lp
        self._comb_pos[i] = _buf_write(self._comb_buf[i], self._comb_pos[i], y)
        return y

    def _allpass(self, i: int, x: np.ndarray) -> np.ndarray:
        """올패스 필터 (Schroeder 재공식화):
        v[n] = x[n] + g * v[n-D]
        y[n] = v[n-D] - g * v[n]
        """
        g = self._AP_G
        vd = _buf_read(self._ap_buf[i], self._ap_pos[i], self._ap_dl[i], len(x))
        v  = x + g * vd
        y  = vd - g * v
        self._ap_pos[i] = _buf_write(self._ap_buf[i], self._ap_pos[i], v)
        return y

    def process(self, indata: np.ndarray) -> np.ndarray:
        """indata: (frames, ch) → 리버브 믹스 적용 후 동일 shape 반환."""
        p = self.params
        if p.reverb_wet < 1e-4:
            return indata

        n_frames, n_ch = indata.shape
        mono = indata[:, 0]   # 모노 처리 (CHANNELS_IN=1)

        # ── 4 콤 필터 병렬 합산 (damping 포함) ──────────────────────
        comb_sum = np.zeros(n_frames, dtype=np.float32)
        for i in range(len(self._comb_dl)):
            comb_sum += self._comb(i, mono, p.reverb_room, p.reverb_damp)
        comb_sum /= len(self._comb_dl)

        # ── 2 올패스 직렬 ────────────────────────────────────────────
        ap = comb_sum
        for i in range(len(self._ap_dl)):
            ap = self._allpass(i, ap)

        # ── wet 믹스 (브로드캐스트해 다채널 지원) ────────────────────
        reverb = np.expand_dims(ap, axis=1)          # (n, 1)
        out = indata + p.reverb_wet * reverb
        return np.clip(out, -1.0, 1.0, out=out)
