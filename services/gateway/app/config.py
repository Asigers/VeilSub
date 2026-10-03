from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        env_ignore_empty=True,
    )

    veilsub_env: str = "development"
    veilsub_speech_provider: Literal["mock", "aliyun"] = "mock"
    veilsub_translation_provider: Literal["none", "mock", "aliyun"] = "none"
    veilsub_translation_timeout_seconds: float = Field(default=2.5, gt=0, allow_inf_nan=False)
    veilsub_translation_max_concurrency: int = Field(default=4, ge=1)
    veilsub_translation_max_qps: int = Field(default=20, ge=1)
    veilsub_translation_cache_size: int = Field(default=256, ge=0)

    dashscope_api_key: str = ""
    aliyun_bailian_workspace_id: str = ""
    aliyun_bailian_region: Literal["cn-beijing", "ap-southeast-1"] = "cn-beijing"
    aliyun_asr_model: str = "qwen-audio-3.0-asr-flash-streaming"
    aliyun_asr_semantic_punctuation_enabled: bool = False
    aliyun_asr_max_sentence_silence_ms: int = 1300
    aliyun_asr_multi_threshold_mode_enabled: bool = False
    aliyun_asr_speech_noise_threshold: float | None = None
    aliyun_asr_vocabulary_id: str = ""
    aliyun_asr_vocabulary: dict[str, int] = Field(default_factory=dict)

    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    aliyun_mt_endpoint: str = "mt.cn-hangzhou.aliyuncs.com"

    @field_validator("aliyun_asr_max_sentence_silence_ms")
    @classmethod
    def validate_max_sentence_silence(cls, value: int) -> int:
        if not 200 <= value <= 6000:
            raise ValueError("ALIYUN_ASR_MAX_SENTENCE_SILENCE_MS must be within 200..6000")
        return value

    @field_validator("aliyun_asr_speech_noise_threshold")
    @classmethod
    def validate_speech_noise_threshold(cls, value: float | None) -> float | None:
        if value is not None and not -1.0 <= value <= 1.0:
            raise ValueError("ALIYUN_ASR_SPEECH_NOISE_THRESHOLD must be within -1.0..1.0")
        return value

    @field_validator("aliyun_asr_vocabulary")
    @classmethod
    def validate_vocabulary(cls, value: dict[str, int]) -> dict[str, int]:
        if len(value) > 2000:
            raise ValueError("ALIYUN_ASR_VOCABULARY cannot contain more than 2000 hotwords")

        super_hotwords = 0
        for word, weight in value.items():
            if not word.strip():
                raise ValueError("ALIYUN_ASR_VOCABULARY contains an empty hotword")
            if weight not in {1, 2, 3, 4, 5, 50}:
                raise ValueError("hotword weights must be 1..5 or 50")
            if weight == 50:
                super_hotwords += 1

        if super_hotwords > 50:
            raise ValueError("ALIYUN_ASR_VOCABULARY supports at most 50 weight-50 hotwords")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
