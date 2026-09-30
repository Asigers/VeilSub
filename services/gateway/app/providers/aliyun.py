import asyncio
from collections.abc import AsyncIterator
from typing import Any

import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult

from app.config import Settings
from app.models import AudioConfig, SpeechResult
from app.providers.base import SpeechStream, Translator


_REGION_HOSTS = {
    "cn-beijing": "{workspace}.cn-beijing.maas.aliyuncs.com",
    "ap-southeast-1": "{workspace}.ap-southeast-1.maas.aliyuncs.com",
}


class _RecognitionCallback(RecognitionCallback):
    def __init__(self, owner: "AliyunSpeechStream") -> None:
        self.owner = owner

    def on_open(self) -> None:
        return None

    def on_event(self, result: RecognitionResult) -> None:
        self.owner._handle_event(result)

    def on_complete(self) -> None:
        self.owner._finish_results()

    def on_error(self, result: RecognitionResult) -> None:
        message = getattr(result, "message", None) or "Aliyun ASR stream failed"
        self.owner._fail_results(RuntimeError(message))

    def on_close(self) -> None:
        return None


class AliyunSpeechStream(SpeechStream):
    """Alibaba Cloud Model Studio Qwen Audio streaming ASR adapter."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._result_queue: asyncio.Queue[SpeechResult | Exception | None] = asyncio.Queue()
        self._recognition: Recognition | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._segment_sequence = 0
        self._active_segment_id: str | None = None
        self._started = False
        self._closed = False
        self._results_finished = False

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        if self._started:
            raise RuntimeError("speech stream already started")
        if not self.settings.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required")
        if not self.settings.aliyun_bailian_workspace_id:
            raise RuntimeError("ALIYUN_BAILIAN_WORKSPACE_ID is required")
        if audio.encoding != "linear16":
            raise ValueError("AliyunSpeechStream currently requires LINEAR16/PCM audio")
        if audio.channels != 1:
            raise ValueError("AliyunSpeechStream currently requires mono audio")

        self._loop = asyncio.get_running_loop()
        dashscope.api_key = self.settings.dashscope_api_key
        host = _REGION_HOSTS[self.settings.aliyun_bailian_region].format(
            workspace=self.settings.aliyun_bailian_workspace_id
        )
        dashscope.base_websocket_api_url = f"wss://{host}/api-ws/v1/inference"

        callback = _RecognitionCallback(self)
        self._recognition = Recognition(
            model=self.settings.aliyun_asr_model,
            format="pcm",
            sample_rate=audio.sample_rate_hz,
            language_hints=[language.split("-")[0]],
            semantic_punctuation_enabled=False,
            heartbeat=True,
            callback=callback,
        )

        await asyncio.to_thread(self._recognition.start)
        self._started = True

    async def write(self, chunk: bytes) -> None:
        if not self._started or self._closed or self._recognition is None:
            raise RuntimeError("speech stream is not active")
        if not chunk:
            return
        await asyncio.to_thread(self._recognition.send_audio_frame, chunk)

    def results(self) -> AsyncIterator[SpeechResult]:
        return self._iterate_results()

    async def close(self) -> None:
        if not self._started or self._closed:
            return

        self._closed = True
        if self._recognition is not None:
            try:
                await asyncio.to_thread(self._recognition.stop)
            finally:
                self._finish_results()

    def _handle_event(self, result: RecognitionResult) -> None:
        sentence = result.get_sentence()
        if not isinstance(sentence, dict):
            return

        text = str(sentence.get("text") or "").strip()
        if not text:
            return

        is_final = RecognitionResult.is_sentence_end(sentence)
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
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._result_queue.put_nowait, result)

    def _fail_results(self, exc: Exception) -> None:
        if self._loop is None:
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
        return await asyncio.to_thread(
            self._translate_sync,
            text,
            source_language,
            target_language,
        )

    def _translate_sync(
        self,
        text: str,
        source_language: str,
        target_language: str,
    ) -> str:
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
        response = self._client.translate_general(request)
        translated = response.body.data.translated
        if not translated:
            raise RuntimeError("Aliyun Machine Translation returned an empty result")
        return translated
