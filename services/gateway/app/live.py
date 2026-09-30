import asyncio
import contextlib
import json
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import get_settings
from app.models import SessionStart, SubtitleEvent
from app.providers import create_speech_stream, create_translator
from app.subtitles import SubtitleStabilizer
from app.translation import TranslationService

router = APIRouter()


@router.websocket("/v1/live")
async def live_subtitles(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    speech = create_speech_stream(settings)
    translator = create_translator(settings)
    translation = TranslationService(
        translator,
        timeout_seconds=settings.veilsub_translation_timeout_seconds,
        max_concurrency=settings.veilsub_translation_max_concurrency,
        max_qps=settings.veilsub_translation_max_qps,
        cache_size=settings.veilsub_translation_cache_size,
    )

    pump_task: asyncio.Task[None] | None = None
    receive_task: asyncio.Task[str] | None = None
    translation_tasks: dict[str, asyncio.Task[None]] = {}
    segment_revisions: dict[str, int] = {}
    send_lock = asyncio.Lock()
    speech_closed = False

    async def send_json(payload: dict[str, object]) -> None:
        async with send_lock:
            await websocket.send_json(payload)

    async def close_speech() -> None:
        nonlocal speech_closed
        if speech_closed:
            return
        speech_closed = True
        await speech.close()

    async def cancel_translation_tasks() -> None:
        tasks = list(translation_tasks.values())
        translation_tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def drain_translation_tasks() -> None:
        tasks = list(translation_tasks.values())
        if not tasks:
            return
        await asyncio.gather(*tasks, return_exceptions=True)

    try:
        start = SessionStart.model_validate_json(await websocket.receive_text())
        await speech.start(language=start.source_language, audio=start.audio)

        session_id = uuid.uuid4().hex
        await send_json({"type": "session.ready", "session_id": session_id})

        stabilizer = SubtitleStabilizer()

        async def translate_final(
            *,
            segment_id: str,
            revision: int,
            source: str,
            end_offset_ms: int | None,
        ) -> None:
            outcome = await translation.translate(
                source,
                source_language=start.source_language,
                target_language=start.target_language,
            )
            if not outcome.target:
                return
            if segment_revisions.get(segment_id) != revision:
                return

            await send_json(
                SubtitleEvent(
                    type="subtitle.translation",
                    id=segment_id,
                    revision=revision,
                    source=source,
                    target=outcome.target,
                    is_final=True,
                    end_offset_ms=end_offset_ms,
                ).model_dump()
            )

        def schedule_translation(
            *,
            segment_id: str,
            revision: int,
            source: str,
            end_offset_ms: int | None,
        ) -> None:
            previous = translation_tasks.get(segment_id)
            if previous and not previous.done():
                previous.cancel()

            task = asyncio.create_task(
                translate_final(
                    segment_id=segment_id,
                    revision=revision,
                    source=source,
                    end_offset_ms=end_offset_ms,
                ),
                name=f"translate:{segment_id}",
            )
            translation_tasks[segment_id] = task

            def cleanup(done: asyncio.Task[None]) -> None:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    done.result()
                if translation_tasks.get(segment_id) is done:
                    translation_tasks.pop(segment_id, None)

            task.add_done_callback(cleanup)

        async def pump_results() -> None:
            async for result in speech.results():
                decision = stabilizer.decide(result)
                segment_id = f"{session_id}:{result.id}"
                revision = segment_revisions.get(segment_id, 0) + 1
                segment_revisions[segment_id] = revision

                await send_json(
                    SubtitleEvent(
                        type="subtitle.final" if decision.final else "subtitle.partial",
                        id=segment_id,
                        revision=revision,
                        source=result.text,
                        target=None,
                        is_final=result.is_final,
                        end_offset_ms=result.end_offset_ms,
                    ).model_dump()
                )

                if decision.translate and result.text:
                    schedule_translation(
                        segment_id=segment_id,
                        revision=revision,
                        source=result.text,
                        end_offset_ms=result.end_offset_ms,
                    )

        async def receive_audio() -> str:
            while True:
                message = await websocket.receive()
                if message.get("bytes") is not None:
                    await speech.write(message["bytes"])
                    continue

                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "session.stop":
                        return "stop"

        pump_task = asyncio.create_task(pump_results(), name="subtitle-results")
        receive_task = asyncio.create_task(receive_audio(), name="subtitle-audio")

        done, _pending = await asyncio.wait(
            {pump_task, receive_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        if receive_task in done:
            reason = await receive_task
            if reason == "stop":
                await close_speech()
                await pump_task
                await drain_translation_tasks()
                await send_json(
                    {
                        "type": "session.stopped",
                        "translation_calls": translation.calls,
                        "translation_characters": translation.characters,
                        "translation_cache_hits": translation.cache_hits,
                    }
                )
                return

        if pump_task in done:
            await pump_task
            await drain_translation_tasks()
            if receive_task and not receive_task.done():
                receive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receive_task

    except WebSocketDisconnect:
        await cancel_translation_tasks()
    except Exception as exc:  # noqa: BLE001
        await cancel_translation_tasks()
        with contextlib.suppress(Exception):
            await send_json(
                {
                    "type": "session.error",
                    "code": "stream_failed",
                    "message": str(exc),
                }
            )
    finally:
        await close_speech()
        await cancel_translation_tasks()

        for task in (receive_task, pump_task):
            if task is None:
                continue
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
