from types import SimpleNamespace

from app.services.generation_runtime import (
    probe_both_generation_backends,
    snapshot_generation_execution,
)


def settings(**overrides: object) -> SimpleNamespace:
    values = {
        "ai_backend_mode": "openclaw_codex",
        "openai_api_key": "test-key",
        "openai_api_model": "gpt-6.1-sol",
        "openai_api_reasoning_effort": "medium",
        "openai_api_timeout_seconds": 120,
        "openai_api_max_attempts": 2,
        "openai_api_retry_backoff_seconds": 0.8,
        "openclaw_command": "openclaw",
        "openclaw_assistant_model": "openai/gpt-6.1-sol",
        "openclaw_assistant_thinking": "off",
        "openclaw_assistant_timeout_seconds": 180,
        "openclaw_assistant_max_attempts": 3,
        "openclaw_assistant_retry_backoff_seconds": 1.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_execution_snapshot_freezes_selected_backend_and_nonsecret_settings() -> None:
    source = settings()

    snapshot = snapshot_generation_execution(source)
    source.ai_backend_mode = "openai_api"

    assert snapshot.backend == "openclaw_codex"
    assert snapshot.model == "openai/gpt-6.1-sol"
    assert snapshot.max_attempts == 3
    assert "api_key" not in snapshot.as_dict()
    assert snapshot.upstream_sha == "c7bd494f11e792508534c1c795e24694498395c4"


def test_runtime_reports_each_backend_independently() -> None:
    paths = {
        name: f"/usr/bin/{name}"
        for name in (
            "openclaw",
            "lualatex",
            "xelatex",
            "pdftotext",
            "pdfinfo",
            "pdftoppm",
        )
    }
    reports = probe_both_generation_backends(settings(), which=paths.get)

    assert reports["openai_api"].available is True
    assert reports["openclaw_codex"].available is True


def test_runtime_does_not_treat_one_ready_backend_as_the_other() -> None:
    paths = {
        name: f"/usr/bin/{name}"
        for name in ("lualatex", "xelatex", "pdftotext", "pdfinfo", "pdftoppm")
    }
    reports = probe_both_generation_backends(
        settings(openai_api_key=""),
        which=paths.get,
    )

    assert reports["openai_api"].available is False
    assert reports["openclaw_codex"].available is False
    assert reports["openai_api"].dependencies[0].name == "openai_api"
    assert reports["openclaw_codex"].dependencies[0].name == "openclaw"
