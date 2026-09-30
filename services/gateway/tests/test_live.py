import asyncio
import json
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from app import live
from app.config import Settings
from app.main import app
from app.models import AudioConfig, SpeechResult
from app.providers.base import SpeechStream, Translator


class FlushOnCloseSpeechStream(SpeechStream):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[SpeechResult | None] = asyncio.Queue()
        self.closed = False

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        return None

    async def write(self, chunk: bytes) -> None:
        return None

    def results(self) -> AsyncIterator[SpeechResult]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[SpeechResult]:
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.queue.put(
            SpeechResult(
                id="flush-1",
                text="最後の字幕",
                is_final=True,
                end_offset_ms=1200,
            )
        )
        await self.queue.put(None)


class TwoResultSpeechStream(SpeechStream):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[SpeechResult | None] = asyncio.Queue()
        self.closed = False

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        await self.queue.put(
            SpeechResult(
                id="one",
                text="第一文です",
                is_final=True,
                end_offset_ms=900,
            )
        )
        await self.queue.put(
            SpeechResult(
                id="two",
                text="第二",
                is_final=False,
                end_offset_ms=None,
            )
        )

    async def write(self, chunk: bytes) -> None:
        return None

    def results(self) -> AsyncIterator[SpeechResult]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[SpeechResult]:
        while True:
            item = await self.queue.get()
            if item is None:
                return
            yield item

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self.queue.put(None)


class SlowTranslator(Translator):
    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        await asyncio.sleep(0.05)
        return "第一句"


def start_payload() -> str:
    return json.dumps(
        {
            "type": "session.start",
            "source_language": "ja-JP",
            "target_language": "zh-CN",
            "audio": {
                "encoding": "linear16",
                "sample_rate_hz": 16000,
                "channels": 1,
            },
        }
    )


def test_graceful_stop_flushes_final_subtitle(monkeypatch) -> None:
    speech = FlushOnCloseSpeechStream()
    monkeypatch.setattr(live, "create_speech_stream", lambda _settings: speech)

    with TestClient(app).websocket_connect("/v1/live") as websocket:
        websocket.send_text(start_payload())

        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_text(json.dumps({"type": "session.stop"}))

        final = websocket.receive_json()
        stopped = websocket.receive_json()

    assert final["type"] == "subtitle.final"
    assert final["revision"] == 1
    assert final["source"] == "最後の字幕"
    assert final["id"] == f"{ready['session_id']}:flush-1"
    assert stopped["type"] == "session.stopped"
    assert stopped["translation_calls"] == 0
    assert stopped["translation_characters"] == 0
    assert speech.closed is True


def test_slow_translation_does_not_block_next_asr_event(monkeypatch) -> None:
    speech = TwoResultSpeechStream()

    monkeypatch.setattr(
        live,
        "get_settings",
        lambda: Settings(veilsub_translation_provider="mock"),
    )
    monkeypatch.setattr(live, "create_speech_stream", lambda _settings: speech)
    monkeypatch.setattr(live, "create_translator", lambda _settings: SlowTranslator())

    with TestClient(app).websocket_connect("/v1/live") as websocket:
        websocket.send_text(start_payload())
        ready = websocket.receive_json()

        first_final = websocket.receive_json()
        next_partial = websocket.receive_json()
        translation = websocket.receive_json()

        websocket.send_text(json.dumps({"type": "session.stop"}))
        stopped = websocket.receive_json()

    assert ready["type"] == "session.ready"

    assert first_final["type"] == "subtitle.final"
    assert first_final["source"] == "第一文です"
    assert first_final["target"] is None
    assert first_final["revision"] == 1

    # This must arrive before the deliberately slow translation finishes.
    assert next_partial["type"] == "subtitle.partial"
    assert next_partial["source"] == "第二"

    assert translation["type"] == "subtitle.translation"
    assert translation["id"] == first_final["id"]
    assert translation["revision"] == first_final["revision"]
    assert translation["target"] == "第一句"

    assert stopped["type"] == "session.stopped"
    assert stopped["translation_calls"] == 1
    assert stopped["translation_characters"] == len("第一文です")
