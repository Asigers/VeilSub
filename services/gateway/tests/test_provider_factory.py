from app.config import Settings
from app.providers.factory import create_speech_stream, create_translator
from app.providers.mock import MockSpeechStream, NullTranslator


def test_default_development_providers() -> None:
    settings = Settings()
    assert isinstance(create_speech_stream(settings), MockSpeechStream)
    assert isinstance(create_translator(settings), NullTranslator)


def test_aliyun_provider_selection() -> None:
    speech = create_speech_stream(Settings(veilsub_speech_provider="aliyun"))
    translator = create_translator(Settings(veilsub_translation_provider="aliyun"))

    assert speech.__class__.__name__ == "AliyunSpeechStream"
    assert translator.__class__.__name__ == "AliyunTranslator"
