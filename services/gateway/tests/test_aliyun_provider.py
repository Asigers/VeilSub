import asyncio

import pytest

from app.config import Settings
from app.providers.aliyun import AliyunSpeechStream, AliyunTranslator


class FakeRecognitionResult:
    def __init__(self, sentence):
        self._sentence = sentence

    def get_sentence(self):
        return self._sentence


class FakeTranslationData:
    def __init__(self, translated):
        self.translated = translated


class FakeTranslationBody:
    def __init__(self, translated):
        self.data = FakeTranslationData(translated)


class FakeTranslationResponse:
    def __init__(self, translated):
        self.body = FakeTranslationBody(translated)


class FakeTranslationClient:
    def __init__(self):
        self.last_request = None

    def translate_general(self, request):
        self.last_request = request
        return FakeTranslationResponse("别一直盯着看")


@pytest.mark.asyncio
async def test_interim_and_final_keep_same_segment_id() -> None:
    speech = AliyunSpeechStream(Settings())
    speech._loop = asyncio.get_running_loop()

    speech._handle_event(
        FakeRecognitionResult(
            {"text": "そんなに見", "begin_time": 0, "end_time": None}
        )
    )
    interim = await asyncio.wait_for(anext(speech.results()), timeout=1)

    speech._handle_event(
        FakeRecognitionResult(
            {"text": "そんなに見ないで", "begin_time": 0, "end_time": 1420}
        )
    )
    final = await asyncio.wait_for(anext(speech.results()), timeout=1)

    assert interim.id == final.id == "aliyun-1"
    assert interim.is_final is False
    assert interim.end_offset_ms is None
    assert final.is_final is True
    assert final.end_offset_ms == 1420


@pytest.mark.asyncio
async def test_new_sentence_gets_new_segment_id() -> None:
    speech = AliyunSpeechStream(Settings())
    speech._loop = asyncio.get_running_loop()

    speech._handle_event(
        FakeRecognitionResult({"text": "第一句", "begin_time": 0, "end_time": 800})
    )
    first = await asyncio.wait_for(anext(speech.results()), timeout=1)

    speech._handle_event(
        FakeRecognitionResult({"text": "第二句", "begin_time": 900, "end_time": None})
    )
    second = await asyncio.wait_for(anext(speech.results()), timeout=1)

    assert first.id == "aliyun-1"
    assert second.id == "aliyun-2"


@pytest.mark.asyncio
async def test_translation_uses_ja_to_zh_codes() -> None:
    settings = Settings(
        alibaba_cloud_access_key_id="id",
        alibaba_cloud_access_key_secret="secret",
    )
    translator = AliyunTranslator(settings)
    fake_client = FakeTranslationClient()
    translator._client = fake_client

    translated = await translator.translate(
        "そんなに見ないで",
        source_language="ja-JP",
        target_language="zh-CN",
    )

    assert translated == "别一直盯着看"
    assert fake_client.last_request.source_language == "ja"
    assert fake_client.last_request.target_language == "zh"
    assert fake_client.last_request.scene == "general"


@pytest.mark.asyncio
async def test_translation_rejects_over_5000_characters() -> None:
    settings = Settings(
        alibaba_cloud_access_key_id="id",
        alibaba_cloud_access_key_secret="secret",
    )
    translator = AliyunTranslator(settings)

    with pytest.raises(ValueError, match="5000"):
        await translator.translate(
            "あ" * 5001,
            source_language="ja-JP",
            target_language="zh-CN",
        )



@pytest.mark.asyncio
async def test_asr_tuning_and_hotwords_are_forwarded(monkeypatch) -> None:
    captured = {}

    class FakeRecognition:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def start(self):
            return None

        def stop(self):
            return None

    monkeypatch.setattr("app.providers.aliyun.asr.Recognition", FakeRecognition)

    settings = Settings(
        dashscope_api_key="key",
        aliyun_bailian_workspace_id="workspace",
        aliyun_asr_semantic_punctuation_enabled=False,
        aliyun_asr_max_sentence_silence_ms=900,
        aliyun_asr_multi_threshold_mode_enabled=True,
        aliyun_asr_speech_noise_threshold=0.2,
        aliyun_asr_vocabulary_id="vocab-123",
        aliyun_asr_vocabulary={"山田": 4},
    )
    speech = AliyunSpeechStream(settings)

    from app.models import AudioConfig

    await speech.start(language="ja-JP", audio=AudioConfig())

    assert captured["language_hints"] == ["ja"]
    assert captured["semantic_punctuation_enabled"] is False
    assert captured["max_sentence_silence"] == 900
    assert captured["multi_threshold_mode_enabled"] is True
    assert captured["speech_noise_threshold"] == pytest.approx(0.2)
    assert captured["vocabulary_id"] == "vocab-123"
    assert captured["vocabulary"] == {"山田": 4}
    assert captured["heartbeat"] is True

    await speech.close()
