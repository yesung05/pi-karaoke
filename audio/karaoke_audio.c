/*
 * karaoke_audio.c — Pi 4 카라오케 C 오디오 엔진
 *
 * ALSA 직접 접근(hw:N,0 캡처, scarlett_dmix 재생) + Echo + Freeverb 리버브
 * SCHED_FIFO 40 RT 스케줄링, 원자적 파라미터 업데이트
 *
 * IPC (stdin → 커맨드, stdout → 상태):
 *   stdin:  START | STOP | QUIT | PARAM key=val ...
 *   stdout: READY | LEVEL in_rms out_rms xruns | BYE
 *
 * 빌드: make -C audio karaoke_audio
 */

#define _GNU_SOURCE
#include <alsa/asoundlib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdint.h>
#include <time.h>

/* ── 오디오 포맷 상수 ───────────────────────────────────────── */
#define SAMPLE_RATE    48000
#define CHANNELS_IN    2   /* Scarlett Solo는 스테레오 캡처만 지원; 왼쪽 채널만 처리 */
#define CHANNELS_OUT   2
#define PERIOD_FRAMES  256
#define BUFFER_FRAMES  1024
#define INT32_SCALE    2147483647.0f

/* ── 원자적 float 헬퍼 (uint32 비트 재해석) ─────────────────── */
/* C11 _Atomic float는 표준이지만 GCC generic 매크로 충돌을 피하기 위해
   uint32 bitcast 방식으로 구현한다. */
typedef atomic_uint_fast32_t atomic_f32;

static inline void af32_store(atomic_f32 *a, float v) {
    uint32_t u;
    memcpy(&u, &v, 4);
    atomic_store_explicit(a, (uint_fast32_t)u, memory_order_relaxed);
}
static inline float af32_load(const atomic_f32 *a) {
    uint_fast32_t u = atomic_load_explicit((atomic_f32 *)a, memory_order_relaxed);
    float v;
    uint32_t u32 = (uint32_t)u;
    memcpy(&v, &u32, 4);
    return v;
}

/* ── Echo 딜레이 버퍼 ────────────────────────────────────────── */
#define ECHO_MAX_SAMP  96001

typedef struct {
    float      buf[ECHO_MAX_SAMP];
    int        write_pos;
    atomic_int delay_samp;
    atomic_f32 feedback;
    atomic_f32 wet;
    atomic_f32 volume;
} Echo;

static void echo_init(Echo *e, float delay_sec, float fb, float wet, float vol) {
    memset(e->buf, 0, sizeof(e->buf));
    e->write_pos = 0;
    int ds = (int)(delay_sec * SAMPLE_RATE);
    if (ds < 1)              ds = 1;
    if (ds >= ECHO_MAX_SAMP) ds = ECHO_MAX_SAMP - 1;
    atomic_store(&e->delay_samp, ds);
    af32_store(&e->feedback, fb);
    af32_store(&e->wet,      wet);
    af32_store(&e->volume,   vol);
}

static void echo_process(Echo *e, const float *in, float *out, int n) {
    int   delay = atomic_load_explicit(&e->delay_samp, memory_order_relaxed);
    float fb    = af32_load(&e->feedback);
    float wet   = af32_load(&e->wet);
    float vol   = af32_load(&e->volume);
    for (int i = 0; i < n; i++) {
        int   rp = (e->write_pos - delay + ECHO_MAX_SAMP) % ECHO_MAX_SAMP;
        float d  = e->buf[rp];
        float o  = (in[i] + wet * d) * vol;
        e->buf[e->write_pos] = in[i] + fb * d;
        e->write_pos = (e->write_pos + 1) % ECHO_MAX_SAMP;
        if (o >  1.0f) o =  1.0f;
        if (o < -1.0f) o = -1.0f;
        out[i] = o;
    }
}

/* ── Freeverb 리버브 ─────────────────────────────────────────── */
#define N_COMB    4
#define N_ALLPASS 2
#define AP_G      0.5f

static const int COMB_DELAYS_44K[]    = {1116, 1188, 1277, 1356};
static const int ALLPASS_DELAYS_44K[] = {556,  441};

typedef struct {
    float      *buf;
    int         size, pos;
    float       last;
    atomic_f32  feedback;
    atomic_f32  damp;
} Comb;

typedef struct {
    float *buf;
    int    size, pos;
} AP;

typedef struct {
    Comb       combs[N_COMB];
    AP         aps[N_ALLPASS];
    atomic_f32 wet;
} Reverb;

static int scale_delay(int d44k) {
    int d = (int)(d44k * (SAMPLE_RATE / 44100.0f));
    return d < 16 ? 16 : d;
}

static void reverb_init(Reverb *r, float room, float damp, float wet) {
    for (int i = 0; i < N_COMB; i++) {
        int sz = scale_delay(COMB_DELAYS_44K[i]);
        r->combs[i].buf  = calloc(sz, sizeof(float));
        r->combs[i].size = sz;
        r->combs[i].pos  = 0;
        r->combs[i].last = 0.0f;
        af32_store(&r->combs[i].feedback, room);
        af32_store(&r->combs[i].damp,     damp);
    }
    for (int i = 0; i < N_ALLPASS; i++) {
        int sz = scale_delay(ALLPASS_DELAYS_44K[i]);
        r->aps[i].buf  = calloc(sz, sizeof(float));
        r->aps[i].size = sz;
        r->aps[i].pos  = 0;
    }
    af32_store(&r->wet, wet);
}

static inline float comb_tick(Comb *c, float x) {
    float fb   = af32_load(&c->feedback);
    float damp = af32_load(&c->damp);
    float y    = c->buf[c->pos];
    c->last    = y * (1.0f - damp) + c->last * damp;
    c->buf[c->pos] = x + fb * c->last;
    c->pos = (c->pos + 1) % c->size;
    return y;
}

static inline float ap_tick(AP *a, float x) {
    float y = a->buf[a->pos];
    float v = x + AP_G * y;
    a->buf[a->pos] = v;
    a->pos = (a->pos + 1) % a->size;
    return y - AP_G * v;
}

static void reverb_process(Reverb *r, const float *in, float *out, int n) {
    float wet = af32_load(&r->wet);
    for (int i = 0; i < n; i++) {
        float x = in[i] * 0.015f;
        float y = 0.0f;
        for (int c = 0; c < N_COMB;    c++) y += comb_tick(&r->combs[c], x);
        for (int a = 0; a < N_ALLPASS; a++) y  = ap_tick(&r->aps[a], y);
        float o = in[i] + wet * y;
        if (o >  1.0f) o =  1.0f;
        if (o < -1.0f) o = -1.0f;
        out[i] = o;
    }
}

/* ── ALSA 헬퍼 ───────────────────────────────────────────────── */
static snd_pcm_t *open_pcm(const char *dev, snd_pcm_stream_t stream,
                            int ch, unsigned int rate,
                            snd_pcm_uframes_t period,
                            snd_pcm_uframes_t buffer) {
    snd_pcm_t        *h  = NULL;
    snd_pcm_hw_params_t *hw = NULL;

    if (snd_pcm_open(&h, dev, stream, 0) < 0) {
        fprintf(stderr, "ERROR open_pcm %s\n", dev);
        return NULL;
    }
    snd_pcm_hw_params_alloca(&hw);
    snd_pcm_hw_params_any(h, hw);
    snd_pcm_hw_params_set_access(h, hw, SND_PCM_ACCESS_RW_INTERLEAVED);
    snd_pcm_hw_params_set_format(h, hw, SND_PCM_FORMAT_S32_LE);
    snd_pcm_hw_params_set_channels(h, hw, (unsigned)ch);
    if (snd_pcm_hw_params_set_rate(h, hw, rate, 0) < 0) {
        fprintf(stderr, "ERROR set_rate %u on %s\n", rate, dev);
        snd_pcm_close(h); return NULL;
    }
    snd_pcm_hw_params_set_period_size_near(h, hw, &period, 0);
    snd_pcm_hw_params_set_buffer_size_near(h, hw, &buffer);
    if (snd_pcm_hw_params(h, hw) < 0) {
        fprintf(stderr, "ERROR hw_params %s\n", dev);
        snd_pcm_close(h); return NULL;
    }
    snd_pcm_prepare(h);
    return h;
}

/* ── 전역 상태 ───────────────────────────────────────────────── */
static Echo   g_echo;
static Reverb g_reverb;

static volatile int g_running = 0;
static volatile int g_quit    = 0;

static atomic_f32 g_in_rms;
static atomic_f32 g_out_rms;
static atomic_int g_xruns;

/* ── 파라미터 적용 ───────────────────────────────────────────── */
static void apply_param(const char *key, float val) {
    if (!strcmp(key, "delay_sec")) {
        int ds = (int)(val * SAMPLE_RATE);
        if (ds < 1)              ds = 1;
        if (ds >= ECHO_MAX_SAMP) ds = ECHO_MAX_SAMP - 1;
        atomic_store_explicit(&g_echo.delay_samp, ds, memory_order_relaxed);
    } else if (!strcmp(key, "feedback")) {
        af32_store(&g_echo.feedback, val);
    } else if (!strcmp(key, "wet")) {
        af32_store(&g_echo.wet, val);
    } else if (!strcmp(key, "volume")) {
        af32_store(&g_echo.volume, val);
    } else if (!strcmp(key, "reverb_room")) {
        for (int i = 0; i < N_COMB; i++)
            af32_store(&g_reverb.combs[i].feedback, val);
    } else if (!strcmp(key, "reverb_damp")) {
        for (int i = 0; i < N_COMB; i++)
            af32_store(&g_reverb.combs[i].damp, val);
    } else if (!strcmp(key, "reverb_wet")) {
        af32_store(&g_reverb.wet, val);
    }
}

/* ── 컨트롤 스레드 ───────────────────────────────────────────── */
static void *ctrl_thread(void *arg) {
    (void)arg;
    char line[512];
    while (!g_quit && fgets(line, sizeof(line), stdin)) {
        line[strcspn(line, "\r\n")] = 0;
        if      (!strcmp(line, "START")) { g_running = 1; }
        else if (!strcmp(line, "STOP"))  { g_running = 0; }
        else if (!strcmp(line, "QUIT"))  { g_quit = 1; break; }
        else if (!strncmp(line, "PARAM ", 6)) {
            char *p = line + 6;
            char key[32]; float val;
            while (sscanf(p, "%31[^=]=%f", key, &val) == 2) {
                apply_param(key, val);
                while (*p && *p != ' ') p++;
                while (*p == ' ') p++;
            }
        }
    }
    g_quit = 1;
    return NULL;
}

/* ── 레벨 출력 스레드 ────────────────────────────────────────── */
static void *level_thread(void *arg) {
    (void)arg;
    struct timespec ts = {0, 50000000L};
    while (!g_quit) {
        nanosleep(&ts, NULL);
        if (g_running) {
            printf("LEVEL %.6f %.6f %d\n",
                   af32_load(&g_in_rms),
                   af32_load(&g_out_rms),
                   atomic_load_explicit(&g_xruns, memory_order_relaxed));
            fflush(stdout);
        }
    }
    return NULL;
}

/* ── 메인 ────────────────────────────────────────────────────── */
int main(int argc, char **argv) {
    const char *cap_dev = (argc > 1) ? argv[1] : "hw:3,0";
    const char *pb_dev  = (argc > 2) ? argv[2] : "scarlett_dmix";

    af32_store(&g_in_rms,  0.0f);
    af32_store(&g_out_rms, 0.0f);
    atomic_store(&g_xruns, 0);

    echo_init(&g_echo, 0.20f, 0.45f, 0.40f, 1.00f);
    reverb_init(&g_reverb, 0.30f, 0.55f, 0.12f);

    snd_pcm_t *cap = open_pcm(cap_dev, SND_PCM_STREAM_CAPTURE,
                               CHANNELS_IN, SAMPLE_RATE,
                               PERIOD_FRAMES, BUFFER_FRAMES);
    if (!cap) { fprintf(stderr, "ERROR cap open fail\n"); return 1; }

    snd_pcm_t *pb = open_pcm(pb_dev, SND_PCM_STREAM_PLAYBACK,
                              CHANNELS_OUT, SAMPLE_RATE,
                              PERIOD_FRAMES, BUFFER_FRAMES);
    if (!pb) {
        fprintf(stderr, "ERROR pb open fail\n");
        snd_pcm_close(cap);
        return 1;
    }

    /* SCHED_FIFO 40 — 실패해도 계속 진행 (sudo 없이 실행 시 허용) */
    struct sched_param sp = {.sched_priority = 40};
    sched_setscheduler(0, SCHED_FIFO, &sp);

    pthread_t ctrl_tid, lvl_tid;
    pthread_create(&ctrl_tid, NULL, ctrl_thread,  NULL);
    pthread_create(&lvl_tid,  NULL, level_thread, NULL);

    printf("READY\n");
    fflush(stdout);

    int32_t cap_raw[PERIOD_FRAMES * CHANNELS_IN];  /* 2ch 스테레오 버퍼 */
    float   f_in[PERIOD_FRAMES];
    float   f_mid[PERIOD_FRAMES];
    float   f_out_buf[PERIOD_FRAMES];
    int32_t pb_raw[PERIOD_FRAMES * CHANNELS_OUT];

    int stopped_drain = 0;

    while (!g_quit) {
        if (!g_running) {
            if (!stopped_drain) {
                snd_pcm_drop(cap);  snd_pcm_prepare(cap);
                snd_pcm_drop(pb);   snd_pcm_prepare(pb);
                stopped_drain = 1;
            }
            struct timespec ts = {0, 10000000L};
            nanosleep(&ts, NULL);
            continue;
        }
        stopped_drain = 0;

        snd_pcm_sframes_t n = snd_pcm_readi(cap, cap_raw, PERIOD_FRAMES);
        if (n < 0) {
            snd_pcm_recover(cap, (int)n, 0);
            atomic_fetch_add_explicit(&g_xruns, 1, memory_order_relaxed);
            continue;
        }

        for (int i = 0; i < (int)n; i++)
            f_in[i] = (float)cap_raw[i * CHANNELS_IN] / INT32_SCALE;  /* 왼쪽 채널만 사용 */

        echo_process  (&g_echo,   f_in,  f_mid,    (int)n);
        reverb_process(&g_reverb, f_mid, f_out_buf, (int)n);

        float si = 0.0f, so = 0.0f;
        for (int i = 0; i < (int)n; i++) {
            si += f_in[i]      * f_in[i];
            so += f_out_buf[i] * f_out_buf[i];
        }
        af32_store(&g_in_rms,  sqrtf(si / (float)n));
        af32_store(&g_out_rms, sqrtf(so / (float)n));

        for (int i = 0; i < (int)n; i++) {
            float s = f_out_buf[i];
            if (s >  1.0f) s =  1.0f;
            if (s < -1.0f) s = -1.0f;
            int32_t v = (int32_t)(s * INT32_SCALE);
            pb_raw[i * 2]     = v;
            pb_raw[i * 2 + 1] = v;
        }

        snd_pcm_sframes_t w = snd_pcm_writei(pb, pb_raw, (snd_pcm_uframes_t)n);
        if (w < 0) {
            snd_pcm_recover(pb, (int)w, 0);
            atomic_fetch_add_explicit(&g_xruns, 1, memory_order_relaxed);
        }
    }

    snd_pcm_close(cap);
    snd_pcm_close(pb);
    printf("BYE\n");
    fflush(stdout);
    return 0;
}
