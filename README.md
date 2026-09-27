# VeilSub

**Live subtitles for anything you watch.**

VeilSub is a real-time subtitle layer for browser video. M0 captures the current browser tab's audio, streams it to a small gateway, transcribes it with Google Speech-to-Text V2 / Chirp 3, and renders source-language subtitles over the page.

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
      +--> Translation provider (disabled in M0)
      v
WebSocket subtitle events
      |
      v
Browser subtitle overlay
```

The gateway uses provider interfaces. Local development defaults to mock speech and no translation. M0 production speech uses Google Speech-to-Text V2 with the `chirp_3` model.

## Repository layout

```text
apps/extension/         Chrome/Edge MV3 extension
services/gateway/       FastAPI WebSocket gateway
docs/                   Protocol and architecture decisions
.github/workflows/       CI
```

## Quick start

### 1. Start the gateway in mock mode

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

With the default mock provider, the overlay emits synthetic source-language subtitles after it receives audio. This validates the browser-to-gateway path without cloud credentials.

## M0: Google Chirp 3 streaming

Install the Google provider extras:

```bash
cd services/gateway
pip install -e '.[dev,google]'
```

Enable the Speech-to-Text API for your Google Cloud project and authenticate with Application Default Credentials.

Set `services/gateway/.env`:

```env
VEILSUB_SPEECH_PROVIDER=google
VEILSUB_TRANSLATION_PROVIDER=none

GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us
GOOGLE_SPEECH_RECOGNIZER=_
GOOGLE_SPEECH_ENDPOINTING=short
```

Then run:

```bash
uvicorn app.main:app --reload --port 8000
```

Open a Japanese video, start VeilSub, and the source subtitle should appear as Google returns sufficiently stable interim/final results.

### Current M0 behavior

- input: PCM16, 16 kHz, mono;
- model: `chirp_3`;
- source language: `ja-JP` by default in the extension;
- interim results: enabled;
- automatic punctuation: enabled;
- profanity filtering: disabled;
- endpointing: `short` by default;
- each outbound Google audio request is capped below the API's per-message limit;
- translation is intentionally disabled until M1.

M0 does **not** yet implement seamless streaming rollover for long sessions. That belongs to M2.

## Initial milestones

- **M0 — It hears:** tab audio -> WebSocket -> Chirp 3 streaming ASR -> live Japanese subtitle.
- **M1 — It translates:** stable source segments -> NMT -> bilingual overlay.
- **M2 — It feels live:** stream rollover, reconnect, latency metrics, endpoint/stability tuning.
- **M3 — Mobile:** reuse the same gateway protocol from Android/iOS capture adapters.

## Status

M0 implementation is in place. Google credentials and a real Cloud project are required for end-to-end Chirp 3 validation.
