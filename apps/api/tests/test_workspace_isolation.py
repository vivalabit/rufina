import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    "compose_project",
    (
        "tasko",
        "tasko-screenshots",
        "tasko-production",
        "workspace-e2e",
        "tasko-workspace-e2e-",
        "tasko-workspace-e2e.other",
    ),
)
def test_e2e_runner_refuses_projects_outside_e2e_namespace(
    compose_project: str,
) -> None:
    environment = os.environ.copy()
    environment["E2E_COMPOSE_PROJECT"] = compose_project

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "run_workspace_e2e.sh")],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "must be tasko-workspace-e2e" in result.stderr


@pytest.mark.parametrize(
    "compose_project",
    ("tasko-workspace-e2e", "tasko-workspace-e2e-worker_2"),
)
def test_e2e_runner_accepts_only_e2e_project_namespace(
    tmp_path: Path,
    compose_project: str,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command in ("docker", "python3"):
        executable = fake_bin / command
        executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        executable.chmod(0o755)

    environment = os.environ.copy()
    environment["E2E_COMPOSE_PROJECT"] = compose_project
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "run_workspace_e2e.sh")],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_compose_overrides_declare_isolated_projects_and_databases() -> None:
    screenshot_compose = (
        REPO_ROOT / "infra" / "screenshots" / "compose.screenshots.yaml"
    ).read_text(encoding="utf-8")
    e2e_compose = (REPO_ROOT / "tests" / "e2e" / "compose.e2e.yaml").read_text(encoding="utf-8")
    screenshot_runner = (REPO_ROOT / "scripts" / "screenshot_workspace.sh").read_text(
        encoding="utf-8"
    )

    assert screenshot_compose.startswith("name: tasko-screenshots\n")
    assert "/tasko_screenshots" in screenshot_compose
    assert "POSTGRES_DB: tasko_screenshots" in screenshot_compose
    assert "TASKO_SETTINGS_FILE: /dev/null" in screenshot_compose
    assert "AI_BACKEND: openai_api" in screenshot_compose
    assert "OPENAI_API_KEY: screenshot-fixture-disabled" in screenshot_compose
    for feature in ("AI_MATCH", "ASSISTANT", "RESUME_IMPORT", "RESUME_TAILORING"):
        assert f'OPENCLAW_{feature}_ENABLED: "false"' in screenshot_compose
    assert 'BRIGHTDATA_API_KEY: ""' in screenshot_compose

    assert e2e_compose.startswith("name: tasko-workspace-e2e\n")
    assert "/tasko_e2e" in e2e_compose
    assert "POSTGRES_DB: tasko_e2e" in e2e_compose
    assert "TASKO_SETTINGS_FILE: /dev/null" in e2e_compose
    assert "AI_BACKEND: openclaw_codex" in e2e_compose
    assert 'OPENAI_API_KEY: ""' in e2e_compose
    assert 'BRIGHTDATA_API_KEY: ""' in e2e_compose

    for isolated_volume in (
        "e2e-openclaw-home:/root/.openclaw",
        "e2e-openclaw-shared-state:/root/.openclaw-shared-state",
        "e2e-openclaw-state:/root/.openclaw/state",
        "e2e-openclaw-npm:${HOME}/.openclaw/npm",
        "e2e-openclaw-workspace:${HOME}/.openclaw/workspace-rufina-assistant",
        "e2e-openclaw-agent:${HOME}/.openclaw/agents/rufina-assistant",
    ):
        assert isolated_volume in e2e_compose

    assert "SCREENSHOT_POSTGRES_PORT:-15433" in screenshot_runner
    assert '"${POSTGRES_PORT}" == "5432" || "${POSTGRES_PORT}" == "5433"' in screenshot_runner
    assert screenshot_runner.count('"${compose[@]}" down --volumes --remove-orphans') == 2


def test_screenshot_up_recreates_only_screenshot_project_volumes(tmp_path: Path) -> None:
    trace_file = tmp_path / "docker.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "${TRACE_FILE:?}"\n',
        encoding="utf-8",
    )
    docker.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["TRACE_FILE"] = str(trace_file)

    result = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "screenshot_workspace.sh"), "up"],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    commands = trace_file.read_text(encoding="utf-8").splitlines()
    assert len(commands) == 3
    assert all("--project-name tasko-screenshots" in command for command in commands)
    assert commands[0].endswith("down --volumes --remove-orphans")
    assert commands[1].endswith("up --detach --build --wait")
    assert commands[2].endswith(
        "exec -T api python /workspace/scripts/seed_screenshot_workspace.py"
    )
