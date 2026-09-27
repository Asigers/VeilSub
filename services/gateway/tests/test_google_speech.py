import asyncio

import pytest
from google.cloud.speech_v2.types import cloud_speech

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
                    )
                ]
            )

        return responses()


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

    config_request = fake_client.config_request
    assert config_request.recognizer == "projects/veilsub-test/locations/us/recognizers/_"
    assert config_request.streaming_config.config.model == "chirp_3"
    assert config_request.streaming_config.config.language_codes == ["ja-JP"]
    assert config_request.streaming_config.streaming_features.interim_results is True
    assert fake_client.audio_request.audio == b"\x00\x00" * 1600

    await speech.close()
    assert fake_client.transport.closed is True


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
