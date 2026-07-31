from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def load_runtime_settings(settings_file: str | None) -> None:
    if not settings_file:
        return

    path = Path(settings_file)
    if not path.is_file():
        return

    for key, value in dotenv_values(path).items():
        if value is not None:
            os.environ[key] = value


def main() -> None:
    load_runtime_settings(os.environ.get("TASKO_SETTINGS_FILE"))

    if os.environ.get("AI_BACKEND") == "openclaw_codex":
        subprocess.run(
            [sys.executable, "-m", "app.core.openclaw_state"],
            check=True,
        )

    if len(sys.argv) < 2:
        raise SystemExit("API command is required")

    os.execvp(sys.argv[1], sys.argv[1:])


if __name__ == "__main__":
    main()
