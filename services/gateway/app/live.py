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
    pump_task: asyncio.Task[None] | None = None

    try:
        start = SessionStart.model_validate_json(await websocket.receive_text())
        await speech.start(language=start.source_language, audio=start.audio)

        session_id = uuid.uuid4().hex
        await websocket.send_json({"type": "session.ready", "session_id": session_id})

        stabilizer = SubtitleStabilizer(
            settings.veilsub_partial_threshold,
            settings.veilsub_translate_threshold,
        )

        async def pump_results() -> None:
            async for result in speech.results():
                decision = stabilizer.decide(result)
                if not decision.show:
                    continue

                target = None
                if decision.translate and result.text:
                    target = await translator.translate(
                        result.text,
                        source_language=start.source_language,
                        target_language=start.target_language,
                    )

                event_type = (
                    "subtitle.final"
                    if decision.final
                    else "subtitle.stable"
                    if decision.translate
                    else "subtitle.partial"
                )
                await websocket.send_json(
                    SubtitleEvent(
                        type=event_type,
                        id=result.id,
                        source=result.text,
                        target=target,
                        stability=result.stability,
                        is_final=result.is_final,
                    ).model_dump()
                )

        pump_task = asyncio.create_task(pump_results())

        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await speech.write(message["bytes"])
                continue

            if message.get("text"):
                payload = json.loads(message["text"])
                if payload.get("type") == "session.stop":
                    break

    except WebSocketDisconnect:
        pass
    finally:
        await speech.close()
        if pump_task:
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(pump_task, timeout=2)
            if not pump_task.done():
                pump_task.cancel()
