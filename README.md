# VeilSub

**Live subtitles for anything you watch.**

VeilSub is a real-time subtitle layer for browser video. The first milestone captures the current browser tab's audio, streams it to a small gateway, transcribes it, translates stable segments, and renders bilingual subtitles over the page.

## Architecture

```text
Chrome / Edge
  tabCapture
      |
      | PCM16 16 kHz mono over WebSocket
      v
VeilSub Gateway (FastAPI)
      |
      +--> Streaming ASR provider
      |
      +--> Subtitle stabilizer
      |
      +--> Translation provider
      v
WebSocket subtitle events
      |
      v
Browser subtitle overlay
```

The gateway uses provider interfaces. Local development defaults to mock providers so the end-to-end transport and overlay can be tested without cloud credentials. Production is intended to use Google Speech-to-Text V2 (Chirp 3) plus Google Cloud Translation NMT.

## Repository layout

```text
apps/extension/         Chrome/Edge MV3 extension
services/gateway/       FastAPI WebSocket gateway
docs/                   Protocol and architecture decisions
.github/workflows/       CI
```

## Quick start

### 1. Start the gateway

```bash
cd services/gateway
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e '.[dev]'
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

### 2. Load the extension

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select `apps/extension`.
5. Open a page that is playing audio and click the VeilSub extension.
6. Click **Start subtitles**.

With the default mock provider, the overlay will emit synthetic subtitles after it receives audio. This validates the browser-to-gateway path before cloud credentials are configured.

## Google provider

Set these variables in `services/gateway/.env`:

```env
VEILSUB_SPEECH_PROVIDER=google
VEILSUB_TRANSLATION_PROVIDER=google
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
GOOGLE_SPEECH_RECOGNIZER=_
```

Authenticate with Application Default Credentials. The Google speech adapter is intentionally isolated behind the provider interface so streaming rollover and provider replacement do not affect clients.

## Initial milestones

- **M0 — It hears:** tab audio -> WebSocket -> live source-language subtitle.
- **M1 — It translates:** stable source segments -> NMT -> bilingual overlay.
- **M2 — It feels live:** stability thresholds, endpoint tuning, stream rollover, reconnect and latency metrics.
- **M3 — Mobile:** reuse the same gateway protocol from Android/iOS capture adapters.

## Status

Early scaffold. The protocol and provider boundaries are intentionally small so product behavior can evolve without rewriting the clients.
