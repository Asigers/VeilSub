import asyncio
from collections.abc import AsyncIterator

from app.models import AudioConfig, SpeechResult
from app.providers.base import SpeechStream, Translator


class MockSpeechStream(SpeechStream):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[SpeechResult | None] = asyncio.Queue()
        self.bytes_seen = 0
        self.bytes_per_result = 32000
        self.segment = 0

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        self.bytes_per_result = audio.sample_rate_hz * audio.channels * 2

    async def write(self, chunk: bytes) -> None:
        self.bytes_seen += len(chunk)
        while self.bytes_seen >= self.bytes_per_result:
            self.bytes_seen -= self.bytes_per_result
            self.segment += 1
            await self.queue.put(
                SpeechResult(
                    id=f"mock-{self.segment}",
                    text=f"モック字幕 {self.segment}",
                    is_final=True,
                )
            )

    async def _iterate(self) -> AsyncIterator[SpeechResult]:
        while True:
            result = await self.queue.get()
            if result is None:
                break
            yield result

    def results(self) -> AsyncIterator[SpeechResult]:
        return self._iterate()

    async def close(self) -> None:
        await self.queue.put(None)


class NullTranslator(Translator):
    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> None:
        return None


class MockTranslator(Translator):
    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        return f"[mock {target_language}] {text}"
