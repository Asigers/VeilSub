# VeilSub TODO

VeilSub now has a single production cloud stack:

- ASR: Alibaba Cloud Bailian `qwen-audio-3.0-asr-flash-streaming`
- Translation: Alibaba Cloud Machine Translation `TranslateGeneral`
- Development only: mock providers


## Current baseline

- [x] Chrome / Edge Manifest V3 extension
- [x] current-tab audio capture with `chrome.tabCapture`
- [x] offscreen document + AudioWorklet
- [x] PCM16 / 16 kHz / mono streaming over WebSocket
- [x] FastAPI gateway
- [x] Alibaba Qwen Audio Streaming provider
- [x] stable interim -> final segment IDs
- [x] truthful capture/session lifecycle state
- [x] captured-tab lifecycle tracking
- [x] basic source-language subtitle overlay
- [x] Alibaba Machine Translation adapter
- [x] mock providers for local development
- [x] CI: Python lint/tests + extension JavaScript syntax checks
- [ ] real Alibaba Cloud end-to-end validation with a Japanese video

---

# P0 — Finish M0 validation

## 1. Real Alibaba Cloud end-to-end validation

CI validates the provider adapter without using real credentials.

- [ ] create / select a Bailian workspace
- [ ] create a DashScope API key for the same region
- [ ] set `VEILSUB_SPEECH_PROVIDER=aliyun`
- [ ] play at least 20–30 minutes of Japanese video
- [ ] verify browser audio remains audible while capture is active
- [ ] verify interim/final Qwen ASR callbacks
- [ ] verify same-sentence interim updates keep one segment ID
- [ ] record time-to-first-subtitle and final-subtitle latency
- [ ] test silence, music, background noise, short utterances, overlapping voices
- [ ] confirm heartbeat prevents long-silence idle disconnects

---

# P1 — Reliability

**Implementation status:** core P1 reliability code is complete. Real-browser/cloud E2E validation is intentionally deferred.

## 2. Graceful stop / final-result flushing

The Gateway now treats user stop as a graceful half-close and waits for provider flush before acknowledging the stop.

- [x] stop accepting new browser audio first
- [x] call ASR `stop()`
- [x] drain the final callback/result
- [x] send `session.stopped` only after final results are delivered
- [x] distinguish user stop from provider/network failure
- [x] integration-test `session.ready -> final subtitle -> session.stopped` ordering

## 3. WebSocket reconnect and ASR recovery

- [x] handle browser WebSocket `error` and `close`
- [x] bounded exponential backoff
- [x] surface `reconnecting` state
- [x] rebuild the Bailian ASR session after reconnect
- [x] prevent duplicate subtitle segments
- [x] cap retry budget

Alibaba recommends heartbeat for silence and client-side reconnect for connection failures.

## 4. Browser audio backpressure

- [x] monitor `WebSocket.bufferedAmount`
- [x] bound queued client audio
- [x] prefer dropping stale audio over accumulating latency
- [x] expose dropped-audio metrics

## 5. Fullscreen subtitles

- [x] handle `fullscreenchange`
- [x] render overlay as a manual Popover in the browser top layer
- [x] refresh Popover top-layer order on fullscreen enter/exit
- [ ] E2E-test native HTML5 fullscreen and common custom players

## 6. Robust overlay injection

- [x] handle tabs opened before extension reload/install
- [x] dynamically inject overlay when content script is absent
- [x] isolate styles with Shadow DOM
- [x] support SPA navigation
- [x] remove stale overlay state cleanly

---

# M1 — Japanese -> Chinese translation

## 7. Enable Alibaba Machine Translation

The adapter already exists; product integration is still disabled by default.

- [ ] set `VEILSUB_TRANSLATION_PROVIDER=aliyun`
- [ ] configure RAM AccessKey credentials
- [ ] translate final Japanese segments to Simplified Chinese
- [ ] enforce translation timeout
- [ ] source subtitle must still render if translation fails
- [ ] verify `ja -> zh` on real colloquial media

## 8. Make translation asynchronous

`live.py` currently awaits translation inline.

- [ ] decouple ASR event consumption from translation calls
- [ ] add per-segment revision/version
- [ ] prevent stale translation response from replacing newer text
- [ ] cancel obsolete translation work

## 9. Deduplicate translation

- [ ] translate only changed/final text
- [ ] cache normalized source text
- [ ] collect translation calls and characters per session
- [ ] respect TranslateGeneral 5000-character per-request limit
- [ ] respect default QPS limits

## 10. Subtitle replacement and history

- [ ] replace current segment by stable `id`
- [ ] keep previous final subtitle while current sentence is spoken
- [ ] max line/character policy
- [ ] natural expiry
- [ ] source-only / bilingual / translated-only modes
- [ ] temporary history panel
- [ ] avoid visible flicker

---

# M2 — Quality and latency

## 11. Instrumentation

Track:

- [ ] time to first subtitle
- [ ] ASR interim latency
- [ ] ASR final latency
- [ ] translation latency
- [ ] end-to-end latency
- [ ] subtitle revision count
- [ ] reconnect count
- [ ] dropped-audio duration
- [ ] ASR seconds billed
- [ ] translation characters billed

## 12. Tune Qwen ASR for real media

Current choices:

- model: `qwen-audio-3.0-asr-flash-streaming`
- `semantic_punctuation_enabled=False` for lower-latency VAD segmentation
- `heartbeat=True`
- `language_hints=["ja"]`
- no sensitive-word filter

Validate before changing:

- [ ] `max_sentence_silence`
- [ ] `speech_noise_threshold`
- [ ] semantic segmentation
- [ ] music-heavy scenes
- [ ] very short Japanese utterances
- [ ] overlapping speakers
- [ ] informal / explicit language

## 13. Domain vocabulary

- [ ] collect a small private evaluation set
- [ ] measure false-speech / hallucination behavior
- [ ] add optional instant vocabulary / hotwords
- [ ] names and recurring terms
- [ ] explicit/informal Japanese vocabulary profile
- [ ] never enable system sensitive-word filtering by default

---

# Product UX

## 14. Extension controls

- [x] persistent Start / Stop state
- [x] basic connection/capture state
- [ ] ASR status
- [x] reconnecting state
- [ ] source language selector
- [ ] target language selector
- [ ] translated-only mode
- [ ] source subtitle toggle
- [ ] font size
- [ ] vertical position
- [ ] background opacity
- [ ] subtitle delay adjustment
- [ ] keyboard shortcut

## 15. Subtitle rendering

- [ ] draggable position
- [ ] safe-area handling
- [x] long-line wrapping
- [x] Japanese/Chinese font fallback
- [ ] high-DPI rendering
- [x] fullscreen support
- [ ] avoid covering player controls
- [ ] accessibility

---

# Production backend

## 16. Authentication / quotas / cost controls

Before exposing a hosted Gateway publicly:

- [ ] session authentication
- [ ] user/device quotas
- [ ] concurrent session limits
- [ ] per-minute audio limits
- [ ] rate limiting
- [ ] usage accounting
- [ ] provider-cost accounting
- [ ] sanitize provider error messages returned to clients

## 17. Deployment

- [ ] Dockerfile
- [ ] production ASGI config
- [ ] WSS / TLS
- [ ] secret management
- [ ] structured logging
- [ ] metrics
- [ ] readiness endpoint
- [ ] graceful shutdown
- [ ] autoscaling
- [ ] China-region deployment strategy
- [ ] cost monitoring

---

# Testing

## 18. Gateway integration tests

- [x] WebSocket session-start/ready test
- [ ] binary audio frame test
- [x] final subtitle event test
- [ ] ASR failure -> `session.error`
- [x] graceful stop/flush ordering test
- [ ] reconnect tests
- [x] Aliyun interim/final segment-ID tests
- [x] Aliyun `ja -> zh` translation adapter test

## 19. Browser extension tests

Current CI performs syntax checks only.

- [ ] manifest validation
- [ ] capture-state unit tests
- [ ] overlay replacement unit tests
- [ ] tab-switching tests
- [ ] browser E2E with deterministic audio
- [ ] fullscreen E2E
- [ ] disconnect/reconnect E2E

## 20. Optional real-cloud smoke test

- [ ] manually triggered GitHub Action
- [ ] use repository secrets for DashScope key/workspace
- [ ] send a short known Japanese audio fixture
- [ ] assert non-empty ASR output
- [ ] do not run on every push

---

# Mobile roadmap

## 21. Android

- [ ] native capture adapter
- [ ] AudioPlaybackCapture / MediaProjection validation
- [ ] reuse `/v1/live`
- [ ] floating subtitle UI
- [ ] lifecycle / battery / network testing

## 22. iOS / iPadOS

- [ ] real-device capture feasibility
- [ ] Safari extension + native app communication
- [ ] ScreenCaptureKit / ReplayKit constraint validation
- [ ] reuse `/v1/live` where possible

---

# Non-goals

- DRM bypass
- paywall bypass
- video downloading
- account scraping
- second cloud ASR provider

The project intentionally stays single-provider on the backend to keep maintenance cost low.
