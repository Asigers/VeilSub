# ADR 0001: Alibaba Cloud single-provider pipeline

Status: accepted

## Decision

VeilSub uses one production cloud stack:

```text
platform capture adapter
        ->
VeilSub WebSocket gateway
        ->
Alibaba Cloud Bailian
qwen-audio-3.0-asr-flash-streaming
        ->
subtitle segment state
        ->
Alibaba Cloud Machine Translation
TranslateGeneral
        ->
subtitle events
```

The browser sends PCM16 16 kHz mono audio to the Gateway. The Gateway owns all cloud credentials and provider lifecycle.

The project deliberately keeps a single production cloud provider to avoid duplicate configuration, tests, SDK upgrades, provider-specific semantics, and operational paths.

## ASR choices

- Model: `qwen-audio-3.0-asr-flash-streaming`
- Default region: `cn-beijing`
- SDK: DashScope Python SDK
- Audio format: PCM / 16 kHz / mono
- Language hint: Japanese (`ja`)
- Segmentation: VAD, `semantic_punctuation_enabled=False`
- Heartbeat: enabled
- Sensitive-word filtering: not configured, therefore disabled for the real-time model

Aliyun returns one sentence object per callback. `end_time != None` means that sentence is final. VeilSub keeps the same logical segment ID from interim revisions through finalization.

## Translation choices

Alibaba Cloud Machine Translation `TranslateGeneral` is the only planned production translation backend.

Translation is intentionally disabled in M0 and enabled in M1 after the ASR path is validated.

## Consequences

- one cloud vendor to configure and monitor;
- no cross-provider behavior normalization;
- Bailian API key/workspace and Machine Translation AccessKey credentials remain separate;
- browser/mobile clients remain provider-agnostic because they only speak VeilSub's WebSocket protocol.
