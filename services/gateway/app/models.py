from typing import Literal

from pydantic import BaseModel, Field


class AudioConfig(BaseModel):
    encoding: Literal["linear16"] = "linear16"
    sample_rate_hz: Literal[16000] = 16000
    channels: Literal[1] = 1


class SessionStart(BaseModel):
    type: Literal["session.start"]
    source_language: str = "ja-JP"
    target_language: str = "zh-CN"
    audio: AudioConfig = Field(default_factory=AudioConfig)


class SpeechResult(BaseModel):
    id: str
    text: str
    is_final: bool = False
    end_offset_ms: int | None = None


class SubtitleEvent(BaseModel):
    type: Literal["subtitle.partial", "subtitle.final", "subtitle.translation"]
    id: str
    revision: int
    source: str
    target: str | None = None
    is_final: bool
    end_offset_ms: int | None = None
