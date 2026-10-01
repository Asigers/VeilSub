import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass

from app.providers.base import Translator


@dataclass(frozen=True, slots=True)
class TranslationResult:
    target: str | None
    cache_hit: bool
    timed_out: bool
    latency_ms: float


class TranslationService:
    """Per-session translation runtime with timeout, cache and rate limits."""

    def __init__(
        self,
        translator: Translator,
        *,
        timeout_seconds: float,
        max_concurrency: int,
        max_qps: int,
        cache_size: int,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("translation timeout must be positive")
        if max_concurrency < 1:
            raise ValueError("translation max concurrency must be >= 1")
        if max_qps < 1:
            raise ValueError("translation max QPS must be >= 1")
        if cache_size < 0:
            raise ValueError("translation cache size must be >= 0")

        self.translator = translator
        self.timeout_seconds = timeout_seconds
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_qps = max_qps
        self.cache_size = cache_size
        self.cache: OrderedDict[tuple[str, str, str], str] = OrderedDict()

        self._rate_lock = asyncio.Lock()
        self._recent_calls: deque[float] = deque()

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
            return TranslationResult(target=None, cache_hit=False, timed_out=False, latency_ms=0.0)

        key = (source_language, target_language, normalized)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.move_to_end(key)
            self.cache_hits += 1
            return TranslationResult(target=cached, cache_hit=True, timed_out=False, latency_ms=0.0)

        async with self.semaphore:
            cached = self.cache.get(key)
            if cached is not None:
                self.cache.move_to_end(key)
                self.cache_hits += 1
                return TranslationResult(target=cached, cache_hit=True, timed_out=False, latency_ms=0.0)

            await self._acquire_rate_slot()

            self.calls += 1
            self.characters += len(normalized)
            loop = asyncio.get_running_loop()
            started_at = loop.time()

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
                return TranslationResult(target=None, cache_hit=False, timed_out=False, latency_ms=0.0)

            if not translated:
                return TranslationResult(target=None, cache_hit=False, timed_out=False, latency_ms=0.0)

            self._cache_put(key, translated)
            return TranslationResult(target=translated, cache_hit=False, timed_out=False)

    async def _acquire_rate_slot(self) -> None:
        loop = asyncio.get_running_loop()

        async with self._rate_lock:
            while True:
                now = loop.time()
                while self._recent_calls and now - self._recent_calls[0] >= 1:
                    self._recent_calls.popleft()

                if len(self._recent_calls) < self.max_qps:
                    self._recent_calls.append(now)
                    return

                wait_seconds = 1 - (now - self._recent_calls[0])
                await asyncio.sleep(max(wait_seconds, 0.001))

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
