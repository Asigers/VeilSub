import asyncio
import contextlib
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.models import SessionStart, SubtitleEvent
from app.providers import create_speech_stream, create_translator
from app.subtitles import SubtitleStabilizer

router = APIRouter()


@router.websocket("/v1/live")
async def live_subtitles(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    speech = create_speech_stream(settings)
    translator = create_translator(settings)
    tasks: set[asyncio.Task[None]] = set()

    try:
        start = SessionStart.model_validate_json(await websocket.receive_text())
        await speech.start(language=start.source_language, audio=start.audio)

        session_id = uuid.uuid4().hex
        await websocket.send_json({"type": "session.ready", "session_id": session_id})

        stabilizer = SubtitleStabilizer()

        async def pump_results() -> None:
            async for result in speech.results():
                decision = stabilizer.decide(result)

                target = None
                if decision.translate and result.text:
                    target = await translator.translate(
                        result.text,
                        source_language=start.source_language,
                        target_language=start.target_language,
                    )

                await websocket.send_json(
                    SubtitleEvent(
                        type="subtitle.final" if decision.final else "subtitle.partial",
                        id=result.id,
                        source=result.text,
                        target=target,
                        is_final=result.is_final,
                        end_offset_ms=result.end_offset_ms,
                    ).model_dump()
                )

        async def receive_audio() -> None:
            while True:
                message = await websocket.receive()
                if message.get("bytes") is not None:
                    await speech.write(message["bytes"])
                    continue

                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "session.stop":
                        return

        tasks = {
            asyncio.create_task(pump_results(), name="subtitle-results"),
            asyncio.create_task(receive_audio(), name="subtitle-audio"),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()
        for task in done:
            await task

    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            await websocket.send_json(
                {
                    "type": "session.error",
                    "code": "stream_failed",
                    "message": str(exc),
                }
            )
    finally:
        await speech.close()
        for task in tasks:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
