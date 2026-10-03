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

**Implementation status:** M1 code path is complete. Real Alibaba Cloud translation credentials / media validation are deferred with P0 validation.

## 7. Enable Alibaba Machine Translation

The adapter is integrated into the live pipeline but remains opt-in so local development can run without cloud credentials.

- [x] support `VEILSUB_TRANSLATION_PROVIDER=aliyun` in the live pipeline
- [ ] configure / validate real RAM AccessKey credentials
- [x] translate final Japanese segments to Simplified Chinese
- [x] enforce translation timeout
- [x] source subtitle renders before translation and survives translation failure
- [x] emit translation as a later update instead of blocking ASR
- [ ] verify `ja -> zh` on real colloquial media

## 8. Make translation asynchronous

`live.py` currently awaits translation inline.

- [x] decouple ASR event consumption from translation calls
- [x] add per-segment revision/version
- [x] prevent stale translation response from replacing newer text
- [x] cancel obsolete translation work

## 9. Deduplicate translation

- [x] translate only changed/final text
- [x] cache normalized source text
- [x] collect translation calls and characters per session
- [x] respect TranslateGeneral 5000-character per-request limit
- [x] respect default QPS limits

## 10. Subtitle replacement and history

- [x] replace current segment by stable `id`
- [x] keep previous final subtitle while current sentence is spoken
- [x] max visible segment policy (previous final + current)
- [ ] max character policy for exceptionally long sentences
- [x] natural expiry
- [x] source-only / bilingual / translated-only modes
- [x] bounded in-memory subtitle history (50 segments)
- [ ] user-visible history panel
- [x] avoid visible flicker

---

# M2 — Quality and latency

## 11. Instrumentation

**Implementation status:** session metrics are emitted on graceful stop and stored by the extension. ASR interim latency remains pending because Qwen interim sentences do not expose a reliable end offset.

Track:

- [x] time to first subtitle
- [ ] ASR interim latency
- [x] ASR final latency
- [x] translation latency
- [x] end-to-end translated-subtitle latency
- [x] subtitle revision count
- [x] reconnect count
- [x] dropped-audio duration
- [x] estimated ASR audio seconds (billing proxy; provider bill remains authoritative)
- [x] translation characters/calls/cache hits/timeouts/failures

## 12. Tune Qwen ASR for real media

**Implementation status:** tuning knobs are wired and validated; real-media parameter selection is intentionally still pending.

Current choices:

- model: `qwen-audio-3.0-asr-flash-streaming`
- `semantic_punctuation_enabled=False` for lower-latency VAD segmentation
- `heartbeat=True`
- `language_hints=["ja"]`
- no sensitive-word filter

Validate before changing:

- [x] `max_sentence_silence` is configurable and range-validated
- [x] `speech_noise_threshold` is optional and range-validated
- [x] semantic/VAD segmentation mode is configurable
- [ ] music-heavy scenes
- [ ] very short Japanese utterances
- [ ] overlapping speakers
- [ ] informal / explicit language

## 13. Domain vocabulary

- [ ] collect a small private evaluation set
- [ ] measure false-speech / hallucination behavior
- [x] add optional instant vocabulary / hotwords
- [x] names and recurring terms supported through instant/precompiled hotwords
- [ ] explicit/informal Japanese vocabulary profile
- [x] never enable system sensitive-word filtering by default

---

# Product UX

## 14. Extension controls

- [x] persistent Start / Stop state
- [x] basic connection/capture state
- [ ] ASR status
- [x] reconnecting state
- [x] source language selector
- [x] target language selector
- [x] translated-only mode
- [x] source subtitle toggle
- [x] font size
- [x] vertical position
- [x] background opacity
- [x] positive subtitle delay adjustment (0–3000 ms)
- [x] keyboard shortcut for Start/Stop (remappable via Chrome)

## 15. Subtitle rendering

- [ ] draggable position
- [x] safe-area handling
- [x] long-line wrapping
- [x] Japanese/Chinese font fallback
- [ ] high-DPI rendering
- [x] fullscreen support
- [ ] avoid covering player controls
- [x] basic live-region accessibility (`role=status`, `aria-live=polite`)

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
- [x] slow translation does not block the next ASR event
- [x] obsolete translation revision cannot overwrite a newer subtitle
- [x] translation cache / timeout unit tests
- [x] TranslateGeneral 5000-character limit test
- [x] graceful stop/flush ordering test
- [ ] reconnect tests
- [x] Aliyun interim/final segment-ID tests
- [x] Aliyun `ja -> zh` translation adapter test

## 19. Browser extension tests

Current CI performs syntax checks only.

- [x] manifest JSON validation
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

Detailed architecture: `docs/android-app-design.md`

### A0 — Scaffold
- [x] create `apps/android`
- [x] Kotlin + Jetpack Compose
- [x] minSdk 29 / targetSdk 36
- [x] Android CI build
- [x] DataStore settings + capture state machine

### A1 — Playback capture

**Code status:** capture pipeline is implemented and Android CI builds/tests it. Real-device playback-capture validation is still required before A1 is accepted.

- [x] MediaProjection permission flow
- [x] mediaProjection foreground service
- [x] AudioPlaybackCaptureConfiguration
- [x] AudioRecord playback capture
- [x] PCM16 / 16 kHz / mono conversion
- [x] MediaProjection.Callback cleanup
- [ ] distinguish / explain source apps that block playback capture on a real device
- [ ] verify non-zero PCM from Chrome or another capturable media app on a real Android 10+ device

### A2 — Gateway
- [ ] OkHttp WebSocket client
- [ ] reuse `/v1/live`
- [ ] revision-aware subtitle parsing
- [ ] reconnect / backpressure
- [ ] graceful stop / metrics

### A3 — Floating subtitles
- [ ] SYSTEM_ALERT_WINDOW permission flow
- [ ] TYPE_APPLICATION_OVERLAY
- [ ] bilingual segment renderer
- [ ] drag / lock position
- [ ] persistent foreground notification + Stop action

### A4 — Product UX
- [ ] source / target languages
- [ ] display modes
- [ ] font / position / opacity / delay
- [ ] permission guidance
- [ ] in-app preview fallback
- [ ] last-session metrics

### A5 — Reliability
- [ ] rotation / configuration changes
- [ ] projection revoke
- [ ] Wi-Fi / cellular transition
- [ ] background / foreground lifecycle
- [ ] OEM tests
- [ ] 30+ minute Android run

### A6 — Release
- [ ] WSS production Gateway
- [ ] no cloud credentials in APK
- [ ] signed release build
- [ ] Play Data Safety / privacy disclosures
- [ ] target API 36 release checklist

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
