import asyncio
import json
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

import app.live as live
from app.main import app
from app.models import AudioConfig, SpeechResult
from app.providers.base import SpeechStream


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


def test_graceful_stop_flushes_final_subtitle(monkeypatch) -> None:
    speech = FlushOnCloseSpeechStream()
    monkeypatch.setattr(live, "create_speech_stream", lambda _settings: speech)

    with TestClient(app).websocket_connect("/v1/live") as websocket:
        websocket.send_text(
            json.dumps(
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
        )

        ready = websocket.receive_json()
        assert ready["type"] == "session.ready"

        websocket.send_text(json.dumps({"type": "session.stop"}))

        final = websocket.receive_json()
        stopped = websocket.receive_json()

    assert final["type"] == "subtitle.final"
    assert final["source"] == "最後の字幕"
    assert final["id"] == f"{ready['session_id']}:flush-1"
    assert stopped == {"type": "session.stopped"}
    assert speech.closed is True
