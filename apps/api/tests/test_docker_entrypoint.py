import os
from pathlib import Path

from app.core.docker_entrypoint import load_runtime_settings


def test_load_runtime_settings_overrides_container_environment(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings_file = tmp_path / "settings.env"
    settings_file.write_text(
        'AI_BACKEND=openai_api\nOPENAI_API_KEY="literal$(not-a-command)"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AI_BACKEND", "openclaw_codex")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    load_runtime_settings(str(settings_file))

    assert os.environ["AI_BACKEND"] == "openai_api"
    assert os.environ["OPENAI_API_KEY"] == "literal$(not-a-command)"
