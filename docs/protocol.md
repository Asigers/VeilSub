# VeilSub live protocol

The browser and future mobile clients use one WebSocket protocol. Cloud-provider details never cross this boundary.

## Endpoint

`WS /v1/live`

First frame:

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

After that, clients send binary PCM16 little-endian audio frames, targeting about 100 ms per frame.

## Session events

```json
{
  "type": "session.ready",
  "session_id": "..."
}
```

```json
{
  "type": "session.error",
  "code": "stream_failed",
  "message": "..."
}
```

The client must not report capture success until `session.ready`.

## Subtitle events

Interim:

```json
{
  "type": "subtitle.partial",
  "id": "aliyun-12",
  "source": "そんなに見",
  "target": null,
  "is_final": false,
  "end_offset_ms": null
}
```

Final:

```json
{
  "type": "subtitle.final",
  "id": "aliyun-12",
  "source": "そんなに見ないで",
  "target": null,
  "is_final": true,
  "end_offset_ms": 1420
}
```

## Segment replacement semantics

Alibaba Qwen Audio Streaming returns interim updates for the current sentence and marks the sentence complete by returning a non-null `end_time`.

VeilSub maps that into stable IDs:

```text
id=aliyun-12  "そんな"
id=aliyun-12  "そんなに見"
id=aliyun-12  "そんなに見ないで"
id=aliyun-12  "そんなに見ないで" FINAL
id=aliyun-13  "次の..."
```

Rules:

1. same ID means replace the existing on-screen segment;
2. final closes the segment;
3. the next sentence gets a new ID;
4. interim subtitles are displayed immediately;
5. translation is attached only to final segments in the initial M1 design;
6. `end_offset_ms` comes from Aliyun's final sentence `end_time`.

## Design rules

- capture is platform-specific;
- the protocol is provider-agnostic;
- no numeric provider stability score is exposed;
- stable segment IDs are required for replacement and translation ordering;
- reconnect logic must avoid duplicating finalized segments.
