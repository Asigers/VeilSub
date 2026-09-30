# VeilSub TODO

This file tracks both:

1. code-review findings in the current implementation; and
2. product capabilities that still need to be completed.

Priority convention:

- **P0** — correctness or core-path issue; fix before treating VeilSub as a usable alpha.
- **P1** — important reliability / UX work.
- **P2** — product hardening and expansion.

---

## Current baseline

Already implemented:

- [x] Chrome / Edge Manifest V3 extension
- [x] current-tab audio capture with `chrome.tabCapture`
- [x] offscreen document + AudioWorklet
- [x] PCM16 / 16 kHz / mono streaming over WebSocket
- [x] FastAPI gateway
- [x] Google Speech-to-Text V2 / Chirp 3 streaming adapter
- [x] interim / final ASR result flow
- [x] basic subtitle stability policy
- [x] independent Google result parsing + stable segment IDs
- [x] truthful capture/session lifecycle state
- [x] captured-tab lifecycle tracking
- [x] source-language subtitle overlay
- [x] mock speech provider for local development
- [x] CI: Python lint/tests + extension JavaScript syntax checks
- [ ] real Google Cloud end-to-end validation with a real Japanese video

M0 currently means **real-time source-language subtitles**. Translation is intentionally disabled by default.

---

# P0 — Correctness / core-path fixes

**Code status:** P0 code fixes are complete and CI is green. The only remaining P0 item is real-cloud / real-media M0 validation.

## 1. Fix Google streaming-result segmentation

**Previous problem (fixed):** `GoogleSpeechStream._convert_response()` concatenates every
`StreamingRecognitionResult` in one Google response and assigns the minimum stability to
the whole combined string.

Google explicitly allows one streaming response to contain multiple consecutive results,
for example a high-stability prefix followed by a low-stability suffix. With the current
implementation, a stable prefix can therefore be hidden because the unstable suffix lowers
the combined stability.

References:

- https://docs.cloud.google.com/python/docs/reference/speech/latest/google.cloud.speech_v2.types.StreamingRecognizeResponse
- https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v2/StreamingRecognitionResult

Tasks:

- [x] process each Google `StreamingRecognitionResult` independently
- [x] preserve each result's own `is_final`, `stability`, and `result_end_offset`
- [x] do not merge a final result and following interim result into one subtitle event
- [x] add tests for a response containing:
  - one high-stability interim result + one low-stability interim result
  - one final result + one interim result
- [x] ensure a stable prefix can be shown even while the next phrase is unstable

---

## 2. Make subtitle segment IDs stable

**Previous problem (fixed):** every Google response gets a new ID such as `google-1`,
`google-2`, etc. An evolving interim transcript is therefore treated as a new segment on
every update.

Desired behavior:

```text
google segment A:
そんな
↓
そんなに見
↓
そんなに見ないで
↓
FINAL
```

The same logical segment should keep the same ID until it becomes final.

Tasks:

- [x] introduce a segment / utterance state machine
- [x] keep one ID across interim revisions of the same segment
- [x] increment the logical segment only after finalization
- [x] include timing metadata such as `result_end_offset` in the internal model
- [x] define replacement semantics in `docs/protocol.md`

This is required before subtitle history and M1 translation are implemented.

---

## 3. Fix capture-start acknowledgement

**Previous problem (fixed):** `background.js` reports `capture.start` as successful after it sends a
message to the offscreen document. It does **not** wait for:

- `getUserMedia()` to succeed;
- the WebSocket to connect;
- the gateway to accept the session;
- `session.ready` to arrive.

An offscreen error is currently only printed with `console.error`, while the popup can show
"Capturing current tab".

Tasks:

- [x] add explicit capture lifecycle states:
  - `idle`
  - `starting`
  - `capturing`
  - `reconnecting`
  - `error`
- [x] make the offscreen document acknowledge startup success/failure
- [x] only report success after gateway `session.ready`
- [x] surface WebSocket / ASR errors to the popup and overlay
- [x] persist current state so reopening the popup shows the real session state

---

## 4. Track the actual captured tab

**Previous problem (fixed):** `stopCapture()` hides the overlay on the *currently active tab*, not
necessarily the tab that originally started VeilSub.

Example:

```text
start on tab A
switch to tab B
click Stop
=> capture stops, but tab A's overlay may remain visible
```

The same issue can appear when starting a new capture while an old capture is active.

Tasks:

- [x] store `capturedTabId`
- [x] always hide / clean up the overlay on the captured tab
- [x] stop the previous session before switching capture to another tab
- [x] handle captured-tab close / navigation / replacement
- [x] consider `chrome.tabCapture.onStatusChanged` as the source of capture truth

Reference:

- https://developer.chrome.com/docs/extensions/reference/api/tabCapture

---

## 5. Real M0 end-to-end validation

CI validates the adapter without calling the real Google service. Before M0 is considered
finished:

- [ ] configure a real Google Cloud project and ADC
- [ ] play at least 20–30 minutes of Japanese video
- [ ] verify browser audio remains audible while capture is active
- [ ] verify real Chirp 3 interim / final responses
- [ ] verify no obvious audio-speed or sample-rate distortion
- [ ] record first-subtitle latency and final-subtitle latency
- [ ] test silence, music, background noise, and short Japanese utterances
- [x] document any required Chrome / Edge minimum version

---

# P1 — Reliability and subtitle behavior

## 6. Implement seamless Google stream rollover

Google StreamingRecognize streams can remain open for up to roughly five minutes.

Reference:

- https://docs.cloud.google.com/speech-to-text/docs/quotas

Tasks:

- [ ] rotate the Google stream before the hard limit
- [ ] overlap a short audio window between old/new streams
- [ ] deduplicate rollover results
- [ ] keep subtitle IDs monotonic across rollover
- [ ] make rollover invisible to the browser client
- [ ] test 30+ minute playback

---

## 7. Fix graceful shutdown / final-result flushing

**Previous problem (fixed):** the gateway uses `asyncio.FIRST_COMPLETED`. When the client sends
`session.stop`, the audio receiver can finish first and the result pump is cancelled before
the speech stream is closed and flushed. A final recognition result may therefore be lost.

Tasks:

- [ ] on normal stop: stop accepting audio first
- [ ] close / half-close the speech stream
- [ ] continue draining final ASR results
- [ ] only then close the WebSocket session
- [ ] distinguish graceful stop from disconnect / provider failure

---

## 8. Add WebSocket reconnect and failure recovery

Current extension behavior has no reconnect strategy.

Tasks:

- [ ] handle WebSocket `error` and `close`
- [ ] reconnect with bounded exponential backoff
- [ ] expose `reconnecting` state to UI
- [ ] stop capture after a maximum retry budget
- [ ] define whether audio during reconnect is dropped or briefly buffered
- [ ] prevent duplicate sessions after reconnect

---

## 9. Add audio backpressure

The gateway has a bounded speech queue, but the browser currently calls `socket.send()`
without observing `WebSocket.bufferedAmount`.

If the gateway / network becomes slow, browser-side buffered audio can grow.

Tasks:

- [ ] monitor `WebSocket.bufferedAmount`
- [ ] define a bounded client audio buffer
- [ ] choose a policy for overload:
  - drop oldest audio, or
  - drop newest audio, or
  - pause / reduce sending
- [ ] emit metrics for dropped audio
- [ ] ensure stale audio is never replayed many seconds late

For live subtitles, dropping stale audio is generally preferable to accumulating large delay.

---

## 10. Handle fullscreen correctly

The overlay is currently appended to the document root. Browser fullscreen can put the video
element in the top layer, causing an external overlay to disappear.

Tasks:

- [ ] listen for `fullscreenchange`
- [ ] mount / move the subtitle overlay into the fullscreen element when needed
- [ ] restore it when fullscreen exits
- [ ] test native HTML5 video fullscreen
- [ ] test common custom players

---

## 11. Make overlay injection robust

Current content scripts rely on static `content_scripts` injection.

Tasks:

- [ ] handle tabs that were already open when the extension was installed / reloaded
- [ ] dynamically inject the overlay when the content script is missing
- [ ] use Shadow DOM or equivalent isolation to reduce CSS conflicts
- [ ] cleanly remove overlay state on stop
- [ ] support SPA navigation

---

# M1 — Real-time Japanese -> Chinese translation

## 12. Connect Google Cloud Translation NMT

- [ ] enable `VEILSUB_TRANSLATION_PROVIDER=google`
- [ ] translate Japanese stable/final segments to Simplified Chinese
- [ ] verify target language handling instead of blindly stripping all BCP-47 region tags
- [ ] add translation timeout and error fallback
- [ ] show source subtitle even when translation temporarily fails

---

## 13. Do not block the ASR result pump on translation

**Current future-risk:** `live.py` awaits translation inline inside `pump_results()`.
Once real NMT is enabled, translation latency will block consumption of newer ASR events.

Tasks:

- [ ] decouple ASR event consumption from translation calls
- [ ] run translation per stable segment asynchronously
- [ ] cancel / supersede stale translation when the source text changes
- [ ] prevent an older translation response from overwriting a newer subtitle revision
- [ ] add per-segment revision numbers

---

## 14. Deduplicate translation calls

A stable interim segment can be revised several times.

Tasks:

- [ ] only translate when text actually changes
- [ ] cache translation by normalized source text
- [ ] avoid translating every high-stability interim response
- [ ] always translate the final revision if it differs from the last translated revision
- [ ] collect translation calls/session as a cost metric

---

## 15. Build proper subtitle replacement / history

The current overlay only displays the latest event.

Tasks:

- [ ] current-segment replacement using stable segment IDs
- [ ] keep the previous final line while the current line is being spoken
- [ ] define max lines / characters on screen
- [ ] natural subtitle expiry
- [ ] source-only / bilingual / translated-only display modes
- [ ] temporary subtitle history panel
- [ ] avoid visible flicker when partial text changes

---

# M2 — Make it feel live

## 16. Latency instrumentation

Track at least:

- [ ] time to first subtitle
- [ ] audio-capture -> ASR interim latency
- [ ] audio-capture -> ASR final latency
- [ ] translation latency
- [ ] end-to-end subtitle latency
- [ ] subtitle revision count
- [ ] reconnect count
- [ ] dropped-audio duration

Do not optimize thresholds until these measurements exist.

---

## 17. Tune stability and endpointing using real media

Current defaults:

```text
partial threshold:   0.75
translate threshold: 0.85
endpointing:         short
```

These are starting parameters, not proven product defaults.

Tasks:

- [ ] tune against real Japanese dialogue
- [ ] test very short utterances
- [ ] test overlapping voices
- [ ] test long pauses
- [ ] test music-heavy media
- [ ] test explicit / informal conversational media
- [ ] optimize for perceived subtitle latency, not just WER

---

## 18. Improve difficult / explicit Japanese recognition

The original target scenario has audio that can contain silence, music, breath sounds,
non-speech vocalization, slang, names, and very short phrases.

Tasks:

- [ ] collect a small private evaluation set
- [ ] measure hallucination / false-speech behavior
- [ ] add Chirp 3 speech adaptation / phrase hints where useful
- [ ] maintain an optional explicit/informal Japanese phrase profile
- [ ] add names / domain glossary support
- [ ] evaluate whether additional VAD / non-speech filtering is actually needed
- [ ] never silently sanitize explicit vocabulary

Do not add a second ASR model until the Chirp 3 baseline has been measured.

---

# Product UX

## 19. Extension state and controls

- [x] persistent Start / Stop state
- [x] basic connection / capture-state indicator
- [ ] ASR status
- [ ] reconnecting / error status
- [ ] source language selector
- [ ] target language selector
- [ ] translated-only mode
- [ ] source subtitle toggle
- [ ] subtitle font size
- [ ] vertical position
- [ ] background opacity
- [ ] subtitle delay adjustment
- [ ] keyboard shortcut

---

## 20. Better subtitle rendering

- [ ] draggable position
- [ ] safe-area handling
- [ ] responsive mobile-like browser windows
- [ ] long-line wrapping
- [ ] Japanese / Chinese font fallback
- [ ] high-DPI rendering
- [ ] fullscreen rendering
- [ ] avoid obscuring player controls
- [ ] accessibility considerations

---

# Production backend

## 21. Authentication and abuse prevention

The current WebSocket endpoint accepts anyone who can reach it. This is acceptable for local
development and **not acceptable for a public hosted service**.

Before public deployment:

- [ ] session authentication
- [ ] user / anonymous-device quotas
- [ ] concurrent-session limits
- [ ] per-minute audio limits
- [ ] rate limiting
- [ ] abuse detection
- [ ] billing / usage accounting
- [ ] do not expose raw provider error details to untrusted clients

---

## 22. Deployment

- [ ] Dockerfile
- [ ] production ASGI configuration
- [ ] WSS / TLS
- [ ] environment / secret management
- [ ] structured logs
- [ ] metrics
- [ ] health + readiness endpoints
- [ ] graceful shutdown
- [ ] autoscaling strategy
- [ ] regional deployment strategy
- [ ] cost monitoring

---

# Testing

## 23. Gateway integration tests

- [ ] WebSocket session-start test
- [ ] binary audio frame test
- [ ] subtitle event test
- [ ] provider failure -> `session.error` test
- [ ] graceful stop test
- [ ] reconnect / rollover tests
- [x] multi-result Google response tests

---

## 24. Browser extension tests

Current CI only performs JavaScript syntax checking.

Add:

- [ ] manifest validation
- [ ] unit tests for capture state
- [ ] unit tests for overlay replacement
- [ ] unit tests for tab switching
- [ ] browser E2E test using a deterministic audio fixture
- [ ] fullscreen E2E test
- [ ] WebSocket disconnect test

---

## 25. Optional real-cloud smoke test

Keep normal CI credential-free, but allow an explicitly triggered test using repository
secrets:

- [ ] send a short known Japanese audio fixture to real Chirp 3
- [ ] assert non-empty recognition
- [ ] never run this on every push
- [ ] cap cost and execution frequency

---

# Mobile roadmap

## 26. Android

- [ ] native capture adapter
- [ ] AudioPlaybackCapture / MediaProjection feasibility validation
- [ ] reuse `/v1/live` protocol
- [ ] floating subtitle UI
- [ ] background / foreground lifecycle
- [ ] battery and network behavior

---

## 27. iOS / iPadOS

- [ ] validate feasible audio-capture path on real devices
- [ ] validate Safari extension + native app communication
- [ ] validate ScreenCaptureKit / ReplayKit constraints for the required scenario
- [ ] reuse `/v1/live` protocol where possible
- [ ] define fallback when system policy prevents capture

Do not promise universal iOS capture until this is verified on-device.

---

# Non-goals for now

Keep the project focused on real-time subtitles.

- [ ] do **not** add DRM bypass
- [ ] do **not** add paywall bypass
- [ ] do **not** add video downloading
- [ ] do **not** add account scraping
- [ ] do **not** add a second ASR model before the primary pipeline is measured

---

# Suggested implementation order

```text
P0
1. Real M0 cloud validation  <- remaining
2. Correct Google multi-result parsing  [done]
3. Stable subtitle segment IDs  [done]
4. Accurate capture/session state  [done]
5. Correct captured-tab lifecycle  [done]

P1 core reliability
6. Graceful stop
7. 5-minute rollover
8. WebSocket reconnect
9. Backpressure
10. Fullscreen overlay

M1
11. Google NMT
12. Async translation pipeline
13. Translation deduplication
14. Subtitle replacement/history

M2
15. Latency metrics
16. Real-world stability tuning
17. Explicit/informal Japanese recognition improvements
18. UI polish

Production
19. Authentication / quota / billing
20. Deployment / observability

Expansion
21. Android
22. iOS / iPadOS
```

## Alpha definition of done

VeilSub should not be called a usable alpha until all of the following are true:

- [ ] a user can start subtitles and receive truthful connection state
- [ ] a Japanese video produces stable source subtitles
- [ ] Japanese -> Chinese translation works
- [ ] the same utterance updates instead of duplicating
- [ ] 30+ minute playback works without subtitle interruption
- [ ] temporary network failure can recover
- [ ] fullscreen works
- [ ] failures are visible and recoverable
- [ ] basic latency and cost metrics are observable
