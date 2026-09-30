import asyncio
from collections import OrderedDict
from dataclasses import dataclass

from app.providers.base import Translator


@dataclass(frozen=True, slots=True)
class TranslationResult:
    target: str | None
    cache_hit: bool
    timed_out: bool


class TranslationService:
    """Small per-session translation runtime.

    It keeps translation off the ASR hot path, bounds concurrency, caches repeated
    finalized text, and converts provider failures/timeouts into a missing target
    rather than a failed subtitle session.
    """

    def __init__(
        self,
        translator: Translator,
        *,
        timeout_seconds: float,
        max_concurrency: int,
        cache_size: int,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("translation timeout must be positive")
        if max_concurrency < 1:
            raise ValueError("translation max concurrency must be >= 1")
        if cache_size < 0:
            raise ValueError("translation cache size must be >= 0")

        self.translator = translator
        self.timeout_seconds = timeout_seconds
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.cache_size = cache_size
        self.cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()

        self.calls = 0
        self.characters = 0
        self.cache_hits = 0
        self.timeouts = 0
        self.failures = 0

    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> TranslationResult:
        normalized = self._normalize(text)
        if not normalized:
            return TranslationResult(target=None, cache_hit=False, timed_out=False)

        key = (source_language, target_language, normalized)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.move_to_end(key)
            self.cache_hits += 1
            return TranslationResult(target=cached, cache_hit=True, timed_out=False)

        async with self.semaphore:
            # Another task may have filled the cache while this one waited.
            cached = self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                self.cache_hits += 1
                return TranslationResult(target=cached, cache_hit=True, timed_out=False)

            self.calls += 1
            self.characters += len(normalized)

            try:
                async with asyncio.timeout(self.timeout_seconds):
                    translated = await self.translator.translate(
                        normalized,
                        source_language=source_language,
                        target_language=target_language,
                    )
            except TimeoutError:
                self.timeouts += 1
                return TranslationResult(target=None, cache_hit=False, timed_out=True)
            except Exception:  # noqa: BLE001
                self.failures += 1
                return TranslationResult(target=None, cache_hit=False, timed_out=False)

            if not translated:
                return TranslationResult(target=None, cache_hit=False, timed_out=False)

            self._cache_put(key, translated)
            return TranslationResult(target=translated, cache_hit=False, timed_out=False)

    def _cache_put(self, key: tuple[str, str, str], value: str) -> None:
        if self.cache_size == 0:
            return

        self.cache[key] = value
        self.cache.move_to_end(key)

        while len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(text.split())
