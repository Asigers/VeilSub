"""Opt-in real-cloud smoke test via the Gateway; never substitutes a mock provider."""

import argparse
import asyncio
import contextlib
import json
import sys
import wave
from pathlib import Path

from websockets.asyncio.client import connect

from app.config import Settings

SAMPLE_RATE = 16000
FRAME_SAMPLES = 1600
MAX_AUDIO_SECONDS = 60


def check_config(settings: Settings, *, asr_only: bool) -> None:
    required = {
        "DASHSCOPE_API_KEY": settings.dashscope_api_key,
        "ALIYUN_BAILIAN_WORKSPACE_ID": settings.aliyun_bailian_workspace_id,
    }
    if not asr_only:
        required.update(
            ALIBABA_CLOUD_ACCESS_KEY_ID=settings.alibaba_cloud_access_key_id,
            ALIBABA_CLOUD_ACCESS_KEY_SECRET=settings.alibaba_cloud_access_key_secret,
        )
    if settings.veilsub_speech_provider != "aliyun":
        raise ValueError("Set VEILSUB_SPEECH_PROVIDER=aliyun; mock ASR is not accepted")
    if settings.veilsub_translation_provider == "mock":
        raise ValueError("Mock translation is not accepted, even with --asr-only")
    if not asr_only and settings.veilsub_translation_provider != "aliyun":
        raise ValueError("Set VEILSUB_TRANSLATION_PROVIDER=aliyun, or use --asr-only")
    missing = [key for key, value in required.items() if not value.strip()]
    if missing:
        raise ValueError("Missing credentials: " + ", ".join(missing))
    print(
        "Local config: speech=aliyun, "
        f"translation={settings.veilsub_translation_provider}, "
        f"region={settings.aliyun_bailian_region}, model={settings.aliyun_asr_model}"
    )
    print("Required credentials are present (values are not printed).")
    print("This is not an authentication check; live results are required to pass.")


def validate_wav(audio: wave.Wave_read) -> float:
    if (
        audio.getnchannels() != 1
        or audio.getsampwidth() != 2
        or audio.getframerate() != SAMPLE_RATE
        or audio.getcomptype() != "NONE"
    ):
        raise ValueError("Audio must be an uncompressed PCM16 / 16000 Hz / mono WAV")
    duration = audio.getnframes() / SAMPLE_RATE
    if not 0 < duration <= MAX_AUDIO_SECONDS:
        raise ValueError(f"Audio must be nonempty and at most {MAX_AUDIO_SECONDS} seconds")
    return duration


async def smoke(url: str, audio_path: Path, *, asr_only: bool) -> None:
    # A stalled socket send must not leave a billable session open indefinitely.
    async with asyncio.timeout(MAX_AUDIO_SECONDS + 65):
        await _smoke(url, audio_path, asr_only=asr_only)


async def _smoke(url: str, audio_path: Path, *, asr_only: bool) -> None:
    with wave.open(str(audio_path), "rb") as audio:
        duration = validate_wav(audio)
        print(f"Sending {duration:.2f}s of real audio at realtime speed; charges may apply.")
        async with connect(url, open_timeout=10, close_timeout=3, max_size=1024 * 1024) as ws:
            await ws.send(
                json.dumps(
                    {
                        "type": "session.start",
                        "source_language": "ja-JP",
                        "target_language": "zh-CN",
                        "audio": {
                            "encoding": "linear16",
                            "sample_rate_hz": SAMPLE_RATE,
                            "channels": 1,
                        },
                    }
                )
            )
            ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            if ready.get("type") != "session.ready":
                raise RuntimeError(f"Gateway did not become ready: {ready}")
            if ready.get("speech_provider") != "aliyun":
                raise RuntimeError("Server did not confirm speech_provider=aliyun; restart Gateway")
            if ready.get("translation_provider") == "mock":
                raise RuntimeError("Server is using mock translation; restart Gateway")
            if not asr_only and ready.get("translation_provider") != "aliyun":
                raise RuntimeError("Server did not confirm translation_provider=aliyun")
            print(json.dumps(ready, ensure_ascii=False))

            finals: dict[tuple[str, int], str] = {}
            translations: dict[tuple[str, int], str] = {}
            stop_requested = False

            async def receive_events() -> dict:
                async for raw in ws:
                    event = json.loads(raw)
                    print(json.dumps(event, ensure_ascii=False), flush=True)
                    kind = event.get("type")
                    if kind == "session.error":
                        raise RuntimeError("Gateway reported session.error; inspect the event above")
                    if kind == "session.stopped":
                        if not stop_requested:
                            raise RuntimeError("Gateway stopped before audio finished")
                        return event
                    key = (event.get("id", ""), event.get("revision", 0))
                    if kind == "subtitle.final" and event.get("source", "").strip():
                        finals[key] = event["source"]
                    elif kind == "subtitle.translation" and event.get("target", "").strip():
                        translations[key] = event["target"]
                raise RuntimeError("Gateway disconnected before session.stopped")

            receiver = asyncio.create_task(receive_events())
            try:
                loop = asyncio.get_running_loop()
                started = loop.time()
                sent_samples = 0
                while chunk := audio.readframes(FRAME_SAMPLES):
                    if receiver.done():
                        await receiver
                        raise RuntimeError("Gateway stopped while audio was still being sent")
                    await ws.send(chunk)
                    sent_samples += len(chunk) // 2
                    await asyncio.sleep(max(0.0, started + sent_samples / SAMPLE_RATE - loop.time()))
                if sent_samples != audio.getnframes():
                    raise ValueError("WAV data is truncated; fewer samples read than declared")
                stop_requested = True
                await ws.send(json.dumps({"type": "session.stop"}))
                stopped = await asyncio.wait_for(receiver, timeout=35)
            finally:
                if not receiver.done():
                    receiver.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await receiver

            if not finals:
                raise RuntimeError("No nonempty final ASR subtitle; check speech, language and credentials")
            matched = set(finals) & set(translations)
            if not asr_only and not matched:
                raise RuntimeError("ASR succeeded but no matching translation; check MT activation/credentials")
            if not isinstance(stopped.get("metrics"), dict):
                raise TypeError("session.stopped did not include metrics")
            print(f"PASS: {len(finals)} final subtitles, {len(matched)} matching translations, graceful stop.")
            print("Recognition/translation quality still requires comparing the text with the recording.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audio", type=Path, help="Real Japanese PCM16/16kHz/mono WAV, at most 60s")
    parser.add_argument("--url", default="ws://127.0.0.1:8010/v1/live")
    parser.add_argument("--asr-only", action="store_true", help="Do not require MT credentials/results")
    parser.add_argument("--check-config", action="store_true", help="Offline config check; no network/charges")
    parser.add_argument("--allow-paid", action="store_true", help="Explicitly permit billable cloud calls")
    args = parser.parse_args()
    if not args.check_config and (args.audio is None or not args.allow_paid):
        parser.error("Live testing requires --audio FILE and --allow-paid")
    try:
        check_config(Settings(), asr_only=args.asr_only)
        if not args.check_config:
            asyncio.run(smoke(args.url, args.audio, asr_only=args.asr_only))
    except (Exception, KeyboardInterrupt) as exc:  # noqa: BLE001
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
