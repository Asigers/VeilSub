import asyncio

import pytest

from app.config import Settings
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
    assert service.last_error == "Translation timed out after 0.01s"


@pytest.mark.asyncio
async def test_translation_failure_is_logged_and_redacted(caplog) -> None:
    class FailingTranslator(Translator):
        settings = Settings(_env_file=None,
            alibaba_cloud_access_key_id="access-id-regression-only",
            alibaba_cloud_access_key_secret="access-secret-regression-only",
        )

        async def translate(self, text, **kwargs):
            raise RuntimeError("SignatureDoesNotMatch " + self.settings.alibaba_cloud_access_key_secret)

    service = TranslationService(FailingTranslator(), timeout_seconds=1,
                                 max_concurrency=1, max_qps=20, cache_size=0)
    result = await service.translate("テスト", source_language="ja-JP", target_language="zh-CN")
    assert result.target is None
    assert service.failures == 1
    assert "SignatureDoesNotMatch" in service.last_error
    assert "access-secret-regression-only" not in service.last_error
    assert "access-secret-regression-only" not in caplog.text
    assert "SignatureDoesNotMatch" in caplog.text


@pytest.mark.asyncio
async def test_empty_translation_is_counted_as_failure() -> None:
    class EmptyTranslator(Translator):
        async def translate(self, text, **kwargs):
            return None

    service = TranslationService(EmptyTranslator(), timeout_seconds=1,
                                 max_concurrency=1, max_qps=20, cache_size=0)
    result = await service.translate("テスト", source_language="ja-JP", target_language="zh-CN")
    assert result.target is None
    assert service.failures == 1
    assert service.last_error == "Translation provider returned an empty result"
