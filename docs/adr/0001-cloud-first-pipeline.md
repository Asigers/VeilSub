# ADR 0001: Cloud-first subtitle pipeline

Status: accepted

## Decision

VeilSub uses:

```text
platform capture adapter
        ->
VeilSub WebSocket gateway
        ->
streaming ASR
        ->
subtitle stabilizer
        ->
NMT
        ->
subtitle events
```

The first production provider pair is Google Speech-to-Text V2 / Chirp 3 and Google Cloud Translation NMT. Provider implementations remain isolated behind internal interfaces.

The browser client sends PCM16 16 kHz mono audio. The gateway owns cloud credentials, provider configuration, session state, translation triggering, retries, and future stream rollover.

## Consequences

- clients remain thin;
- no model installation is required on user devices;
- gateway cost controls and reconnect logic are production requirements;
- providers can be replaced without changing browser/mobile clients.
