import asyncio

import pytest
from google.cloud.speech_v2.types import cloud_speech
from google.protobuf.duration_pb2 import Duration

from app.config import Settings
from app.models import AudioConfig
from app.providers.google import GoogleSpeechStream


class FakeTransport:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeSpeechClient:
    def __init__(self) -> None:
        self.transport = FakeTransport()
        self.config_request = None
        self.audio_request = None

    async def streaming_recognize(self, requests):
        self.config_request = await anext(requests)

        async def responses():
            self.audio_request = await anext(requests)
            yield cloud_speech.StreamingRecognizeResponse(
                results=[
                    cloud_speech.StreamingRecognitionResult(
                        alternatives=[
                            cloud_speech.SpeechRecognitionAlternative(
                                transcript="こんにちは"
                            )
                        ],
                        stability=0.92,
                        is_final=False,
                        result_end_offset=Duration(seconds=1, nanos=250_000_000),
                    )
                ]
            )

        return responses()


def provider_result(
    text: str,
    *,
    stability: float,
    is_final: bool = False,
    end_ms: int = 0,
):
    seconds, millis = divmod(end_ms, 1000)
    return cloud_speech.StreamingRecognitionResult(
        alternatives=[
            cloud_speech.SpeechRecognitionAlternative(transcript=text)
        ],
        stability=stability,
        is_final=is_final,
        result_end_offset=Duration(
            seconds=seconds,
            nanos=millis * 1_000_000,
        ),
    )


@pytest.mark.asyncio
async def test_chirp3_stream_emits_interim_result(monkeypatch) -> None:
    settings = Settings(
        google_cloud_project="veilsub-test",
        google_cloud_location="us",
        google_speech_endpointing="short",
    )
    speech = GoogleSpeechStream(settings)
    fake_client = FakeSpeechClient()
    monkeypatch.setattr(speech, "_create_client", lambda: fake_client)

    await speech.start(language="ja-JP", audio=AudioConfig())
    await speech.write(b"\x00\x00" * 1600)

    result = await asyncio.wait_for(anext(speech.results()), timeout=1)

    assert result.text == "こんにちは"
    assert result.stability == pytest.approx(0.92)
    assert result.is_final is False
    assert result.end_offset_ms == 1250

    config_request = fake_client.config_request
    assert config_request.recognizer == "projects/veilsub-test/locations/us/recognizers/_"
    assert config_request.streaming_config.config.model == "chirp_3"
    assert config_request.streaming_config.config.language_codes == ["ja-JP"]
    assert config_request.streaming_config.streaming_features.interim_results is True
    assert fake_client.audio_request.audio == b"\x00\x00" * 1600

    await speech.close()
    assert fake_client.transport.closed is True


def test_multi_result_response_keeps_independent_stability() -> None:
    speech = GoogleSpeechStream(Settings(google_cloud_project="veilsub-test"))

    results = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[
                provider_result("安定した前半", stability=0.95, end_ms=1200),
                provider_result("まだ不安定", stability=0.32, end_ms=1800),
            ]
        )
    )

    assert [result.text for result in results] == ["安定した前半", "まだ不安定"]
    assert results[0].stability == pytest.approx(0.95)
    assert results[1].stability == pytest.approx(0.32)
    assert results[0].id != results[1].id


def test_interim_revisions_keep_same_segment_id_until_final() -> None:
    speech = GoogleSpeechStream(Settings(google_cloud_project="veilsub-test"))

    first = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[provider_result("そんな", stability=0.60, end_ms=500)]
        )
    )[0]
    second = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[provider_result("そんなに見", stability=0.82, end_ms=900)]
        )
    )[0]
    final = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[
                provider_result(
                    "そんなに見ないで",
                    stability=0.0,
                    is_final=True,
                    end_ms=1400,
                )
            ]
        )
    )[0]
    next_segment = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[provider_result("次の文", stability=0.70, end_ms=1900)]
        )
    )[0]

    assert first.id == second.id == final.id
    assert final.is_final is True
    assert final.stability == 1.0
    assert final.end_offset_ms == 1400
    assert next_segment.id != final.id


def test_final_plus_interim_keeps_result_boundaries() -> None:
    speech = GoogleSpeechStream(Settings(google_cloud_project="veilsub-test"))

    current = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[provider_result("第一文", stability=0.80, end_ms=800)]
        )
    )[0]

    results = speech._convert_response(
        cloud_speech.StreamingRecognizeResponse(
            results=[
                provider_result(
                    "第一文です",
                    stability=0.0,
                    is_final=True,
                    end_ms=1000,
                ),
                provider_result("第二", stability=0.40, end_ms=1300),
            ]
        )
    )

    assert len(results) == 2
    assert results[0].id == current.id
    assert results[0].is_final is True
    assert results[1].id != current.id
    assert results[1].is_final is False


@pytest.mark.asyncio
async def test_audio_is_split_below_google_message_limit() -> None:
    settings = Settings(google_cloud_project="veilsub-test")
    speech = GoogleSpeechStream(settings)
    speech._started = True

    payload = b"x" * 30_001
    await speech.write(payload)

    chunks = [
        await speech._audio_queue.get(),
        await speech._audio_queue.get(),
        await speech._audio_queue.get(),
    ]
    assert sum(len(chunk) for chunk in chunks if chunk is not None) == len(payload)
    assert all(chunk is not None and len(chunk) <= 14_000 for chunk in chunks)
