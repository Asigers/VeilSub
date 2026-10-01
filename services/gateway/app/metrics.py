import math
import time
from dataclasses import dataclass, field

from app.models import AudioConfig


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None

    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[index], 1)


@dataclass(slots=True)
class SessionMetrics:
    audio: AudioConfig
    first_audio_at: float | None = None
    first_subtitle_at: float | None = None
    audio_bytes: int = 0
    subtitle_revision_count: int = 0
    interim_latencies_ms: list[float] = field(default_factory=list)
    final_latencies_ms: list[float] = field(default_factory=list)
    translation_latencies_ms: list[float] = field(default_factory=list)
    translation_e2e_latencies_ms: list[float] = field(default_factory=list)
    reconnect_count: int = 0
    dropped_audio_ms: float = 0.0

    def record_audio(self, size: int) -> None:
        if size <= 0:
            return
        if self.first_audio_at is None:
            self.first_audio_at = time.monotonic()
        self.audio_bytes += size

    def record_subtitle(self, *, is_final: bool, end_offset_ms: int | None) -> None:
        now = time.monotonic()
        if self.first_subtitle_at is None:
            self.first_subtitle_at = now
        self.subtitle_revision_count += 1

        latency = self._stream_latency_ms(now, end_offset_ms)
        if latency is None:
            return
        if is_final:
            self.final_latencies_ms.append(latency)
        else:
            self.interim_latencies_ms.append(latency)

    def record_translation(
        self,
        *,
        provider_latency_ms: float,
        end_offset_ms: int | None,
    ) -> None:
        self.translation_latencies_ms.append(max(0.0, provider_latency_ms))
        e2e = self._stream_latency_ms(time.monotonic(), end_offset_ms)
        if e2e is not None:
            self.translation_e2e_latencies_ms.append(e2e)

    def update_client_stats(self, *, reconnect_count: int, dropped_audio_ms: float) -> None:
        self.reconnect_count = max(self.reconnect_count, reconnect_count)
        self.dropped_audio_ms = max(self.dropped_audio_ms, dropped_audio_ms)

    def summary(
        self,
        *,
        translation_calls: int,
        translation_characters: int,
        translation_cache_hits: int,
        translation_timeouts: int,
        translation_failures: int,
    ) -> dict[str, int | float | None]:
        bytes_per_second = (
            self.audio.sample_rate_hz * self.audio.channels * 2
        )
        estimated_asr_seconds = (
            self.audio_bytes / bytes_per_second if bytes_per_second else 0.0
        )

        first_subtitle_ms = None
        if self.first_audio_at is not None and self.first_subtitle_at is not None:
            first_subtitle_ms = round(
                (self.first_subtitle_at - self.first_audio_at) * 1000,
                1,
            )

        return {
            "time_to_first_subtitle_ms": first_subtitle_ms,
            "asr_interim_latency_ms_p50": _percentile(self.interim_latencies_ms, 0.50),
            "asr_interim_latency_ms_p95": _percentile(self.interim_latencies_ms, 0.95),
            "asr_final_latency_ms_p50": _percentile(self.final_latencies_ms, 0.50),
            "asr_final_latency_ms_p95": _percentile(self.final_latencies_ms, 0.95),
            "translation_latency_ms_p50": _percentile(
                self.translation_latencies_ms,
                0.50,
            ),
            "translation_latency_ms_p95": _percentile(
                self.translation_latencies_ms,
                0.95,
            ),
            "translation_e2e_latency_ms_p50": _percentile(
                self.translation_e2e_latencies_ms,
                0.50,
            ),
            "translation_e2e_latency_ms_p95": _percentile(
                self.translation_e2e_latencies_ms,
                0.95,
            ),
            "subtitle_revision_count": self.subtitle_revision_count,
            "reconnect_count": self.reconnect_count,
            "dropped_audio_ms": round(self.dropped_audio_ms, 1),
            "estimated_asr_seconds": round(estimated_asr_seconds, 3),
            "translation_calls": translation_calls,
            "translation_characters": translation_characters,
            "translation_cache_hits": translation_cache_hits,
            "translation_timeouts": translation_timeouts,
            "translation_failures": translation_failures,
        }

    def _stream_latency_ms(
        self,
        now: float,
        end_offset_ms: int | None,
    ) -> float | None:
        if self.first_audio_at is None or end_offset_ms is None:
            return None

        elapsed_ms = (now - self.first_audio_at) * 1000
        return round(max(0.0, elapsed_ms - end_offset_ms), 1)
