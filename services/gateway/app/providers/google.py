from app.config import Settings
from app.models import AudioConfig
from app.providers.base import SpeechStream, Translator


class GoogleSpeechStream(SpeechStream):
    """Production adapter boundary for Speech-to-Text V2 / Chirp 3.

    The streaming implementation belongs here so Google request/response types
    never leak into the rest of VeilSub.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        if not self.settings.google_cloud_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")
        raise NotImplementedError("Implement Chirp 3 StreamingRecognize in M0")

    async def write(self, chunk: bytes) -> None:
        raise NotImplementedError

    def results(self):
        raise NotImplementedError

    async def close(self) -> None:
        return None


class GoogleTranslator(Translator):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None

    async def translate(self, text: str, *, source_language: str, target_language: str) -> str:
        if not self.settings.google_cloud_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")

        from google.cloud import translate_v3

        if self.client is None:
            self.client = translate_v3.TranslationServiceAsyncClient()

        response = await self.client.translate_text(
            request={
                "parent": f"projects/{self.settings.google_cloud_project}/locations/global",
                "contents": [text],
                "mime_type": "text/plain",
                "source_language_code": source_language.split("-")[0],
                "target_language_code": target_language.split("-")[0],
            }
        )
        return response.translations[0].translated_text
