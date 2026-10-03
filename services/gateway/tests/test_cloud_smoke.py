import asyncio
import importlib.util
import json
import wave
from pathlib import Path

import pytest

from app.config import Settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "cloud_smoke.py"
spec = importlib.util.spec_from_file_location("cloud_smoke", SCRIPT)
assert spec is not None and spec.loader is not None
cloud_smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud_smoke)


def cloud_settings(**overrides) -> Settings:
    values = {
        "veilsub_speech_provider": "aliyun",
        "veilsub_translation_provider": "aliyun",
        "dashscope_api_key": "test-api-key-not-real",
        "aliyun_bailian_workspace_id": "test-workspace",
        "alibaba_cloud_access_key_id": "test-ak-not-real",
        "alibaba_cloud_access_key_secret": "test-secret-not-real",
    }
    return Settings(_env_file=None, **(values | overrides))


def test_config_check_refuses_mock() -> None:
    with pytest.raises(ValueError, match="mock ASR"):
        cloud_smoke.check_config(cloud_settings(veilsub_speech_provider="mock"), asr_only=False)


def test_config_check_refuses_missing_translation(capsys) -> None:
    with pytest.raises(ValueError, match="TRANSLATION_PROVIDER"):
        cloud_smoke.check_config(cloud_settings(veilsub_translation_provider="none"), asr_only=False)
    cloud_smoke.check_config(cloud_settings(veilsub_translation_provider="none"), asr_only=True)
    assert "test-api-key-not-real" not in capsys.readouterr().out


def test_asr_only_also_refuses_mock_translation() -> None:
    with pytest.raises(ValueError, match="Mock translation"):
        cloud_smoke.check_config(cloud_settings(veilsub_translation_provider="mock"), asr_only=True)


def test_config_check_does_not_print_credentials(capsys) -> None:
    cloud_smoke.check_config(cloud_settings(), asr_only=False)
    output = capsys.readouterr().out
    assert "test-api-key-not-real" not in output
    assert "test-ak-not-real" not in output
    assert "test-secret-not-real" not in output


@pytest.mark.parametrize("channels,rate,width,frames", [(2, 16000, 2, 1600),
    (1, 48000, 2, 1600), (1, 16000, 3, 1600), (1, 16000, 2, 0),
    (1, 16000, 2, 16000 * 61)])
def test_wav_validation_rejects_unsupported_or_oversized_audio(
    tmp_path, channels, rate, width, frames
) -> None:
    path = tmp_path / "regression-only.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(channels)
        audio.setframerate(rate)
        audio.setsampwidth(width)
        audio.writeframes(bytes(frames * channels * width))
    with wave.open(str(path), "rb") as audio, pytest.raises(ValueError):
        cloud_smoke.validate_wav(audio)


@pytest.mark.parametrize("server_provider,emit_translation,expected", [
    ("mock", True, "speech_provider=aliyun"),
    ("aliyun", False, "no matching translation"),
    ("aliyun", True, None),
])
async def test_live_validation_requires_real_provider_and_matching_results(
    tmp_path, monkeypatch, server_provider, emit_translation, expected
) -> None:
    # Only an in-memory protocol regression; no cloud/network calls.
    path = tmp_path / "protocol-regression-only.wav"
    with wave.open(str(path), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(bytes(320))

    class Socket:
        def __init__(self):
            self.events = asyncio.Queue()
            self.audio_bytes = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def send(self, payload):
            if isinstance(payload, bytes):
                self.audio_bytes += len(payload)
                await self.events.put(json.dumps({
                    "type": "subtitle.final", "id": "one", "revision": 1, "source": "こんにちは",
                }))
                if emit_translation:
                    await self.events.put(json.dumps({
                        "type": "subtitle.translation", "id": "one", "revision": 1, "target": "你好",
                    }))
            elif json.loads(payload)["type"] == "session.start":
                await self.events.put(json.dumps({
                    "type": "session.ready", "speech_provider": server_provider,
                    "translation_provider": "aliyun",
                }))
            else:
                await self.events.put(json.dumps({"type": "session.stopped", "metrics": {}}))

        async def recv(self):
            return await self.events.get()

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.recv()

    socket = Socket()
    monkeypatch.setattr(cloud_smoke, "connect", lambda *args, **kwargs: socket)
    if expected:
        with pytest.raises(RuntimeError, match=expected):
            await cloud_smoke.smoke("ws://unused", path, asr_only=False)
        if server_provider == "mock":
            assert socket.audio_bytes == 0
    else:
        await cloud_smoke.smoke("ws://unused", path, asr_only=False)
        assert socket.audio_bytes == 320


def test_cli_requires_explicit_paid_opt_in(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", [str(SCRIPT), "--audio", "any.wav"])
    with pytest.raises(SystemExit) as exc:
        cloud_smoke.main()
    assert exc.value.code == 2
