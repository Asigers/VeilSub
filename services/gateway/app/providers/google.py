import asyncio
import contextlib
import inspect
from collections.abc import AsyncIterator
from typing import Any

from app.config import Settings
from app.models import AudioConfig, SpeechResult
from app.providers.base import SpeechStream, Translator

_MAX_AUDIO_REQUEST_BYTES = 14_000


class GoogleSpeechStream(SpeechStream):
    """Streaming Speech-to-Text V2 / Chirp 3 adapter."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._result_queue: asyncio.Queue[SpeechResult | Exception | None] = asyncio.Queue()
        self._stream_task: asyncio.Task[None] | None = None
        self._client: Any = None
        self._started = False
        self._closed = False
        self._sequence = 0
        self._language = ""
        self._audio: AudioConfig | None = None

    async def start(self, *, language: str, audio: AudioConfig) -> None:
        if self._started:
            raise RuntimeError("speech stream already started")
        if not self.settings.google_cloud_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")
        if self.settings.google_cloud_location == "global":
            raise RuntimeError(
                "Chirp 3 does not use the global location; set GOOGLE_CLOUD_LOCATION "
                "to us, eu, asia-northeast1, or another supported Chirp 3 region"
            )
        if audio.encoding != "linear16":
            raise ValueError("GoogleSpeechStream currently requires LINEAR16 audio")
        if audio.channels != 1:
            raise ValueError("GoogleSpeechStream currently requires mono audio")

        self._language = language
        self._audio = audio
        self._started = True
        self._client = self._create_client()
        self._stream_task = asyncio.create_task(self._run(), name="google-speech-stream")

    async def write(self, chunk: bytes) -> None:
        if not self._started or self._closed:
            raise RuntimeError("speech stream is not active")
        if not chunk:
            return

        for offset in range(0, len(chunk), _MAX_AUDIO_REQUEST_BYTES):
            await self._audio_queue.put(chunk[offset : offset + _MAX_AUDIO_REQUEST_BYTES])

    def results(self) -> AsyncIterator[SpeechResult]:
        return self._iterate_results()

    async def close(self) -> None:
        if not self._started or self._closed:
            return

        self._closed = True
        if self._stream_task and not self._stream_task.done():
            await self._audio_queue.put(None)
            try:
                await asyncio.wait_for(asyncio.shield(self._stream_task), timeout=5)
            except TimeoutError:
                self._stream_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._stream_task
            except Exception:
                # The error is surfaced through results(); close remains idempotent.
                pass

        await self._close_client()

    def _create_client(self) -> Any:
        from google.api_core.client_options import ClientOptions
        from google.cloud import speech_v2

        location = self.settings.google_cloud_location
        return speech_v2.SpeechAsyncClient(
            client_options=ClientOptions(
                api_endpoint=f"{location}-speech.googleapis.com",
                quota_project_id=self.settings.google_cloud_project,
            )
        )

    async def _request_iterator(self) -> AsyncIterator[Any]:
        from google.cloud import speech_v2

        assert self._audio is not None

        sensitivity = speech_v2.StreamingRecognitionFeatures.EndpointingSensitivity
        endpointing = {
            "standard": sensitivity.ENDPOINTING_SENSITIVITY_STANDARD,
            "short": sensitivity.ENDPOINTING_SENSITIVITY_SHORT,
            "supershort": sensitivity.ENDPOINTING_SENSITIVITY_SUPERSHORT,
        }[self.settings.google_speech_endpointing]

        recognition_config = speech_v2.RecognitionConfig(
            explicit_decoding_config=speech_v2.ExplicitDecodingConfig(
                encoding=speech_v2.ExplicitDecodingConfig.AudioEncoding.LINEAR16,
                sample_rate_hertz=self._audio.sample_rate_hz,
                audio_channel_count=self._audio.channels,
            ),
            language_codes=[self._language],
            model="chirp_3",
            features=speech_v2.RecognitionFeatures(
                enable_automatic_punctuation=True,
                profanity_filter=False,
            ),
        )
        streaming_config = speech_v2.StreamingRecognitionConfig(
            config=recognition_config,
            streaming_features=speech_v2.StreamingRecognitionFeatures(
                interim_results=True,
                endpointing_sensitivity=endpointing,
            ),
        )
        recognizer = (
            f"projects/{self.settings.google_cloud_project}"
            f"/locations/{self.settings.google_cloud_location}"
            f"/recognizers/{self.settings.google_speech_recognizer}"
        )

        yield speech_v2.StreamingRecognizeRequest(
            recognizer=recognizer,
            streaming_config=streaming_config,
        )

        while True:
            chunk = await self._audio_queue.get()
            if chunk is None:
                break
            yield speech_v2.StreamingRecognizeRequest(audio=chunk)

    async def _run(self) -> None:
        try:
            stream = await self._client.streaming_recognize(requests=self._request_iterator())
            async for response in stream:
                result = self._convert_response(response)
                if result is not None:
                    await self._result_queue.put(result)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self._result_queue.put(exc)
        finally:
            await self._result_queue.put(None)

    def _convert_response(self, response: Any) -> SpeechResult | None:
        usable = [
            result
            for result in response.results
            if result.alternatives and result.alternatives[0].transcript
        ]
        if not usable:
            return None

        text = "".join(result.alternatives[0].transcript for result in usable).strip()
        if not text:
            return None

        is_final = all(result.is_final for result in usable)
        stability = (
            1.0
            if is_final
            else min(
                1.0 if result.is_final else float(result.stability)
                for result in usable
            )
        )

        self._sequence += 1
        return SpeechResult(
            id=f"google-{self._sequence}",
            text=text,
            stability=stability,
            is_final=is_final,
        )

    async def _iterate_results(self) -> AsyncIterator[SpeechResult]:
        while True:
            item = await self._result_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    async def _close_client(self) -> None:
        if self._client is None:
            return

        close = getattr(getattr(self._client, "transport", None), "close", None)
        if close is None:
            return

        result = close()
        if inspect.isawaitable(result):
            with contextlib.suppress(Exception):
                await result


class GoogleTranslator(Translator):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None

    async def translate(
        self,
        text: str,
        *,
        source_language: str,
        target_language: str,
    ) -> str:
        if not self.settings.google_cloud_project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")

        from google.cloud import translate_v3

        if self.client is None:
            self.client = translate_v3.TranslationServiceAsyncClient()

        response = await self.client.translate_text(
            request={
                "parent": f"projects/{self.settings.google_cloud_project}/locations/global",
                "contents": [text],
                "mime_type": "text/plain",
                "source_language_code": source_language.split("-")[0],
                "target_language_code": target_language.split("-")[0],
            }
        )
        return response.translations[0].translated_text
