import asyncio

import pytest

from app.providers.base import Translator
from app.translation import TranslationService


class CountingTranslator(Translator):
    def __init__(self) -> None:
        self.calls = 0

    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        self.calls += 1
        return f"ZH:{text}"


class SlowTranslator(Translator):
    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        await asyncio.sleep(0.05)
        return text


@pytest.mark.asyncio
async def test_translation_cache_avoids_duplicate_provider_call() -> None:
    translator = CountingTranslator()
    service = TranslationService(
        translator,
        timeout_seconds=1,
        max_concurrency=2,
        max_qps=20,
        cache_size=16,
    )

    first = await service.translate(
        "  そんなに   見ないで  ",
        source_language="ja-JP",
        target_language="zh-CN",
    )
    second = await service.translate(
        "そんなに 見ないで",
        source_language="ja-JP",
        target_language="zh-CN",
    )

    assert first.target == "ZH:そんなに 見ないで"
    assert first.cache_hit is False
    assert second.target == first.target
    assert second.cache_hit is True
    assert translator.calls == 1
    assert service.calls == 1
    assert service.cache_hits == 1


@pytest.mark.asyncio
async def test_translation_timeout_returns_no_target() -> None:
    service = TranslationService(
        SlowTranslator(),
        timeout_seconds=0.01,
        max_concurrency=1,
        max_qps=20,
        cache_size=0,
    )

    result = await service.translate(
        "遅い翻訳",
        source_language="ja-JP",
        target_language="zh-CN",
    )

    assert result.target is None
    assert result.timed_out is True
    assert service.timeouts == 1
