"""Regression tests must never inherit real local cloud configuration or incur charges."""

import os

import pytest

from app.config import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_cloud_configuration(monkeypatch, tmp_path):
    # Settings reads .env relative to cwd. A fresh empty directory prevents tests
    # from using the developer's real credentials or changed VAD configuration.
    monkeypatch.chdir(tmp_path)
    for key in list(os.environ):
        if key.lower() in Settings.model_fields:
            monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
