from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api import settings as settings_api
from app.api.settings import (
    format_env_value,
    mask_secret,
    settings_file_path,
    upsert_env_value,
)
from app.core.settings import Settings, get_settings
from app.main import app


def test_mask_secret_keeps_only_edges() -> None:
    assert mask_secret("abcd1234wxyz") == "abcd****wxyz"
    assert mask_secret("short") == "****"
    assert mask_secret("") == ""


def test_format_env_value_quotes_values_that_need_it() -> None:
    assert format_env_value("plain_key-123") == "plain_key-123"
    assert format_env_value("key with spaces") == '"key with spaces"'
    assert format_env_value('key"with\\chars') == '"key\\"with\\\\chars"'
    assert format_env_value("line-one\nline-two") == '"line-one\\nline-two"'


def test_upsert_env_value_preserves_other_lines(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "DATABASE_URL=postgresql://example\n"
        "BRIGHTDATA_API_KEY=old-key\n"
        "# BRIGHTDATA_API_KEY=commented\n",
        encoding="utf-8",
    )

    upsert_env_value(env_path, "BRIGHTDATA_API_KEY", "new-key")

    assert env_path.read_text(encoding="utf-8") == (
        "DATABASE_URL=postgresql://example\n"
        "BRIGHTDATA_API_KEY=new-key\n"
        "# BRIGHTDATA_API_KEY=commented\n"
    )


def test_settings_file_path_supports_persistent_container_storage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.delenv("TASKO_SETTINGS_FILE", raising=False)

    assert settings_file_path() == tmp_path / ".env"

    runtime_path = tmp_path / "runtime" / "settings.env"
    monkeypatch.setenv("TASKO_SETTINGS_FILE", str(runtime_path))

    assert settings_file_path() == runtime_path


def test_brightdata_api_key_cannot_be_read_back(monkeypatch) -> None:
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "full-secret-key")
    get_settings.cache_clear()
    client = TestClient(app)

    try:
        response = client.get("/settings/brightdata-key")
        settings_response = client.get("/settings")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 404
    assert settings_response.status_code == 200
    assert settings_response.json()["brightdata_api_key_preview"] == "full****-key"
    assert "full-secret-key" not in settings_response.text


def test_ai_backend_mode_accepts_only_supported_transports() -> None:
    settings = Settings(
        ai_backend_mode="openai_api",
        openai_api_key="test-key",
        openai_api_base_url="https://api.openai.test/v1",
        openai_api_model="gpt-test",
    )

    assert settings.ai_backend_mode == "openai_api"
    assert settings.openai_api_key == "test-key"
    assert Settings().ai_backend_mode == "openclaw_codex"

    with pytest.raises(ValidationError):
        Settings(ai_backend_mode="unsupported")

    with pytest.raises(ValidationError, match="OPENAI_API_KEY is required"):
        Settings(ai_backend_mode="openai_api", openai_api_key="")


def test_ai_backend_uses_canonical_env_and_direct_api_parameters(monkeypatch) -> None:
    monkeypatch.setenv("AI_BACKEND", "openai_api")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "high")
    monkeypatch.setenv("OPENAI_API_TIMEOUT_SECONDS", "75")
    monkeypatch.setenv("OPENAI_API_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("OPENAI_API_RETRY_BACKOFF_SECONDS", "1.25")

    settings = Settings()

    assert settings.ai_backend_mode == "openai_api"
    assert settings.ai_reasoning_for("off") == "high"
    assert settings.ai_timeout_for(30) == 75
    assert settings.ai_max_attempts_for(1) == 3
    assert settings.ai_retry_backoff_for(0) == 1.25


def test_job_screening_settings_have_independent_defaults() -> None:
    settings = Settings()

    assert settings.job_screening_model == "openai/gpt-5.6-luna"
    assert settings.job_screening_reasoning == "off"
    assert settings.job_screening_batch_size == 10
    assert settings.job_screening_timeout_seconds == 60
    assert settings.job_screening_max_attempts == 2
    assert settings.job_screening_max_description_chars == 12_000
    assert settings.openclaw_ai_match_model == "openai/gpt-5.6-terra"
    assert settings.ai_match_model_value() == "openai/gpt-5.6-terra"
    assert settings.ai_match_reasoning_value() == "off"
    assert settings.ai_match_batch_size_value() == 1


def test_job_screening_settings_use_dedicated_environment_variables(monkeypatch) -> None:
    monkeypatch.setenv("JOB_SCREENING_MODEL", "openai/gpt-screening")
    monkeypatch.setenv("JOB_SCREENING_REASONING", "low")
    monkeypatch.setenv("JOB_SCREENING_BATCH_SIZE", "25")
    monkeypatch.setenv("JOB_SCREENING_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("JOB_SCREENING_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("JOB_SCREENING_MAX_DESCRIPTION_CHARS", "18000")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-full-match")

    settings = Settings()

    assert settings.job_screening_model == "openai/gpt-screening"
    assert settings.job_screening_reasoning == "low"
    assert settings.job_screening_batch_size == 25
    assert settings.job_screening_timeout_seconds == 45
    assert settings.job_screening_max_attempts == 3
    assert settings.job_screening_max_description_chars == 18_000
    assert settings.openai_api_model == "gpt-full-match"


def test_settings_never_returns_full_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-openai-key")
    get_settings.cache_clear()

    try:
        response = TestClient(app).get("/settings")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["openai_api_key_configured"] is True
    assert response.json()["openai_api_key_preview"] == "sk-s****-key"
    assert "sk-secret-openai-key" not in response.text
    assert "openai_api_key" not in response.json()


def test_ai_settings_update_is_partial_and_refreshes_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BRIGHTDATA_API_KEY=bright-existing-key\n"
        "AI_BACKEND=openclaw_codex\n"
        "OPENAI_API_KEY=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "bright-existing-key")
    monkeypatch.setenv("AI_BACKEND", "openclaw_codex")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-5.6-terra")
    monkeypatch.setenv("OPENAI_API_REASONING_EFFORT", "medium")
    monkeypatch.setenv("OPENAI_API_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("OPENAI_API_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("OPENAI_API_RETRY_BACKOFF_SECONDS", "0.8")
    get_settings.cache_clear()
    assert get_settings().ai_backend_mode == "openclaw_codex"

    try:
        response = TestClient(app).put(
            "/settings",
            json={
                "ai_backend": "openai_api",
                "openai_api_key": "sk-new-secret-key",
                "openai_api_model": "gpt-5.6-terra",
                "openai_api_reasoning_effort": "low",
                "openai_api_timeout_seconds": 90,
                "openai_api_max_attempts": 3,
                "openai_api_retry_backoff_seconds": 1.5,
            },
        )

        refreshed = get_settings()
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["ai_backend"] == "openai_api"
    assert response.json()["openai_api_key_configured"] is True
    assert response.json()["openai_api_key_preview"] == "sk-n****-key"
    assert "sk-new-secret-key" not in response.text
    assert refreshed.ai_backend_mode == "openai_api"
    assert refreshed.openai_api_reasoning_effort == "low"
    assert refreshed.openai_api_timeout_seconds == 90
    assert "BRIGHTDATA_API_KEY=bright-existing-key" in env_path.read_text(encoding="utf-8")


def test_job_screening_settings_api_updates_only_screening_configuration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENAI_API_MODEL=gpt-full-match\n"
        "OPENCLAW_AI_MATCH_MODEL=openai/gpt-full-match\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("AI_BACKEND", "openclaw_codex")
    monkeypatch.setenv("OPENAI_API_MODEL", "gpt-full-match")
    monkeypatch.setenv("OPENCLAW_AI_MATCH_MODEL", "openai/gpt-full-match")
    monkeypatch.setenv("JOB_SCREENING_MODEL", "openai/gpt-5-mini")
    monkeypatch.setenv("JOB_SCREENING_REASONING", "none")
    monkeypatch.setenv("JOB_SCREENING_BATCH_SIZE", "10")
    monkeypatch.setenv("JOB_SCREENING_TIMEOUT_SECONDS", "60")
    monkeypatch.setenv("JOB_SCREENING_MAX_ATTEMPTS", "2")
    monkeypatch.setenv("JOB_SCREENING_MAX_DESCRIPTION_CHARS", "12000")
    get_settings.cache_clear()

    try:
        response = TestClient(app).put(
            "/settings",
            json={
                "job_screening_model": "openai/gpt-screening",
                "job_screening_reasoning": "low",
                "job_screening_batch_size": 20,
                "job_screening_timeout_seconds": 75,
                "job_screening_max_attempts": 3,
                "job_screening_max_description_chars": 16_000,
            },
        )
        refreshed = get_settings()
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["job_screening_model"] == "openai/gpt-screening"
    assert response.json()["job_screening_reasoning"] == "low"
    assert response.json()["job_screening_batch_size"] == 20
    assert response.json()["job_screening_timeout_seconds"] == 75
    assert response.json()["job_screening_max_attempts"] == 3
    assert response.json()["job_screening_max_description_chars"] == 16_000
    assert refreshed.openai_api_model == "gpt-full-match"
    assert refreshed.openclaw_ai_match_model == "openai/gpt-full-match"
    env_text = env_path.read_text(encoding="utf-8")
    assert "OPENAI_API_MODEL=gpt-full-match" in env_text
    assert "OPENCLAW_AI_MATCH_MODEL=openai/gpt-full-match" in env_text
    assert 'JOB_SCREENING_MODEL="openai/gpt-screening"' in env_text


def test_ai_match_settings_api_persists_backend_neutral_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("AI_BACKEND", "openclaw_codex")
    monkeypatch.setenv("AI_MATCH_MODEL", "openai/gpt-5.6-terra")
    monkeypatch.setenv("AI_MATCH_REASONING", "low")
    monkeypatch.setenv("AI_MATCH_BATCH_SIZE", "1")
    monkeypatch.setenv("AI_MATCH_TIMEOUT_SECONDS", "120")
    monkeypatch.setenv("AI_MATCH_MAX_ATTEMPTS", "2")
    get_settings.cache_clear()

    try:
        response = TestClient(app).put(
            "/settings",
            json={
                "ai_match_model": "openai/gpt-main",
                "ai_match_reasoning": "high",
                "ai_match_batch_size": 4,
                "ai_match_timeout_seconds": 180,
                "ai_match_max_attempts": 3,
            },
        )
        refreshed = get_settings()
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["ai_match_model"] == "openai/gpt-main"
    assert response.json()["ai_match_reasoning"] == "high"
    assert response.json()["ai_match_batch_size"] == 4
    assert response.json()["ai_match_timeout_seconds"] == 180
    assert response.json()["ai_match_max_attempts"] == 3
    assert refreshed.ai_match_model_value() == "openai/gpt-main"
    assert refreshed.ai_match_batch_size_value() == 4
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'AI_MATCH_MODEL="openai/gpt-main"' in env_text
    assert "AI_MATCH_REASONING=high" in env_text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("job_screening_model", "  "),
        ("job_screening_reasoning", "adaptive"),
        ("job_screening_batch_size", 0),
        ("job_screening_timeout_seconds", 9),
        ("job_screening_max_attempts", 5),
        ("job_screening_max_description_chars", 999),
    ],
)
def test_job_screening_settings_api_rejects_invalid_values(
    monkeypatch,
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    get_settings.cache_clear()

    try:
        response = TestClient(app).put("/settings", json={field: value})
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert not (tmp_path / ".env").exists()


def test_openai_api_cannot_be_enabled_without_a_key(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("AI_BACKEND", "openclaw_codex")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()

    try:
        response = TestClient(app).put(
            "/settings",
            json={"ai_backend": "openai_api"},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert response.json()["detail"] == (
        "Configure an OpenAI API key before enabling openai_api"
    )
    assert not (tmp_path / ".env").exists()


def test_rejected_openai_key_is_not_echoed(monkeypatch, tmp_path: Path) -> None:
    rejected_key = "sk-" + "secret" * 700
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("AI_BACKEND", "openclaw_codex")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()

    try:
        response = TestClient(app).put(
            "/settings",
            json={"openai_api_key": rejected_key},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 422
    assert response.json()["detail"] == "OpenAI API key is too long"
    assert rejected_key not in response.text


def test_brightdata_only_update_keeps_active_ai_configuration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings_api, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("BRIGHTDATA_API_KEY", "old-bright-key")
    monkeypatch.setenv("AI_BACKEND", "openai_api")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-existing-key")
    get_settings.cache_clear()

    try:
        response = TestClient(app).put(
            "/settings",
            json={"brightdata_api_key": "new-bright-key"},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json()["has_brightdata_api_key"] is True
    assert response.json()["ai_backend"] == "openai_api"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert "BRIGHTDATA_API_KEY=new-bright-key" in env_text
    assert "OPENAI_API_KEY" not in env_text
