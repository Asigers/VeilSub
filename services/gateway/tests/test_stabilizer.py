from app.models import SpeechResult
from app.subtitles import SubtitleStabilizer


def test_interim_is_shown_without_translation() -> None:
    decision = SubtitleStabilizer().decide(
        SpeechResult(id="1", text="そんなに見", is_final=False)
    )
    assert decision.show is True
    assert decision.translate is False
    assert decision.final is False


def test_final_is_shown_and_translated() -> None:
    decision = SubtitleStabilizer().decide(
        SpeechResult(id="1", text="そんなに見ないで", is_final=True)
    )
    assert decision.show is True
    assert decision.translate is True
    assert decision.final is True
