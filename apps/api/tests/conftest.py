import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[None]:
    """Keep backend tests away from the developer's persistent settings."""

    original_environment = os.environ.copy()
    original_env_file = Settings.model_config.get("env_file")

    monkeypatch.setenv("TASKO_SETTINGS_FILE", str(tmp_path / "settings.env"))
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()

    try:
        yield
    finally:
        get_settings.cache_clear()
        Settings.model_config["env_file"] = original_env_file
        os.environ.clear()
        os.environ.update(original_environment)
