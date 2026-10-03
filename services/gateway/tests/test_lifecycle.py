import asyncio
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app import live
from app.config import Settings
from app.models import AudioConfig
from app.providers.aliyun import AliyunSpeechStream, _RecognitionCallback, _stop_recognition
from app.providers.mock import MockSpeechStream


@pytest.mark.parametrize("field,value", [
    ("sample_rate_hz", 0), ("sample_rate_hz", -1), ("sample_rate_hz", 48000),
    ("channels", 0), ("channels", -1), ("channels", 2),
])
def test_fixed_audio_protocol(field, value):
    with pytest.raises(ValidationError):
        AudioConfig(**{field: value})


async def test_mock_defends_against_bypassed_validation():
    speech = MockSpeechStream()
    with pytest.raises(ValidationError):
        await speech.start(language="ja", audio=AudioConfig.model_construct(channels=0))
    speech.bytes_per_result = 0
    with pytest.raises(ValueError):
        await speech.write(b"audio")


class FakeWebSocket:
    def __init__(self, frames):
        self.frames = asyncio.Queue()
        for frame in frames:
            self.frames.put_nowait(frame)
        self.sent = []
        self.closed = False

    async def accept(self):
        pass

    async def receive_text(self):
        return json.dumps({"type": "session.start"})

    async def receive(self):
        return await self.frames.get()

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


class LifecycleSpeech:
    def __init__(self, failure):
        self.failure = failure
        self.closed = False
        self.pump_cleaned = False
        self.end = asyncio.Event()

    async def start(self, **kwargs):
        if self.failure == "start":
            raise RuntimeError("start failed")
        if self.failure == "start_timeout":
            await asyncio.Event().wait()

    async def write(self, chunk):
        if self.failure == "write":
            raise RuntimeError("write failed")
        if self.failure == "write_timeout":
            await asyncio.Event().wait()

    async def close(self):
        self.closed = True
        if self.failure == "close":
            raise RuntimeError("close failed")
        if self.failure == "close_timeout":
            await asyncio.Event().wait()
        self.end.set()

    async def results(self):
        try:
            if self.failure != "results_end":
                await self.end.wait()
            if self.failure == "flush_timeout":
                await asyncio.Event().wait()
            if False:
                yield None
        finally:
            self.pump_cleaned = True


@pytest.mark.parametrize("failure", [
    "start", "start_timeout", "write", "write_timeout", "close", "close_timeout",
    "flush_timeout", "results_end", "disconnect",
])
async def test_gateway_lifecycle_is_bounded_and_terminal(monkeypatch, failure):
    speech = LifecycleSpeech(failure)
    monkeypatch.setattr(live, "get_settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(live, "create_speech_stream", lambda settings: speech)
    for name in ("START_TIMEOUT", "WRITE_TIMEOUT", "CLOSE_TIMEOUT", "FLUSH_TIMEOUT"):
        monkeypatch.setattr(live, name, 0.02)
    if failure.startswith("write"):
        frames = [{"type": "websocket.receive", "bytes": b"audio"}]
    elif failure == "disconnect":
        frames = [{"type": "websocket.disconnect", "code": 1000}]
    elif failure == "results_end":
        frames = []
    else:
        frames = [{"type": "websocket.receive", "text": '{"type":"session.stop"}'}]
    ws = FakeWebSocket(frames)
    await asyncio.wait_for(live.live_subtitles(ws), 1)
    assert speech.closed
    assert ws.closed
    assert failure.startswith("start") or speech.pump_cleaned
    errors = [payload for payload in ws.sent if payload["type"] == "session.error"]
    assert bool(errors) == (failure != "disconnect")
    assert not any(payload["type"] == "session.stopped" for payload in ws.sent)
    if failure == "results_end":
        assert "before session.stop" in errors[0]["message"]


async def test_invalid_settings_are_structured(monkeypatch):
    def invalid_settings():
        raise ValueError("invalid configuration")
    monkeypatch.setattr(live, "get_settings", invalid_settings)
    ws = FakeWebSocket([])
    await live.live_subtitles(ws)
    assert ws.sent[0]["type"] == "session.error"
    assert ws.closed


def test_error_messages_redact_credentials_and_authorization():
    settings = Settings(_env_file=None,
        dashscope_api_key="api-key-regression-only",
        alibaba_cloud_access_key_id="access-id-regression-only",
        alibaba_cloud_access_key_secret="access-secret-regression-only",
        aliyun_bailian_workspace_id="workspace-regression",
    )
    error = RuntimeError(
        "InvalidApiKey " + settings.dashscope_api_key + " " +
        settings.alibaba_cloud_access_key_id + " " + settings.alibaba_cloud_access_key_secret +
        " " + settings.aliyun_bailian_workspace_id + " Authorization: Bearer arbitrary-test-token"
    )
    message = live.safe_error_message(error, settings)
    for value in (settings.dashscope_api_key, settings.alibaba_cloud_access_key_id,
                  settings.alibaba_cloud_access_key_secret, settings.aliyun_bailian_workspace_id,
                  "arbitrary-test-token"):
        assert value not in message
    assert "InvalidApiKey" in message


def test_validation_error_does_not_disclose_its_input():
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, veilsub_translation_max_concurrency="input-regression-only")
    message = live.safe_error_message(error.value, None)
    assert "veilsub_translation_max_concurrency" in message
    assert "input-regression-only" not in message


async def test_gateway_logs_sanitized_error_and_marks_it_terminal(monkeypatch, caplog):
    settings = Settings(_env_file=None, dashscope_api_key="api-key-regression-only")
    speech = LifecycleSpeech("write")

    async def fail_write(chunk):
        raise RuntimeError("InvalidApiKey " + settings.dashscope_api_key)

    speech.write = fail_write
    monkeypatch.setattr(live, "get_settings", lambda: settings)
    monkeypatch.setattr(live, "create_speech_stream", lambda _settings: speech)
    ws = FakeWebSocket([{"type": "websocket.receive", "bytes": b"audio"}])
    await live.live_subtitles(ws)
    error = next(payload for payload in ws.sent if payload["type"] == "session.error")
    assert error["retryable"] is False
    assert "InvalidApiKey" in error["message"]
    assert settings.dashscope_api_key not in error["message"]
    assert settings.dashscope_api_key not in caplog.text
    assert "InvalidApiKey" in caplog.text
    assert speech.closed and ws.closed


async def test_partial_aliyun_start_failure_cleans_resources(monkeypatch):
    timer = Mock()
    worker = Mock()
    worker.is_alive.return_value = False
    class Recognition:
        def __init__(self, **kwargs):
            self._callback = kwargs["callback"]
            self._worker = worker
            self._silence_timer = timer

        def start(self):
            raise RuntimeError("partially allocated")
    monkeypatch.setattr("app.providers.aliyun.asr.Recognition", Recognition)
    speech = AliyunSpeechStream(Settings(
        _env_file=None, dashscope_api_key="test-only", aliyun_bailian_workspace_id="test-only",
    ))
    with pytest.raises(RuntimeError, match="partially allocated"):
        await speech.start(language="ja", audio=AudioConfig())
    assert speech._closed
    assert speech._results_finished
    timer.cancel.assert_called_once()
    await speech.close()


def test_bounded_sdk_stop_cancels_timer_even_after_error():
    worker = Mock()
    worker.is_alive.return_value = True
    timer = Mock()
    recognition = SimpleNamespace(_worker=worker, _silence_timer=timer, _running=False)
    with pytest.raises(TimeoutError):
        _stop_recognition(recognition)
    worker.join.assert_called_once_with(timeout=5.0)
    timer.cancel.assert_called_once()
    assert recognition._silence_timer is None


async def test_sdk_on_close_finishes_results_and_ignores_late_events():
    speech = AliyunSpeechStream(Settings(_env_file=None))
    speech._loop = asyncio.get_running_loop()
    _RecognitionCallback(speech).on_close()
    assert [result async for result in speech.results()] == []
    speech._handle_event(SimpleNamespace(get_sentence=lambda: {"text": "late"}))
    await asyncio.sleep(0)
    assert speech._result_queue.empty()


async def test_aliyun_close_exception_still_finishes_and_cleans_timer():
    speech = AliyunSpeechStream(Settings(_env_file=None))
    speech._loop = asyncio.get_running_loop()
    worker = Mock()
    worker.is_alive.return_value = True
    worker.join.side_effect = RuntimeError("join failed")
    timer = Mock()
    speech._recognition = SimpleNamespace(
        _worker=worker, _silence_timer=timer, _running=True,
    )
    with pytest.raises(RuntimeError, match="join failed"):
        await speech.close()
    timer.cancel.assert_called_once()
    assert speech._results_finished
    assert [result async for result in speech.results()] == []
    await speech.close()


async def test_cancelled_sdk_start_cleans_late_allocations(monkeypatch):
    import threading

    entered = threading.Event()
    release = threading.Event()
    cleaned = threading.Event()
    timer = Mock()
    timer.cancel.side_effect = cleaned.set

    class Recognition:
        def __init__(self, **kwargs):
            self._callback = kwargs["callback"]
            self._worker = None
            self._silence_timer = None

        def start(self):
            entered.set()
            assert release.wait(1)
            self._silence_timer = timer
            self._running = True

    monkeypatch.setattr("app.providers.aliyun.asr.Recognition", Recognition)
    speech = AliyunSpeechStream(Settings(
        _env_file=None, dashscope_api_key="test-only", aliyun_bailian_workspace_id="test-only",
    ))
    task = asyncio.create_task(speech.start(language="ja", audio=AudioConfig()))
    try:
        assert await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
    assert await asyncio.to_thread(cleaned.wait, 1)
    assert speech._closed
    assert speech._recognition._running is False
    assert speech._recognition._silence_timer is None
