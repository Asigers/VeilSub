from dataclasses import dataclass

from app.models import SpeechResult


@dataclass(frozen=True, slots=True)
class SubtitleDecision:
    show: bool
    translate: bool
    final: bool


class SubtitleStabilizer:
    def __init__(self, partial_threshold: float = 0.75, translate_threshold: float = 0.85):
        if not 0 <= partial_threshold <= translate_threshold <= 1:
            raise ValueError("thresholds must satisfy 0 <= partial <= translate <= 1")
        self.partial_threshold = partial_threshold
        self.translate_threshold = translate_threshold

    def decide(self, result: SpeechResult) -> SubtitleDecision:
        if result.is_final:
            return SubtitleDecision(True, True, True)
        if result.stability >= self.translate_threshold:
            return SubtitleDecision(True, True, False)
        if result.stability >= self.partial_threshold:
            return SubtitleDecision(True, False, False)
        return SubtitleDecision(False, False, False)
