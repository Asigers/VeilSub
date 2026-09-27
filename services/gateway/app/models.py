from typing import Literal

from pydantic import BaseModel, Field


class AudioConfig(BaseModel):
    encoding: Literal["linear16"] = "linear16"
    sample_rate_hz: int = 16000
    channels: int = 1


class SessionStart(BaseModel):
    type: Literal["session.start"]
    source_language: str = "ja-JP"
    target_language: str = "zh-CN"
    audio: AudioConfig = Field(default_factory=AudioConfig)


class SpeechResult(BaseModel):
    id: str
    text: str
    stability: float = 0.0
    is_final: bool = False


class SubtitleEvent(BaseModel):
    type: Literal["subtitle.partial", "subtitle.stable", "subtitle.final"]
    id: str
    source: str
    target: str | None = None
    stability: float
    is_final: bool
