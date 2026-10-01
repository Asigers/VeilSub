import pytest

from app import metrics as metrics_module
from app.metrics import SessionMetrics
from app.models import AudioConfig


def test_session_metrics_summary(monkeypatch) -> None:
    times = iter([10.0, 11.5, 12.0, 12.2])
    monkeypatch.setattr(metrics_module.time, "monotonic", lambda: next(times))

    metrics = SessionMetrics(audio=AudioConfig())
    metrics.record_audio(32000)
    metrics.record_subtitle(is_final=False, end_offset_ms=1000)
    metrics.record_subtitle(is_final=True, end_offset_ms=1500)
    metrics.record_translation(provider_latency_ms=180.0, end_offset_ms=1500)
    metrics.update_client_stats(reconnect_count=2, dropped_audio_ms=350.0)

    summary = metrics.summary(
        translation_calls=3,
        translation_characters=42,
        translation_cache_hits=1,
        translation_timeouts=1,
        translation_failures=0,
    )

    assert summary["time_to_first_subtitle_ms"] == pytest.approx(1500.0)
    assert summary["asr_interim_latency_ms_p50"] == pytest.approx(500.0)
    assert summary["asr_final_latency_ms_p50"] == pytest.approx(500.0)
    assert summary["translation_latency_ms_p50"] == pytest.approx(180.0)
    assert summary["translation_e2e_latency_ms_p50"] == pytest.approx(700.0)
    assert summary["subtitle_revision_count"] == 2
    assert summary["reconnect_count"] == 2
    assert summary["dropped_audio_ms"] == pytest.approx(350.0)
    assert summary["estimated_asr_seconds"] == pytest.approx(1.0)
    assert summary["translation_characters"] == 42
