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

There is no Google provider or Google SDK dependency in this repository.

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

Current M0 behavior:

- PCM16 / 16 kHz / mono input
- ~100 ms browser audio frames
- Japanese hint: `ja`
- interim text is displayed immediately
- final sentence keeps the same logical segment ID
- heartbeat is enabled for long silent periods
- sensitive-word filtering is not enabled
- translation is disabled until M1

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

Official docs:

- https://help.aliyun.com/zh/machine-translation/developer-reference/api-alimt-2018-10-12-translategeneral

## Milestones

- **M0 — It hears:** browser audio -> Alibaba Qwen Audio Streaming -> live Japanese subtitles.
- **M1 — It translates:** final/stable source segments -> Alibaba NMT -> bilingual subtitles.
- **M2 — It feels live:** reconnect, backpressure, latency metrics, fullscreen, long-session hardening.
- **M3 — Mobile:** Android/iOS capture adapters reuse the same gateway protocol.

## Current status

The production provider has been standardized on Alibaba Cloud. The next required validation is a real 20–30 minute Japanese-video session using a real Bailian workspace.
