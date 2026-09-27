from app.models import SpeechResult
from app.subtitles import SubtitleStabilizer


def test_stability_policy() -> None:
    stabilizer = SubtitleStabilizer(0.75, 0.85)

    assert stabilizer.decide(SpeechResult(id="1", text="x", stability=0.4)).show is False
    assert stabilizer.decide(SpeechResult(id="2", text="x", stability=0.8)).translate is False
    assert stabilizer.decide(SpeechResult(id="3", text="x", stability=0.9)).translate is True

    final = stabilizer.decide(
        SpeechResult(id="4", text="x", stability=0.0, is_final=True)
    )
    assert final.show is True
    assert final.translate is True
    assert final.final is True
