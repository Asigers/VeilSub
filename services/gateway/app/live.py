import asyncio
import contextlib
import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import Settings, get_settings
from app.errors import safe_error_message
from app.metrics import SessionMetrics
from app.models import SessionStart, SubtitleEvent
from app.providers import create_speech_stream, create_translator
from app.subtitles import SubtitleStabilizer
from app.translation import TranslationService

router = APIRouter()
logger = logging.getLogger(__name__)


START_TIMEOUT = 10.0
WRITE_TIMEOUT = 5.0
CLOSE_TIMEOUT = 7.0
FLUSH_TIMEOUT = 10.0
SEND_TIMEOUT = 5.0


@router.websocket("/v1/live")
async def live_subtitles(websocket: WebSocket) -> None:
    await websocket.accept()
    speech = None
    settings: Settings | None = None
    session_id: str | None = None
    pump_task: asyncio.Task[None] | None = None
    receive_task: asyncio.Task[str] | None = None
    translation_tasks: dict[str, asyncio.Task[None]] = {}
    segment_revisions: dict[str, int] = {}
    send_lock = asyncio.Lock()
    speech_closed = False
    metrics: SessionMetrics | None = None

    async def send_json(payload: dict[str, object]) -> None:
        async with send_lock:
            await asyncio.wait_for(websocket.send_json(payload), SEND_TIMEOUT)

    async def close_speech() -> None:
        nonlocal speech_closed
        if speech_closed or speech is None:
            return
        speech_closed = True
        await asyncio.wait_for(speech.close(), CLOSE_TIMEOUT)

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
        await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True), FLUSH_TIMEOUT
        )

    try:
        settings = get_settings()
        speech = create_speech_stream(settings)
        translator = create_translator(settings)
        translation_enabled = settings.veilsub_translation_provider != "none"
        translation = TranslationService(
            translator,
            timeout_seconds=settings.veilsub_translation_timeout_seconds,
            max_concurrency=settings.veilsub_translation_max_concurrency,
            max_qps=settings.veilsub_translation_max_qps,
            cache_size=settings.veilsub_translation_cache_size,
        )

        start = SessionStart.model_validate_json(
            await asyncio.wait_for(websocket.receive_text(), START_TIMEOUT)
        )
        metrics = SessionMetrics(audio=start.audio)
        await asyncio.wait_for(
            speech.start(language=start.source_language, audio=start.audio), START_TIMEOUT
        )

        session_id = uuid.uuid4().hex
        await send_json(
            {
                "type": "session.ready",
                "session_id": session_id,
                "speech_provider": settings.veilsub_speech_provider,
                "translation_provider": settings.veilsub_translation_provider,
            }
        )

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
            if outcome.target and metrics is not None:
                metrics.record_translation(
                    provider_latency_ms=outcome.latency_ms,
                    end_offset_ms=end_offset_ms,
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

                if metrics is not None:
                    metrics.record_subtitle(
                        is_final=result.is_final,
                        end_offset_ms=result.end_offset_ms,
                    )

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

                if translation_enabled and decision.translate and result.text:
                    schedule_translation(
                        segment_id=segment_id,
                        revision=revision,
                        source=result.text,
                        end_offset_ms=result.end_offset_ms,
                    )

        async def receive_audio() -> str:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect(message.get("code", 1000))
                if message.get("bytes") is not None:
                    chunk = message["bytes"]
                    if metrics is not None:
                        metrics.record_audio(len(chunk))
                    await asyncio.wait_for(speech.write(chunk), WRITE_TIMEOUT)
                    continue

                if message.get("text"):
                    payload = json.loads(message["text"])
                    if payload.get("type") == "client.stats" and metrics is not None:
                        metrics.update_client_stats(
                            reconnect_count=int(payload.get("reconnect_count") or 0),
                            dropped_audio_ms=float(payload.get("dropped_audio_ms") or 0),
                        )
                        continue
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
                await asyncio.wait_for(pump_task, FLUSH_TIMEOUT)
                await drain_translation_tasks()
                metric_summary = (
                    metrics.summary(
                        translation_calls=translation.calls,
                        translation_characters=translation.characters,
                        translation_cache_hits=translation.cache_hits,
                        translation_timeouts=translation.timeouts,
                        translation_failures=translation.failures,
                    )
                    if metrics is not None
                    else {}
                )
                await send_json(
                    {
                        "type": "session.stopped",
                        "metrics": {
                            **metric_summary,
                            "translation_last_error": translation.last_error,
                        },
                    }
                )
                return

        if pump_task in done:
            await pump_task
            raise RuntimeError("speech provider results ended before session.stop")

    except WebSocketDisconnect:
        await cancel_translation_tasks()
    except Exception as exc:  # noqa: BLE001
        message = safe_error_message(exc, settings)
        logger.warning(
            "Live session %s failed (%s): %s",
            session_id or "startup", type(exc).__name__, message,
        )
        await cancel_translation_tasks()
        with contextlib.suppress(Exception):
            await send_json(
                {
                    "type": "session.error",
                    "code": "stream_failed",
                    "message": message,
                    "retryable": False,
                }
            )
    finally:
        # Stop producers before cancelling translations so no new task escapes cleanup.
        for task in (receive_task, pump_task):
            if task is None:
                continue
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

        await cancel_translation_tasks()
        # Cleanup must continue even when provider close fails or times out.
        with contextlib.suppress(Exception):
            await close_speech()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(websocket.close(), SEND_TIMEOUT)
