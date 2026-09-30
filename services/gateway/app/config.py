from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    veilsub_env: str = "development"
    veilsub_speech_provider: Literal["mock", "aliyun"] = "mock"
    veilsub_translation_provider: Literal["none", "mock", "aliyun"] = "none"

    dashscope_api_key: str = ""
    aliyun_bailian_workspace_id: str = ""
    aliyun_bailian_region: Literal["cn-beijing", "ap-southeast-1"] = "cn-beijing"
    aliyun_asr_model: str = "qwen-audio-3.0-asr-flash-streaming"

    alibaba_cloud_access_key_id: str = ""
    alibaba_cloud_access_key_secret: str = ""
    aliyun_mt_endpoint: str = "mt.cn-hangzhou.aliyuncs.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
