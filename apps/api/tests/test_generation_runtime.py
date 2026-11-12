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
    # The vacancy is parsed by the cheaper screening model of the same provider.
    assert snapshot.parsing_model == "openai/gpt-6-luna"
    assert snapshot.engine_version


def test_execution_snapshot_uses_the_document_model_of_the_active_provider() -> None:
    source = settings(
        ai_backend_mode="anthropic_api",
        anthropic_api_model="claude-sonnet-5-5",
        anthropic_api_effort="medium",
        job_screening_model="openai/gpt-6-luna",
    )
    source.document_model_value = lambda: "anthropic/claude-opus-5-5"

    snapshot = snapshot_generation_execution(source)

    assert snapshot.model == "anthropic/claude-opus-5-5"
    # A screening model saved for another provider falls back to this provider's default.
    assert snapshot.parsing_model == "anthropic/claude-haiku-5-5"


def test_runtime_reports_each_backend_independently() -> None:
    paths = {"openclaw": "/usr/bin/openclaw"}
    reports = probe_both_generation_backends(settings(), which=paths.get)

    assert reports["openai_api"].available is True
    assert reports["openclaw_codex"].available is True


def test_runtime_does_not_treat_one_ready_backend_as_the_other() -> None:
    reports = probe_both_generation_backends(
        settings(openai_api_key=""),
        which={}.get,
    )

    assert reports["openai_api"].available is False
    assert reports["openclaw_codex"].available is False
    assert reports["openai_api"].dependencies[0].name == "openai_api"
    assert reports["openclaw_codex"].dependencies[0].name == "openclaw"
