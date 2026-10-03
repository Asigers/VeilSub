# VeilSub Android

Native Android capture client for VeilSub.

Current implementation stage:

- A0 scaffold: implemented
- A1 playback-capture path: implemented in code, device validation pending
- A2 Gateway WebSocket integration: not implemented yet

## Requirements

- Android Studio compatible with AGP 8.13.x
- JDK 17
- Android SDK 36
- Android 10+ device/emulator (API 29+)

The project uses:

- Kotlin 2.3
- Jetpack Compose
- minSdk 29
- targetSdk / compileSdk 36
- MediaProjection
- AudioPlaybackCapture
- foregroundServiceType=mediaProjection

## Build

From the repository root:

```bash
gradle -p apps/android :app:testDebugUnitTest :app:assembleDebug
```

Or open `apps/android` in Android Studio.

## A1 device test

1. Install the debug APK on Android 10+.
2. Open VeilSub.
3. Tap **Start playback capture**.
4. Grant Record Audio and MediaProjection consent.
5. Switch to Chrome or another app that permits playback capture.
6. Play media audio.
7. Return to VeilSub and verify **16 kHz PCM captured** increases.

At A1 the PCM is deliberately not sent anywhere and is not persisted. A2 will feed the same PCM frames into the existing `/v1/live` Gateway protocol.

If the source app disables Android playback capture, VeilSub must not bypass that restriction.
