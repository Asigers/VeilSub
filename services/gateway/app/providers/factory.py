from app.config import Settings
from app.providers.base import SpeechStream, Translator
from app.providers.mock import MockSpeechStream, MockTranslator, NullTranslator


def create_speech_stream(settings: Settings) -> SpeechStream:
    if settings.veilsub_speech_provider == "mock":
        return MockSpeechStream()
    if settings.veilsub_speech_provider == "google":
        from app.providers.google import GoogleSpeechStream

        return GoogleSpeechStream(settings)
    raise ValueError(f"unsupported speech provider: {settings.veilsub_speech_provider}")


def create_translator(settings: Settings) -> Translator:
    if settings.veilsub_translation_provider == "none":
        return NullTranslator()
    if settings.veilsub_translation_provider == "mock":
        return MockTranslator()
    if settings.veilsub_translation_provider == "google":
        from app.providers.google import GoogleTranslator

        return GoogleTranslator(settings)
    raise ValueError(
        f"unsupported translation provider: {settings.veilsub_translation_provider}"
    )
