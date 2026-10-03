# VeilSub

**Live subtitles for anything you watch.**

VeilSub is a browser-first real-time subtitle layer. The client captures the current tab's audio, streams PCM audio to a FastAPI gateway, transcribes it with Alibaba Cloud Model Studio (Bailian) Qwen Audio Streaming, and renders subtitles over the original page.

## Architecture

```text
Chrome / Edge
  tabCapture
      |
      | PCM16 16 kHz mono over WebSocket
      v
VeilSub Gateway (FastAPI)
      |
      +--> Alibaba Cloud Bailian
      |    qwen-audio-3.0-asr-flash-streaming
      |
      +--> subtitle segment state
      |
      +--> Alibaba Cloud Machine Translation
           TranslateGeneral (M1)
      v
subtitle events
      |
      v
browser overlay
```

VeilSub intentionally uses **one production cloud stack only**: Alibaba Cloud.

- ASR: Bailian / DashScope `qwen-audio-3.0-asr-flash-streaming`
- Translation: Alibaba Cloud Machine Translation `TranslateGeneral`
- Region for ASR: China (Beijing) by default
- Local development: mock ASR + no translation


## Repository layout

```text
apps/extension/         Chrome/Edge MV3 extension
services/gateway/       FastAPI WebSocket gateway
docs/                   protocol and architecture decisions
.github/workflows/      CI
```

## Quick start

### 1. Install the gateway

```bash
cd services/gateway
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

The default `.env.example` uses the mock speech provider.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 2. Load the extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select `apps/extension`.
5. Open a page that is playing audio.
6. Click VeilSub -> **Start subtitles**.

## Real-cloud validation (no mock)

See [真实阿里云端到端验证](docs/real-cloud-validation.md) for account activation,
least-privilege credentials, real Japanese audio smoke testing, browser acceptance checks,
and troubleshooting. From `services/gateway`, `python scripts/cloud_smoke.py --check-config`
performs an offline configuration check; live testing requires a real PCM16/16 kHz/mono
WAV and explicit `--allow-paid`. The script rejects mock providers and requires actual
final subtitles (and matching translations unless `--asr-only`) before reporting success.
A healthy Gateway alone does not prove cloud authentication or inference works.

## Real ASR with Alibaba Cloud Bailian

Create a Model Studio / Bailian API key and obtain the workspace ID for the same region.

Set `services/gateway/.env`:

```env
VEILSUB_SPEECH_PROVIDER=aliyun
VEILSUB_TRANSLATION_PROVIDER=none

DASHSCOPE_API_KEY=sk-...
ALIYUN_BAILIAN_WORKSPACE_ID=your-workspace-id
ALIYUN_BAILIAN_REGION=cn-beijing
ALIYUN_ASR_MODEL=qwen-audio-3.0-asr-flash-streaming
```

Then start the gateway:

```bash
uvicorn app.main:app --reload --port 8000
```

Current M0–M2 behavior:

- PCM16 / 16 kHz / mono input
- ~100 ms browser audio frames
- Japanese hint: `ja`
- interim text is displayed immediately
- final sentence keeps the same logical segment ID
- heartbeat is enabled for long silent periods
- sensitive-word filtering is not enabled
- graceful Stop waits for the final ASR flush and translations, with a bounded 35 s client fallback
- audio format is strictly validated; gateway startup/write/close/drain operations have timeouts
- capture tokens isolate late startup completions, PCM frames and messages from old sessions
- Gateway transport disconnects trigger at most 5 exponential-backoff reconnect attempts per capture
- explicit Gateway session errors are displayed and stop capture unless marked retryable; readiness does not reset retries
- audio is dropped instead of queued when disconnected or WebSocket backpressure exceeds 64 KiB
- dropped-audio duration is tracked in extension session state
- runtime content-script injection recovers tabs opened before an extension reload
- subtitle UI is isolated with Shadow DOM and uses a manual Popover for fullscreen top-layer rendering
- source final subtitles are emitted immediately; translation never blocks ASR
- translation updates use the same segment ID + revision and arrive asynchronously
- per-session translation cache, timeout, concurrency limit and QPS guard are implemented
- browser overlay keeps the previous final line plus the current segment
- display modes: bilingual / translation only / source only
- live controls for font size, vertical position, background opacity, and 0–3000 ms subtitle delay
- Start/Stop keyboard command: Ctrl+Shift+Y (macOS: Command+Shift+Y), remappable in Chrome extension shortcuts
- translation remains disabled unless `VEILSUB_TRANSLATION_PROVIDER=aliyun` is configured
- Stop returns structured latency/usage metrics and the extension keeps the latest session summary
- Qwen VAD/segmentation parameters are configurable without code changes
- instant hotwords and precompiled vocabulary IDs are supported

Official ASR docs:

- https://help.aliyun.com/zh/model-studio/qwen-audio-asr-streaming-python-sdk
- https://help.aliyun.com/zh/model-studio/qwen-audio-3-0-asr-flash-streaming

## M1 translation credentials

Alibaba Cloud Machine Translation uses AccessKey credentials separately from the Bailian API key.

```env
VEILSUB_TRANSLATION_PROVIDER=aliyun

ALIBABA_CLOUD_ACCESS_KEY_ID=
ALIBABA_CLOUD_ACCESS_KEY_SECRET=
ALIYUN_MT_ENDPOINT=mt.cn-hangzhou.aliyuncs.com
```

The adapter uses the general-purpose `TranslateGeneral` API.

Runtime defaults:

```env
VEILSUB_TRANSLATION_TIMEOUT_SECONDS=2.5
VEILSUB_TRANSLATION_MAX_CONCURRENCY=4
VEILSUB_TRANSLATION_MAX_QPS=20
VEILSUB_TRANSLATION_CACHE_SIZE=256
```

Final source subtitles are shown immediately. The translated text arrives as a later update, so a slow or failed translation does not block speech recognition.

Official docs:

- https://help.aliyun.com/zh/machine-translation/developer-reference/api-alimt-2018-10-12-translategeneral

## Milestones

- **M0 — It hears:** browser audio -> Alibaba Qwen Audio Streaming -> live Japanese subtitles.
- **M1 — It translates:** implemented in code; real-cloud translation validation remains.
- **M2 — It feels live:** latency instrumentation, subtitle UX, ASR tuning, and production hardening.
- **M3 — Mobile:** Android/iOS capture adapters reuse the same gateway protocol.

## Current status

The production provider is standardized on Alibaba Cloud. Core P1 reliability and M1 asynchronous translation are implemented; real-cloud validation remains intentionally deferred.


## SDK lifecycle compatibility

DashScope is pinned to `1.27.7`: its public `Recognition.stop()` uses an unbounded
thread join and has no public transport-abort API. VeilSub isolates a version-specific
bounded stop adapter to keep Gateway cleanup responsive and reject late results.
A stalled underlying SDK network thread may nevertheless survive and delay process exit;
this is not a guarantee of cloud transport cancellation. Upgrade the SDK only after
revalidating this adapter. Machine Translation uses the asynchronous SDK with HTTP timeouts.

## M2 metrics and ASR tuning

The extension keeps the latest completed session metrics, including TTFS, final-ASR latency P50/P95, translation latency P50/P95, translation end-to-end latency, subtitle revision count, reconnect count, dropped audio, estimated ASR audio seconds, and translation characters.

The ASR tuning defaults intentionally remain close to Alibaba Cloud defaults:

```env
ALIYUN_ASR_SEMANTIC_PUNCTUATION_ENABLED=false
ALIYUN_ASR_MAX_SENTENCE_SILENCE_MS=1300
ALIYUN_ASR_MULTI_THRESHOLD_MODE_ENABLED=false
ALIYUN_ASR_SPEECH_NOISE_THRESHOLD=

ALIYUN_ASR_VOCABULARY={}
ALIYUN_ASR_VOCABULARY_ID=
```

See `docs/asr-tuning.md` before changing these parameters. The project does not ship a hard-coded sensitive-content vocabulary; deployments can supply domain-specific hotwords through configuration.
