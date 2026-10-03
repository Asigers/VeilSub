# ruff: noqa: I001
import asyncio
import logging
import time
from queue import Queue
from collections.abc import AsyncIterator
from typing import Any

import dashscope
from dashscope.audio import asr

from app.config import Settings
from app.models import AudioConfig, SpeechResult
from app.providers.base import SpeechStream, Translator


logger = logging.getLogger(__name__)
SDK_STOP_TIMEOUT = 5.0


def _stop_recognition(recognition: asr.Recognition) -> None:
    """Bounded equivalent of DashScope 1.27.7 stop (private SDK fields).

    _running=False lets the input iterator drain queued audio gracefully. There
    is no public abort API: a timed-out network worker can still remain alive.
    """
    recognition._stop_stream_timestamp = time.time() * 1000
    recognition._running = False
    try:
        worker = recognition._worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=SDK_STOP_TIMEOUT)
            if worker.is_alive():
                logger.warning("DashScope network worker survived bounded stop")
                raise TimeoutError("DashScope worker did not stop within 5 seconds")
    finally:
        timer = recognition._silence_timer
        if timer is not None:
            timer.cancel()
            recognition._silence_timer = None
    recognition._stream_data = Queue()
    recognition._callback.on_close()


_REGION_HOSTS = {
    "cn-beijing": "{workspace}.cn-beijing.maas.aliyuncs.com",
    "ap-southeast-1": "{workspace}.ap-southeast-1.maas.aliyuncs.com",
}


def _asr_websocket_url(settings: Settings) -> str:
    workspace = settings.aliyun_bailian_workspace_id.strip()
    # New ws-* IDs can include the China namespace suffix. That suffix is
    # not a second DNS label in the workspace-specific Beijing endpoint;
    # keeping it produces a hostname outside the certificate's wildcard.
    if workspace.startswith("ws-") and workspace.endswith(".cn"):
        if settings.aliyun_bailian_region != "cn-beijing":
            raise ValueError("A .cn Workspace ID requires the cn-beijing ASR region")
        workspace = workspace.removesuffix(".cn")
    if not workspace or "." in workspace or "/" in workspace or ":" in workspace:
        raise ValueError("Workspace ID must be an ID, not a hostname or URL")
    host = _REGION_HOSTS[settings.aliyun_bailian_region].format(workspace=workspace)
    return f"wss://{host}/api-ws/v1/inference"


class _RecognitionCallback(asr.RecognitionCallback):
    def __init__(self, owner: "AliyunSpeechStream") -> None:
        self.owner = owner

    def on_open(self) -> None:
        return None

    def on_event(self, result: asr.RecognitionResult) -> None:
        self.owner._handle_event(result)

    def on_complete(self) -> None:
        self.owner._finish_results()

    def on_error(self, result: asr.RecognitionResult) -> None:
        message = getattr(result, "message", None) or "Aliyun ASR stream failed"
        code = getattr(result, "code", None) or getattr(result, "status_code", None)
        if code is not None:
            message = f"Aliyun ASR {code}: {message}"
        self.owner._fail_results(RuntimeError(message))

    def on_close(self) -> None:
        self.owner._finish_results()


class AliyunSpeechStream(SpeechStream):
    """Alibaba Cloud Model Studio Qwen Audio streaming ASR adapter."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._result_queue: asyncio.Queue[SpeechResult | Exception | None] = asyncio.Queue()
        self._recognition: asr.Recognition | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._segment_sequence = 0
        self._active_segment_id: str | None = None
        self._started = False
        self._closed = False
        self._results_finished = False

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        if self._started or self._closed:
            raise RuntimeError("speech stream already started")
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required")
        if not self.settings.aliyun_bailian_workspace_id:
            raise RuntimeError("ALIYUN_BAILIAN_WORKSPACE_ID is required")
        AudioConfig.model_validate(audio.model_dump())
        if audio.encoding != "linear16":
            raise ValueError("AliyunSpeechStream currently requires LINEAR16/PCM audio")
        if audio.channels != 1:
            raise ValueError("AliyunSpeechStream currently requires mono audio")

        self._loop = asyncio.get_running_loop()
        dashscope.api_key = self.settings.dashscope_api_key
        dashscope.base_websocket_api_url = _asr_websocket_url(self.settings)

        callback = _RecognitionCallback(self)
        recognition_options = {
            "model": self.settings.aliyun_asr_model,
            "format": "pcm",
            "sample_rate": audio.sample_rate_hz,
            "language_hints": [language.split("-")[0]],
            "semantic_punctuation_enabled": (
                self.settings.aliyun_asr_semantic_punctuation_enabled
            ),
            "max_sentence_silence": self.settings.aliyun_asr_max_sentence_silence_ms,
            "multi_threshold_mode_enabled": (
                self.settings.aliyun_asr_multi_threshold_mode_enabled
            ),
            "heartbeat": True,
            "callback": callback,
        }
        if self.settings.aliyun_asr_speech_noise_threshold is not None:
            recognition_options["speech_noise_threshold"] = (
                self.settings.aliyun_asr_speech_noise_threshold
            )
        if self.settings.aliyun_asr_vocabulary_id:
            recognition_options["vocabulary_id"] = self.settings.aliyun_asr_vocabulary_id
        if self.settings.aliyun_asr_vocabulary:
            recognition_options["vocabulary"] = self.settings.aliyun_asr_vocabulary

        self._recognition = asr.Recognition(**recognition_options)

        recognition = self._recognition

        def start_recognition() -> None:
            try:
                recognition.start()
            finally:
                # Cancelling to_thread does not interrupt SDK startup. If it
                # completes after close, stop any late worker/timer allocation.
                if self._closed:
                    try:
                        _stop_recognition(recognition)
                    except Exception:
                        logger.warning("Late DashScope startup cleanup failed", exc_info=True)

        try:
            await asyncio.to_thread(start_recognition)
            if self._closed:
                raise RuntimeError("speech start was cancelled")
            self._started = True
        except BaseException:
            await self.close()
            raise

    async def write(self, chunk: bytes) -> None:
        if not self._started or self._closed or self._recognition is None:
            raise RuntimeError("speech stream is not active")
        if not chunk:
            return
        await asyncio.to_thread(self._recognition.send_audio_frame, chunk)

    def results(self) -> AsyncIterator[SpeechResult]:
        return self._iterate_results()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._recognition is not None:
                await asyncio.to_thread(_stop_recognition, self._recognition)
        finally:
            self._started = False
            self._finish_results()

    def _handle_event(self, result: asr.RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return

        text = str(sentence.get("text") or "").strip()
        if not text:
            return

        is_final = asr.RecognitionResult.is_sentence_end(sentence)
        if self._active_segment_id is None:
            self._active_segment_id = self._new_segment_id()

        segment_id = self._active_segment_id
        end_offset_ms = sentence.get("end_time")
        if not isinstance(end_offset_ms, int):
            end_offset_ms = None

        speech_result = SpeechResult(
            id=segment_id,
            text=text,
            is_final=is_final,
            end_offset_ms=end_offset_ms,
        )
        self._put_result(speech_result)

        if is_final:
            self._active_segment_id = None

    def _new_segment_id(self) -> str:
        self._segment_sequence += 1
        return f"aliyun-{self._segment_sequence}"

    def _put_result(self, result: SpeechResult) -> None:
        if self._loop is not None and not self._results_finished:
            self._loop.call_soon_threadsafe(self._result_queue.put_nowait, result)

    def _fail_results(self, exc: Exception) -> None:
        if self._loop is None or self._results_finished:
            return
        self._loop.call_soon_threadsafe(self._result_queue.put_nowait, exc)
        self._finish_results()

    def _finish_results(self) -> None:
        if self._results_finished or self._loop is None:
            return
        self._results_finished = True
        self._loop.call_soon_threadsafe(self._result_queue.put_nowait, None)

    async def _iterate_results(self) -> AsyncIterator[SpeechResult]:
        while True:
            item = await self._result_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item


class AliyunTranslator(Translator):
    """Alibaba Cloud Machine Translation TranslateGeneral adapter."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None

    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        if len(text) > 5000:
            raise ValueError("Aliyun TranslateGeneral source_text exceeds 5000 characters")
        if not self.settings.alibaba_cloud_access_key_id:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_ID is required")
        if not self.settings.alibaba_cloud_access_key_secret:
            raise RuntimeError("ALIBABA_CLOUD_ACCESS_KEY_SECRET is required")

        if self._client is None:
            from alibabacloud_alimt20181012.client import Client as AlimtClient
            from alibabacloud_tea_openapi import models as open_api_models

            config = open_api_models.Config(
                access_key_id=self.settings.alibaba_cloud_access_key_id,
                access_key_secret=self.settings.alibaba_cloud_access_key_secret,
            )
            config.endpoint = self.settings.aliyun_mt_endpoint
            self._client = AlimtClient(config)

        from alibabacloud_alimt20181012 import models as alimt_models

        request = alimt_models.TranslateGeneralRequest(
            format_type="text",
            source_language=source_language.split("-")[0],
            target_language=target_language.split("-")[0],
            source_text=text,
            scene="general",
        )
        from alibabacloud_tea_util.models import RuntimeOptions

        runtime = RuntimeOptions(
            connect_timeout=3000,
            read_timeout=5000,
            autoretry=False,
        )
        response = await self._client.translate_general_with_options_async(request, runtime)
        body = response.body
        code = getattr(body, "code", None)
        # TranslateGeneral can return HTTP 200 with a business error (e.g.
        # 10009 permission denied / 10010 service not activated) and no Data.
        # Check Code before reading Data so the real cause is not replaced
        # with an unhelpful NoneType AttributeError.
        # The API can encode Code as "200"; the SDK's from_map preserves
        # that string even though its annotation says int.
        if str(code) != "200":
            message = getattr(body, "message", None) or "missing or non-success business Code"
            request_id = getattr(body, "request_id", None) or "unknown"
            raise RuntimeError(f"Aliyun MT code {code}: {message} (request_id={request_id})")
        translated = getattr(getattr(body, "data", None), "translated", None)
        if not translated:
            raise RuntimeError("Aliyun Machine Translation returned an empty result")
        return translated
