import pytest
from pydantic import ValidationError

from app.config import Settings


def test_qwen_asr_tuning_defaults() -> None:
    settings = Settings()
    assert settings.aliyun_asr_semantic_punctuation_enabled is False
    assert settings.aliyun_asr_max_sentence_silence_ms == 1300
    assert settings.aliyun_asr_multi_threshold_mode_enabled is False
    assert settings.aliyun_asr_speech_noise_threshold is None


@pytest.mark.parametrize("value", [199, 6001])
def test_sentence_silence_out_of_range_is_rejected(value: int) -> None:
    with pytest.raises(ValidationError):
        Settings(aliyun_asr_max_sentence_silence_ms=value)


@pytest.mark.parametrize("value", [-1.1, 1.1])
def test_noise_threshold_out_of_range_is_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        Settings(aliyun_asr_speech_noise_threshold=value)



def test_hotword_configuration_accepts_supported_weights() -> None:
    settings = Settings(
        aliyun_asr_vocabulary={"山田": 3, "VeilSub": 50},
        aliyun_asr_vocabulary_id="vocab-123",
    )
    assert settings.aliyun_asr_vocabulary["山田"] == 3
    assert settings.aliyun_asr_vocabulary["VeilSub"] == 50
    assert settings.aliyun_asr_vocabulary_id == "vocab-123"


def test_hotword_configuration_rejects_invalid_weight() -> None:
    with pytest.raises(ValidationError):
        Settings(aliyun_asr_vocabulary={"invalid": 6})


def test_hotword_configuration_limits_super_hotwords() -> None:
    vocabulary = {f"word-{index}": 50 for index in range(51)}
    with pytest.raises(ValidationError):
        Settings(aliyun_asr_vocabulary=vocabulary)
