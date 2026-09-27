from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from app.models import AudioConfig, SpeechResult


class SpeechStream(ABC):
    @abstractmethod
    async def start(self, *, language: str, audio: AudioConfig) -> None: ...

    @abstractmethod
    async def write(self, chunk: bytes) -> None: ...

    @abstractmethod
    def results(self) -> AsyncIterator[SpeechResult]: ...

    @abstractmethod
    async def close(self) -> None: ...


class Translator(ABC):
    @abstractmethod
    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str | None: ...
