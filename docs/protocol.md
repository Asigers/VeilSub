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

A normal client stop is acknowledged only after ASR final-result flushing and pending translation work:

```json
{
  "type": "session.stopped",
  "metrics": {
    "time_to_first_subtitle_ms": 640.2,
    "asr_interim_latency_ms_p50": null,
    "asr_interim_latency_ms_p95": null,
    "asr_final_latency_ms_p50": 410.0,
    "asr_final_latency_ms_p95": 780.4,
    "translation_latency_ms_p50": 92.3,
    "translation_latency_ms_p95": 180.8,
    "translation_e2e_latency_ms_p50": 520.1,
    "translation_e2e_latency_ms_p95": 930.5,
    "subtitle_revision_count": 38,
    "reconnect_count": 0,
    "dropped_audio_ms": 0.0,
    "estimated_asr_seconds": 61.2,
    "translation_calls": 14,
    "translation_characters": 184,
    "translation_cache_hits": 2,
    "translation_timeouts": 0,
    "translation_failures": 0
  }
}
```

The client must not report capture success until `session.ready`, and should wait for
`session.stopped` (with a short timeout fallback) before closing a normal session.

## Subtitle events

Every subtitle event contains a logical segment `id` and a monotonically increasing
`revision` for that segment.

### Interim source

```json
{
  "type": "subtitle.partial",
  "id": "<session-id>:aliyun-12",
  "revision": 2,
  "source": "そんなに見",
  "target": null,
  "is_final": false,
  "end_offset_ms": null
}
```

### Final source

The final source text is sent immediately. Translation never blocks this event.

```json
{
  "type": "subtitle.final",
  "id": "<session-id>:aliyun-12",
  "revision": 3,
  "source": "そんなに見ないで",
  "target": null,
  "is_final": true,
  "end_offset_ms": 1420
}
```

### Translation update

Translation is performed asynchronously and arrives later as an update to the same segment
and same source revision:

```json
{
  "type": "subtitle.translation",
  "id": "<session-id>:aliyun-12",
  "revision": 3,
  "source": "そんなに見ないで",
  "target": "别一直盯着看",
  "is_final": true,
  "end_offset_ms": 1420
}
```

If translation times out or fails, no translation event is emitted; the source subtitle remains valid.

## Replacement and ordering semantics

Alibaba Qwen Audio Streaming returns interim updates for the current sentence and marks the sentence complete by returning a non-null `end_time`.

VeilSub maps that into:

```text
id=<session>:aliyun-12 rev=1  "そんな"
id=<session>:aliyun-12 rev=2  "そんなに見"
id=<session>:aliyun-12 rev=3  "そんなに見ないで" FINAL

# async translation, same source revision
id=<session>:aliyun-12 rev=3  target="别一直盯着看"

id=<session>:aliyun-13 rev=1  "次の..."
```

Client rules:

1. same `id` means update the existing segment;
2. higher `revision` replaces lower source revisions;
3. a lower revision must never overwrite a newer segment state;
4. `subtitle.translation` is accepted only when its revision matches the current source revision;
5. final closes the source segment;
6. the next sentence gets a new ID;
7. the Gateway session ID prefixes provider segment IDs, preventing ID reuse after reconnect;
8. `end_offset_ms` comes from Aliyun's final sentence `end_time`.

## Translation runtime

For each Gateway session:

- source final events are sent before translation starts;
- translation work runs outside the ASR result loop;
- WebSocket writes are serialized with one send lock;
- obsolete translation tasks for the same segment are cancelled;
- stale translation results are discarded by revision;
- calls are concurrency-limited and QPS-limited;
- repeated normalized source text is cached per session;
- translation has a bounded timeout;
- provider translation errors do not terminate the ASR session.

## Design rules

- capture is platform-specific;
- the protocol is provider-agnostic;
- stable IDs and revisions are required for replacement and translation ordering;
- reconnect logic must avoid duplicating finalized segments;
- live latency is more important than replaying stale buffered audio.


## Metrics semantics

The metrics object is diagnostic, not a cloud billing statement.

- `time_to_first_subtitle_ms`: first subtitle event minus first audio frame received by the Gateway.
- ASR final latency: Gateway stream elapsed time minus Aliyun final sentence `end_time`.
- ASR interim latency currently remains null because Qwen interim sentences do not provide a reliable end offset.
- translation latency: time spent inside the translation provider call.
- translation end-to-end latency: Gateway stream elapsed time minus the source sentence end offset when translated text is ready.
- `estimated_asr_seconds`: PCM duration received by the Gateway; use provider billing reports for authoritative billing.
- reconnect/drop metrics originate from the browser client and are sent through `client.stats`.
