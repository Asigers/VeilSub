from dataclasses import dataclass

from app.models import SpeechResult


@dataclass(frozen=True, slots=True)
class SubtitleDecision:
    show: bool
    translate: bool
    final: bool


class SubtitleStabilizer:
    """Provider-neutral subtitle policy.

    Aliyun Qwen Audio Streaming exposes interim/final sentence state rather
    than a numeric stability score. Interim text is shown immediately and
    translation is deferred until the provider marks the sentence final.
    """

    def decide(self, result: SpeechResult) -> SubtitleDecision:
        if result.is_final:
            return SubtitleDecision(show=True, translate=True, final=True)
        return SubtitleDecision(show=True, translate=False, final=False)
