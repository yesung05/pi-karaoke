# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

Raspberry Pi 4 기반 노래방 시스템. Focusrite Scarlett Solo 오디오 인터페이스로 마이크 에코/리버브를 처리하고, mpv로 YouTube 영상을 재생하며, 듀얼 HDMI 출력(미디어 창 + 터치 제어 창)을 지원한다.

## 주요 명령

### Pi에 배포 및 실행

```bash
# 파일을 Pi(192.168.0.60)에 SSH 업로드하고 앱 재시작
python deploy_pi.py

# 원격 앱 상태/로그 확인
python remote_check.py

# 원격 앱 실행 (이미 배포된 경우)
python remote_start_app.py
```

### Pi에서 직접 실행 (SSH 접속 후)

```bash
cd /home/karaoke/pi-karaoke
bash run.sh           # 정상 시작 (venv 사용, CPU 고정)
python main.py        # 직접 실행
tail -f /tmp/karaoke.log  # 로그 확인
```

### C 오디오 바이너리 빌드 (Pi에서)

```bash
cd audio
make karaoke_audio    # audio/karaoke_audio 생성 (없으면 engine.py가 자동 빌드)
```

### 개발 환경 설정

```bash
pip install -r requirements.txt
# requirements: sounddevice, numpy, yt-dlp, requests, beautifulsoup4
```

### 테스트

```bash
python -m pytest tests/
python tests/test_display_assignment.py
```

## 아키텍처

### 시작 흐름 (`main.py`)

1. `_pick_audio_devices()` — OS 감지 후 오디오 장치 결정
   - Linux: PipeWire Scarlett 정지 → ALSA dmix 생성 → `hw:N,0` 캡처
   - Windows: WASAPI Scarlett 자동 선택
2. `AudioEngine` 초기화 (에코/리버브 파라미터 포함)
3. `detect_monitors()` + `assign_displays()` — xrandr로 듀얼 모니터 감지
4. `configure_16_10_monitor()` — 미디어 모니터 16:10 해상도 강제
5. tkinter 루트 창 생성 (숨김), `ControlWindow` + `MediaWindow` 생성
6. 500ms 후 마이크 엔진 기본 ON

### 핵심 모듈

| 모듈 | 역할 |
|---|---|
| `core/app_state.py` | 두 GUI 창이 공유하는 전체 상태 (대기열, 현재 곡, 재생 상태). 스레드 안전한 lock + 리스너 패턴 |
| `core/playback.py` | `PlaybackManager` — 대기열 소진, mpv 조율, 곡 종료 콜백 처리 |
| `core/display.py` | xrandr 파싱, 모니터 할당, 해상도 설정 |
| `audio/engine.py` | `AudioEngine` — Linux에서는 C 바이너리(`audio/karaoke_audio`) subprocess, Windows에서는 PortAudio+numpy |
| `audio/dsp.py` | Python 구현 에코/리버브 (Windows 개발용) |
| `media/player.py` | `MpvPlayer` — mpv subprocess + Unix IPC 소켓(`/tmp/mpv-karaoke.sock`) |
| `media/yt_search.py` | `YTSearcher` — yt-dlp 비동기 YouTube 검색 |
| `gui/control_window.py` | HDMI1(오른쪽) 터치 제어 창 (1024×576) |
| `gui/media_window.py` | HDMI0(왼쪽) 미디어/대기열 표시 창 |
| `config.py` | `EchoParams` 데이터클래스, 샘플레이트/채널 상수 |

### 오디오 엔진 이중 구현

`audio/engine.py`는 `platform.system()`으로 분기:
- **Linux (Pi)**: `audio/karaoke_audio` C 바이너리를 subprocess로 구동. IPC는 stdin/stdout 라인 기반 (`START`, `STOP`, `PARAM key=val`, `READY`, `LEVEL in_rms out_rms`)
- **Windows**: sounddevice PortAudio 스트림 직접 사용

두 구현 모두 동일한 public API 제공: `start()`, `stop()`, `is_running`, `level_queue`, `status_queue`

### mpv 재생

`MpvPlayer`는 mpv 프로세스를 subprocess로 실행하고 Unix 소켓(`/tmp/mpv-karaoke.sock`)으로 제어한다. Pi에서는 H.264 720p + `v4l2m2m-copy` 하드웨어 디코딩, ALSA dmix 출력, CPU 코어 2,3 고정(`taskset`).

### 모니터 배치

- HDMI0 (왼쪽, X 좌표 작은 것): 미디어 창 — mpv 영상 + 대기열 표시
- HDMI1 (오른쪽, X 좌표 큰 것): 제어 창 (1024×576 터치스크린)
- 터치 입력은 `xinput map-to-output`으로 오른쪽 모니터에만 매핑

### 배포 구조

- `deploy_pi.py`: paramiko SSH로 `FILES_TO_SYNC` 파일들을 `192.168.0.60`에 업로드 후 `run.sh` 실행
- Pi 경로: `/home/karaoke/pi-karaoke/`, venv: `/home/karaoke/pi-karaoke/venv/`
- 로그: `/tmp/karaoke.log`

## 주요 제약

- `AppState._on_end()` 콜백은 백그라운드 스레드에서 호출됨 — tkinter GUI에 직접 접근 금지, `root.after()`로 스케줄해야 함
- PipeWire와 ALSA dmix 충돌: 마이크 엔진 시작 전 반드시 PipeWire Scarlett 장치를 suspend해야 함
- Pi에서 AV1/VP9 소프트웨어 디코딩은 CPU 과부하 → 항상 H.264 720p 강제
- C 바이너리 `audio/karaoke_audio`가 없으면 `AudioEngine.start()` 시 자동 빌드 시도 (`make`)
