# Qwen ASR tuning

VeilSub keeps production defaults conservative until they are measured against real media.

## Current defaults

```env
ALIYUN_ASR_SEMANTIC_PUNCTUATION_ENABLED=false
ALIYUN_ASR_MAX_SENTENCE_SILENCE_MS=1300
ALIYUN_ASR_MULTI_THRESHOLD_MODE_ENABLED=false
ALIYUN_ASR_SPEECH_NOISE_THRESHOLD=
ALIYUN_ASR_VOCABULARY={}
ALIYUN_ASR_VOCABULARY_ID=
```

These map directly to Alibaba Cloud Qwen Audio Streaming parameters.

## Segmentation

`semantic_punctuation_enabled=false` keeps VAD segmentation enabled. Alibaba documents VAD segmentation as the lower-latency choice for interactive scenarios.

`max_sentence_silence` controls how much trailing silence closes a sentence. Supported range: 200–6000 ms. VeilSub retains the provider default of 1300 ms until real measurements justify changing it.

`multi_threshold_mode_enabled` may help prevent overly long VAD segments. It only applies while semantic segmentation is disabled.

## Noise threshold

`speech_noise_threshold` accepts -1.0 to 1.0.

- lower values: more sensitive, but noise is more likely to become text;
- higher values: stricter filtering, but quiet speech may be lost.

Leave it unset until an evaluation set shows a repeatable noise problem. Change it in small steps.

## Hotwords

Two mechanisms are supported:

### Instant hotwords

Set a JSON object:

```env
ALIYUN_ASR_VOCABULARY={"山田":4,"VeilSub":5}
```

Weights may be 1–5 or 50. Weight 50 is a super-hotword and is deliberately constrained by VeilSub to Alibaba's documented limits.

Use this for session/domain vocabulary such as names, recurring terms, slang, titles, or specialized vocabulary.

### Precompiled vocabulary

```env
ALIYUN_ASR_VOCABULARY_ID=vocab-...
```

Use this when the vocabulary is stable and reused across sessions.

## Evaluation rule

Do not tune against a single clip. Compare the same private evaluation set and record:

- time to first subtitle;
- ASR final latency P50/P95;
- subtitle revision count;
- missing short utterances;
- false speech during music/noise;
- proper-name/domain-term accuracy;
- translation latency and end-to-end translated-subtitle latency.

Only change one major ASR parameter at a time.
