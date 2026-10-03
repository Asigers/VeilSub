# VeilSub Android App Design

Status: implementation started
Target milestone: M3
Current implementation:
- A0 scaffold: complete in code and CI
- A1 playback capture: implemented in code; real-device validation pending
- A2 Gateway integration: next

Owner boundary: Android client only; reuse the existing VeilSub Gateway and WebSocket protocol.

## 1. Product goal

The Android app should let a user:

1. open VeilSub;
2. grant screen/audio capture consent;
3. optionally grant overlay permission;
4. switch to Chrome, Edge, a browser, or another media app;
5. play Japanese media;
6. see real-time Japanese / Chinese subtitles in a floating overlay;
7. stop capture from the overlay or persistent notification.

The Android app does not implement ASR or translation locally. It is a thin capture/render client for the existing VeilSub Gateway.

## 2. Platform baseline

- minSdk: 29 (Android 10)
- targetSdk: 36 (Android 16)
- compileSdk: 36
- language: Kotlin
- UI: Jetpack Compose
- build: Gradle Kotlin DSL
- architecture: single-activity + foreground capture service

Android 10 is the minimum because AudioPlaybackCapture was introduced in API 29.

## 3. Hard platform constraints

### Playback capture is conditional

AudioPlaybackCapture only receives audio from apps whose playback policy allows capture.

Capturable playback must use one of:

- AudioAttributes.USAGE_MEDIA
- AudioAttributes.USAGE_GAME
- AudioAttributes.USAGE_UNKNOWN

The source app must also allow playback capture. Android 10+ apps allow it by default unless the app or player opts out.

VeilSub must never attempt to bypass a source app that disables capture.

### User consent per capture session

The app obtains a MediaProjection token from MediaProjectionManager.createScreenCaptureIntent().

For apps targeting Android 14+, user consent must be obtained for every capture session. Do not persist/reuse a previous MediaProjection consent Intent or MediaProjection instance.

### Foreground service

Capture runs in a foreground service declared as:

- foregroundServiceType="mediaProjection"

Required manifest permissions include:

- android.permission.FOREGROUND_SERVICE
- android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION

The user initiates capture while the activity is visible. Do not rely on background service starts.

### Floating overlay

A cross-app subtitle overlay uses:

- android.permission.SYSTEM_ALERT_WINDOW
- WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY

This is a special permission and the user must explicitly enable "Display over other apps".

The app should still support an in-app subtitle preview when overlay permission is not granted.

## 4. High-level architecture

```text
┌──────────────────────────────────────┐
│              Android UI              │
│ Jetpack Compose / MainActivity       │
│                                      │
│ Start / Stop                         │
│ source / target language             │
│ display mode                         │
│ font / position / opacity / delay    │
│ connection / error / metrics         │
└──────────────────┬───────────────────┘
                   │
                   │ Intent / StateFlow
                   v
┌──────────────────────────────────────┐
│        SubtitleCaptureService        │
│ foregroundServiceType=mediaProjection│
│                                      │
│ MediaProjectionSession               │
│      ↓                               │
│ PlaybackAudioCapture                 │
│      ↓ PCM16 16kHz mono              │
│ GatewaySession                       │
│      ↓ WebSocket                     │
│ SubtitleStore                        │
│      ↓                               │
│ OverlayController                    │
└──────────────────┬───────────────────┘
                   │
                   │ WS /v1/live
                   v
┌──────────────────────────────────────┐
│         Existing VeilSub Gateway     │
│ Qwen ASR → Aliyun MT → metrics       │
└──────────────────────────────────────┘
```

## 5. Proposed repository structure

```text
apps/android/
├── app/
│   ├── build.gradle.kts
│   ├── proguard-rules.pro
│   └── src/main/
│       ├── AndroidManifest.xml
│       ├── java/com/veilsub/android/
│       │   ├── VeilSubApplication.kt
│       │   ├── MainActivity.kt
│       │   ├── ui/
│       │   │   ├── HomeScreen.kt
│       │   │   ├── SettingsScreen.kt
│       │   │   ├── PermissionScreen.kt
│       │   │   └── components/
│       │   ├── capture/
│       │   │   ├── SubtitleCaptureService.kt
│       │   │   ├── MediaProjectionSession.kt
│       │   │   ├── PlaybackAudioCapture.kt
│       │   │   └── PcmResampler.kt
│       │   ├── gateway/
│       │   │   ├── GatewayClient.kt
│       │   │   ├── GatewayProtocol.kt
│       │   │   ├── GatewayReconnectPolicy.kt
│       │   │   └── GatewayMetrics.kt
│       │   ├── subtitle/
│       │   │   ├── SubtitleStore.kt
│       │   │   ├── SubtitleSegment.kt
│       │   │   └── SubtitleRenderer.kt
│       │   ├── overlay/
│       │   │   ├── OverlayController.kt
│       │   │   ├── SubtitleOverlayView.kt
│       │   │   └── OverlayPositionStore.kt
│       │   ├── settings/
│       │   │   ├── UserSettings.kt
│       │   │   └── SettingsRepository.kt
│       │   └── notification/
│       │       └── CaptureNotification.kt
│       └── res/
├── build.gradle.kts
├── settings.gradle.kts
└── gradle.properties
```

Do not introduce a shared cross-platform framework yet. Android should speak the existing JSON/WebSocket protocol directly.

## 6. Capture flow

### Start flow

```text
HomeScreen
   ↓ Start
check Gateway config
   ↓
check overlay permission
   ↓
MediaProjectionManager.createScreenCaptureIntent()
   ↓
user accepts Android capture dialog
   ↓
startForegroundService()
   ↓
getMediaProjection()
   ↓
AudioPlaybackCaptureConfiguration
   ↓
AudioRecord
   ↓
PCM16
   ↓
Gateway WebSocket
   ↓
session.ready
   ↓
show overlay + switch state to Capturing
```

### Stop flow

```text
Stop button / notification / overlay close
   ↓
send client.stats
   ↓
send session.stop
   ↓
wait for session.stopped (bounded timeout)
   ↓
stop AudioRecord
   ↓
MediaProjection.stop()
   ↓
remove overlay
   ↓
stop foreground service
```

Register MediaProjection.Callback.onStop() and run the same cleanup path when Android revokes projection.

## 7. Audio capture

Use:

- MediaProjection
- AudioPlaybackCaptureConfiguration
- AudioRecord

Capture matching usages:

```kotlin
.addMatchingUsage(AudioAttributes.USAGE_MEDIA)
.addMatchingUsage(AudioAttributes.USAGE_GAME)
.addMatchingUsage(AudioAttributes.USAGE_UNKNOWN)
```

Initial audio target:

- PCM 16-bit
- mono
- 16 kHz
- little endian
- approximately 100 ms frames

Do not assume every device supports a native 16 kHz playback capture path.

### Resampling strategy

1. query / create AudioRecord with the most reliable supported capture rate;
2. if the captured rate is already 16 kHz mono PCM16, send directly;
3. otherwise convert to the Gateway contract in PcmResampler.

The first Android release should keep the Gateway protocol unchanged.

## 8. GatewaySession

The Android GatewayClient implements the same protocol as the browser extension.

Start message:

```json
{
  "type": "session.start",
  "source_language": "ja-JP",
  "target_language": "zh-CN",
  "audio": {
    "encoding": "linear16",
    "sample_rate_hz": 16000,
    "channels": 1
  }
}
```

Handle:

- session.ready
- session.error
- session.stopped
- subtitle.partial
- subtitle.final
- subtitle.translation

Implement the same semantics already used by the browser extension:

- stable segment ID replacement;
- revision ordering;
- discard stale translation revisions;
- bounded exponential-backoff reconnect;
- drop stale audio while disconnected;
- backpressure protection;
- send client.stats;
- keep latest metrics.

Suggested Android WebSocket implementation: OkHttp WebSocket.

## 9. SubtitleStore

Keep Android rendering logic independent from networking.

Model:

```kotlin
data class SubtitleSegment(
    val id: String,
    val revision: Int,
    val source: String,
    val target: String?,
    val isFinal: Boolean,
)
```

Rules:

- lower revision: ignore;
- same revision + translation: attach target;
- higher source revision: replace source and clear old target;
- keep max 50 recent segments in memory;
- render previous final + current segment;
- final subtitle expires after the same product-level timeout used on desktop.

## 10. Floating overlay

### Default presentation

One floating subtitle card:

```text
┌────────────────────────────┐
│ そんなに見ないで           │
│ 别一直盯着看               │
└────────────────────────────┘
```

Properties:

- transparent black rounded background;
- bilingual / translation-only / source-only;
- draggable vertically;
- horizontally centered by default;
- no focus stealing;
- touch passes through except while actively dragging / showing controls;
- survives switching between browser and other media apps.

### Window configuration

Use TYPE_APPLICATION_OVERLAY.

Recommended behavior:

- FLAG_NOT_FOCUSABLE
- keep overlay narrow enough not to block system navigation;
- drag gesture temporarily consumes touch;
- otherwise minimize interception.

### Overlay controls

Tap/long-press opens a compact control strip:

- pause/resume subtitles;
- close;
- source/translation display mode;
- font + / -;
- lock position.

Do not put full settings in the overlay.

## 11. Main UI

### Home screen

Primary state card:

```text
VeilSub

Gateway           Connected
Source            Japanese
Translation       Chinese
Overlay           Ready

[ Start live subtitles ]
```

When capturing:

```text
Listening…

ASR            Connected
Translation    Enabled
Dropped audio  0 ms
Reconnects     0

[ Stop ]
```

### Permissions section

Show explicit state for:

- MediaProjection: requested per Start, not persisted;
- Overlay permission: Granted / Required;
- Notifications permission where required by Android version.

Avoid requesting every permission on first launch. Request when the user starts the relevant feature.

### Settings

Reuse desktop concepts:

- Gateway URL
- source language
- target language
- display mode
- font size
- vertical position
- background opacity
- subtitle delay

Android-specific:

- overlay enabled
- keep screen awake: default off
- auto-hide overlay on stop
- reconnect retry count: not exposed in v1 UI

## 12. Foreground notification

While capture is active, show a persistent notification:

```text
VeilSub
Live subtitles are running
Japanese → Chinese

[ Stop ]
```

The notification is both user feedback and the control path when VeilSub's UI is not visible.

Do not hide or minimize the required capture notification.

## 13. State machine

```text
IDLE
 ↓
REQUESTING_PERMISSION
 ↓
STARTING_CAPTURE
 ↓
CONNECTING_GATEWAY
 ↓
CAPTURING
 ├── RECONNECTING
 │      └── CAPTURING
 ├── STOPPING
 │      └── IDLE
 └── ERROR
        └── IDLE / RETRY
```

Only report CAPTURING after:

1. MediaProjection is valid;
2. AudioRecord started;
3. Gateway returned session.ready.

## 14. Error taxonomy

Expose actionable errors:

### CAPTURE_NOT_ALLOWED

The source app does not expose capturable playback audio.

User message:
"This app does not allow its playback audio to be captured. VeilSub cannot override that Android restriction."

### PROJECTION_DENIED

User denied MediaProjection consent.

### OVERLAY_NOT_GRANTED

Audio subtitles can run, but floating subtitles cannot be displayed over other apps.

Offer:

- grant overlay permission;
- or use in-app preview.

### GATEWAY_UNREACHABLE

Reconnect automatically; show reconnecting status.

### AUDIO_CAPTURE_FAILED

AudioRecord initialization/read error.

### PROJECTION_REVOKED

Android/user stopped screen capture.

### PROVIDER_ERROR

Use sanitized Gateway message; do not expose cloud credentials/provider internals.

## 15. Security and privacy

- never embed DashScope or Alibaba Cloud credentials in the APK;
- Android app knows only the VeilSub Gateway URL;
- production Gateway must use WSS;
- do not persist MediaProjection result Intent;
- do not persist captured audio;
- do not log raw audio;
- redact authentication token / secrets from logs;
- store user settings in DataStore;
- authentication token should use encrypted platform storage when introduced.

## 16. Compatibility matrix

### Supported baseline

Android 10+.

### Expected best case

Apps whose audio playback uses media/game/unknown usages and allows AudioPlaybackCapture.

### Unsupported by design

- source app explicitly disables playback capture;
- DRM/protected path that does not expose capturable playback audio;
- attempts to bypass source-app restrictions.

### OEM testing

Before release, test at least:

- Pixel / AOSP-like Android;
- Samsung One UI;
- Xiaomi / HyperOS;
- OPPO/OnePlus/ColorOS;
- vivo/OriginOS where available.

OEM background and overlay behavior may differ; keep the foreground service visible and user-initiated.

## 17. Android 14–16 requirements

Design against modern restrictions from the beginning:

- ask for MediaProjection consent on every capture session;
- declare foregroundServiceType="mediaProjection";
- declare FOREGROUND_SERVICE_MEDIA_PROJECTION;
- start capture from visible user interaction;
- do not reuse MediaProjection tokens;
- do not start the projection service from BOOT_COMPLETED;
- register MediaProjection.Callback.onStop().

For Google Play in the current release window, target API 36.

## 18. Testing strategy

### Unit tests

- Gateway protocol parsing
- revision ordering
- stale translation rejection
- subtitle history
- reconnect backoff
- PCM conversion
- metrics
- settings validation

### Instrumented tests

- MediaProjection denial
- foreground service lifecycle
- notification Stop action
- overlay creation/removal
- app background/foreground transition

### Device E2E

Required before alpha:

1. Chrome playing a normal HTML5 Japanese video
2. Chromium-based browser
3. YouTube app if capture policy permits
4. a media app known to permit capture
5. source app that intentionally blocks capture
6. screen rotation
7. screen lock/unlock
8. Wi-Fi → cellular transition
9. Gateway temporary disconnect
10. 30+ minute playback

Do not claim universal app compatibility.

## 19. Implementation milestones

### A0 — Android scaffold

- Gradle project
- Compose activity
- settings repository
- state machine
- CI build
- minSdk 29 / targetSdk 36

Definition of done:
APK builds and launches on Android 10+ emulator/device.

### A1 — Playback capture

- MediaProjection consent
- mediaProjection foreground service
- AudioPlaybackCaptureConfiguration
- AudioRecord
- PCM framing
- local capture diagnostics

Definition of done:
capturable Chrome/media playback produces non-zero PCM while VeilSub is backgrounded.

### A2 — Gateway integration

- OkHttp WebSocket
- existing /v1/live protocol
- reconnect
- backpressure
- session metrics
- graceful stop

Definition of done:
Android playback audio produces source subtitles through the existing Gateway.

### A3 — Overlay subtitles

- SYSTEM_ALERT_WINDOW flow
- TYPE_APPLICATION_OVERLAY
- segment replacement
- bilingual rendering
- drag position
- notification Stop

Definition of done:
user can leave VeilSub, watch a supported app, and see floating live subtitles.

### A4 — Product UX

- appearance settings
- display modes
- errors / permission guidance
- metrics
- connection states
- accessibility

Definition of done:
normal user can complete setup without developer tools.

### A5 — Reliability

- rotation
- projection revoke
- network transition
- process/service lifecycle
- OEM tests
- 30+ minute run

Definition of done:
no silent capture failure and all failures are recoverable/actionable.

### A6 — Release

- app icon / package naming
- privacy disclosure
- Play Data Safety review
- signed release
- API 36
- crash reporting / production logs
- release checklist

## 20. Recommended implementation order

```text
A0 scaffold
  ↓
A1 capture PCM
  ↓
A2 existing Gateway
  ↓
A3 floating subtitles
  ↓
A4 product controls
  ↓
A5 device reliability
  ↓
A6 release
```

Do not start with the floating subtitle UI. Prove playback capture first; it is the platform-specific risk that decides whether the product works on a given source app.

## 21. Definition of Android alpha

Android alpha is complete only when:

- [ ] Android 10+ APK installs
- [ ] every Start requests fresh MediaProjection consent
- [ ] foreground mediaProjection service runs correctly
- [ ] supported app playback is captured as PCM
- [ ] existing Gateway produces Japanese subtitles
- [ ] translation update renders without blocking ASR
- [ ] floating overlay works over Chrome
- [ ] source-only / bilingual / translated-only modes work
- [ ] drag / font / opacity / delay settings work
- [ ] notification Stop works
- [ ] projection revoke cleans up
- [ ] disconnect/reconnect works
- [ ] unsupported playback-capture policy is explained clearly
- [ ] no cloud secret exists in the APK
- [ ] 30+ minute device test passes
