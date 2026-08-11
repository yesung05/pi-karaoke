from dataclasses import dataclass

SAMPLE_RATE_DEFAULT = 48000
CHANNELS_IN  = 1
CHANNELS_OUT = 2
BLOCK_SIZE_DEFAULT = 0   # 0 = PortAudio가 장치 네이티브 크기 자동 사용
DTYPE = 'float32'

@dataclass
class EchoParams:
    # 에코
    delay_sec:   float = 0.20
    feedback:    float = 0.45
    wet:         float = 0.40
    volume:      float = 1.00
    sample_rate: int   = SAMPLE_RATE_DEFAULT
    # 리버브
    reverb_room: float = 0.30   # 잔향 시간  (0.0 ~ 0.90)
    reverb_damp: float = 0.55   # 고음 흡수  (0.0 ~ 1.00)
    reverb_wet:  float = 0.12   # 잔향 믹스  (0.0 ~ 1.00)
