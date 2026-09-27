from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    veilsub_env: str = "development"
    veilsub_speech_provider: Literal["mock", "google"] = "mock"
    veilsub_translation_provider: Literal["mock", "google"] = "mock"
    veilsub_partial_threshold: float = 0.75
    veilsub_translate_threshold: float = 0.85

    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    google_speech_recognizer: str = "_"


@lru_cache
def get_settings() -> Settings:
    return Settings()
