# VeilSub live protocol

The browser and future mobile clients use one WebSocket protocol.

## Endpoint

`WS /v1/live`

The first frame is JSON:

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

After that, clients send binary PCM16 little-endian audio frames, targeting roughly 100 ms per frame.

## Session events

The gateway confirms startup only after the ASR provider has been initialized:

```json
{
  "type": "session.ready",
  "session_id": "..."
}
```

Provider or session failures are surfaced explicitly:

```json
{
  "type": "session.error",
  "code": "stream_failed",
  "message": "..."
}
```

Clients must not treat capture startup as successful until `session.ready` is received.

## Subtitle events

Example:

```json
{
  "type": "subtitle.final",
  "id": "google-12",
  "source": "そんなに見ないで",
  "target": null,
  "stability": 1.0,
  "is_final": true,
  "end_offset_ms": 1420
}
```

Event types:

- `subtitle.partial`: visible source text that is not yet stable enough for translation.
- `subtitle.stable`: stable interim text; M1 may attach a translation.
- `subtitle.final`: provider-finalized text for the logical segment.

## Segment replacement semantics

A logical utterance keeps the same `id` while Google revises its interim transcript.

Example:

```text
id=google-12  "そんな"
id=google-12  "そんなに見"
id=google-12  "そんなに見ないで"
id=google-12  "そんなに見ないで"  FINAL
id=google-13  "次の..."
```

Client rules:

1. if an event arrives with an ID already on screen, **replace** that segment;
2. `subtitle.final` closes that logical segment;
3. later speech receives a new segment ID;
4. one Google `StreamingRecognizeResponse` may contain multiple independent results;
   each result is emitted independently and keeps its own stability/finality;
5. `end_offset_ms` is the provider's result end offset from the current ASR stream and
   will also be used for future rollover deduplication.

## Design rules

- capture is platform-specific; protocol is shared;
- provider-specific objects never cross the gateway boundary;
- translation runs only for stable/final speech;
- provider responses are not flattened into a single subtitle;
- segment IDs are stable across interim revisions;
- reconnect/rollover must preserve replacement semantics and prevent duplicate subtitles.
