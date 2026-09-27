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

Server events:

```json
{"type":"session.ready","session_id":"..."}
```

```json
{
  "type":"subtitle.final",
  "id":"seg-1",
  "source":"そんなに見ないで",
  "target":"别一直盯着看",
  "stability":1.0,
  "is_final":true
}
```

Design rules:

- capture is platform-specific; protocol is shared;
- provider-specific objects never cross the gateway boundary;
- translation runs only for stable/final speech;
- segment IDs are replaceable so reconnect/rollover does not duplicate subtitles.
