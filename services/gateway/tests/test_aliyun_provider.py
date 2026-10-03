import asyncio

import pytest

from app.config import Settings
from app.providers.aliyun import AliyunSpeechStream, AliyunTranslator, _asr_websocket_url


@pytest.mark.parametrize("workspace,region,expected_host", [
    ("ws-example.cn", "cn-beijing", "ws-example.cn-beijing.maas.aliyuncs.com"),
    ("ws-example", "cn-beijing", "ws-example.cn-beijing.maas.aliyuncs.com"),
    ("workspace", "ap-southeast-1", "workspace.ap-southeast-1.maas.aliyuncs.com"),
])
def test_workspace_endpoint_has_one_workspace_dns_label(workspace, region, expected_host):
    settings = Settings(_env_file=None, aliyun_bailian_workspace_id=workspace,
                        aliyun_bailian_region=region)
    assert _asr_websocket_url(settings) == f"wss://{expected_host}/api-ws/v1/inference"
    assert settings.aliyun_bailian_workspace_id == workspace


@pytest.mark.parametrize("workspace,region", [
    ("ws-example.cn", "ap-southeast-1"),
    ("https://example.com", "cn-beijing"),
    ("ws-example.invalid", "cn-beijing"),
])
def test_wrong_region_or_hostname_is_rejected(workspace, region):
    settings = Settings(_env_file=None, aliyun_bailian_workspace_id=workspace,
                        aliyun_bailian_region=region)
    with pytest.raises(ValueError):
        _asr_websocket_url(settings)


class FakeRecognitionResult:
    def __init__(self, sentence):
        self._sentence = sentence

    def get_sentence(self):
        return self._sentence


class FakeTranslationData:
    def __init__(self, translated):
        self.translated = translated


class FakeTranslationBody:
    def __init__(self, translated, code=200):
        self.code = code
        self.data = FakeTranslationData(translated)


class FakeTranslationResponse:
    def __init__(self, translated, code=200):
        self.body = FakeTranslationBody(translated, code)


class FakeTranslationClient:
    def __init__(self, code=200):
        self.last_request = None
        self.code = code

    async def translate_general_with_options_async(self, request, runtime):
        assert runtime.connect_timeout == 3000
        assert runtime.read_timeout == 5000
        assert runtime.autoretry is False
        self.last_request = request
        return FakeTranslationResponse("别一直盯着看", self.code)


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


@pytest.mark.parametrize("success_code", [200, "200"])
@pytest.mark.asyncio
async def test_translation_uses_ja_to_zh_codes(success_code) -> None:
    settings = Settings(
        alibaba_cloud_access_key_id="id",
        alibaba_cloud_access_key_secret="secret",
    )
    translator = AliyunTranslator(settings)
    fake_client = FakeTranslationClient(success_code)
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
async def test_translation_preserves_business_error_without_data() -> None:
    from types import SimpleNamespace

    class ErrorClient:
        async def translate_general_with_options_async(self, request, runtime):
            return SimpleNamespace(body=SimpleNamespace(
                code=10010, message="Service is not activated", request_id="test-request", data=None,
            ))

    translator = AliyunTranslator(Settings(
        _env_file=None, alibaba_cloud_access_key_id="test-id",
        alibaba_cloud_access_key_secret="test-secret",
    ))
    translator._client = ErrorClient()
    with pytest.raises(RuntimeError, match="10010.*Service is not activated.*test-request"):
        await translator.translate("こんにちは", source_language="ja-JP", target_language="zh-CN")


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
            self._worker = None
            self._silence_timer = None
            self._callback = kwargs["callback"]

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
