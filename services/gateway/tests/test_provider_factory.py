from app.config import Settings
from app.providers.factory import create_translator
from app.providers.mock import NullTranslator


def test_m0_uses_null_translation_provider() -> None:
    translator = create_translator(Settings(veilsub_translation_provider="none"))
    assert isinstance(translator, NullTranslator)
