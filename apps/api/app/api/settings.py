import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, SecretStr

from app.core.settings import REPO_ROOT, get_settings

router = APIRouter()

BRIGHTDATA_API_KEY_ENV = "BRIGHTDATA_API_KEY"
AI_BACKEND_ENV = "AI_BACKEND"
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"
OPENAI_API_MODEL_ENV = "OPENAI_API_MODEL"
OPENAI_API_REASONING_EFFORT_ENV = "OPENAI_API_REASONING_EFFORT"
OPENAI_API_TIMEOUT_SECONDS_ENV = "OPENAI_API_TIMEOUT_SECONDS"
OPENAI_API_MAX_ATTEMPTS_ENV = "OPENAI_API_MAX_ATTEMPTS"
OPENAI_API_RETRY_BACKOFF_SECONDS_ENV = "OPENAI_API_RETRY_BACKOFF_SECONDS"
AI_MATCH_MODEL_ENV = "AI_MATCH_MODEL"
AI_MATCH_REASONING_ENV = "AI_MATCH_REASONING"
AI_MATCH_BATCH_SIZE_ENV = "AI_MATCH_BATCH_SIZE"
AI_MATCH_TIMEOUT_SECONDS_ENV = "AI_MATCH_TIMEOUT_SECONDS"
AI_MATCH_MAX_ATTEMPTS_ENV = "AI_MATCH_MAX_ATTEMPTS"
JOB_SCREENING_MODEL_ENV = "JOB_SCREENING_MODEL"
JOB_SCREENING_REASONING_ENV = "JOB_SCREENING_REASONING"
JOB_SCREENING_BATCH_SIZE_ENV = "JOB_SCREENING_BATCH_SIZE"
JOB_SCREENING_TIMEOUT_SECONDS_ENV = "JOB_SCREENING_TIMEOUT_SECONDS"
JOB_SCREENING_MAX_ATTEMPTS_ENV = "JOB_SCREENING_MAX_ATTEMPTS"
JOB_SCREENING_MAX_DESCRIPTION_CHARS_ENV = "JOB_SCREENING_MAX_DESCRIPTION_CHARS"

AIBackendName = Literal["openclaw_codex", "openai_api"]
ReasoningEffort = Literal["off", "none", "low", "medium", "high", "xhigh", "max"]


class AppSettingsResponse(BaseModel):
    has_brightdata_api_key: bool
    brightdata_api_key_preview: str = ""
    ai_backend: AIBackendName
    openai_api_key_configured: bool
    openai_api_key_preview: str = ""
    openai_api_model: str
    openai_api_reasoning_effort: ReasoningEffort
    openai_api_timeout_seconds: int
    openai_api_max_attempts: int
    openai_api_retry_backoff_seconds: float
    ai_match_model: str
    ai_match_reasoning: ReasoningEffort
    ai_match_batch_size: int
    ai_match_timeout_seconds: int
    ai_match_max_attempts: int
    job_screening_model: str
    job_screening_reasoning: ReasoningEffort
    job_screening_batch_size: int
    job_screening_timeout_seconds: int
    job_screening_max_attempts: int
    job_screening_max_description_chars: int


class AppSettingsUpdateRequest(BaseModel):
    brightdata_api_key: str | None = Field(default=None, max_length=4096)
    ai_backend: AIBackendName | None = None
    openai_api_key: SecretStr | None = None
    openai_api_model: str | None = Field(default=None, max_length=256)
    openai_api_reasoning_effort: ReasoningEffort | None = None
    openai_api_timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    openai_api_max_attempts: int | None = Field(default=None, ge=1, le=4)
    openai_api_retry_backoff_seconds: float | None = Field(default=None, ge=0, le=10)
    ai_match_model: str | None = Field(default=None, max_length=256)
    ai_match_reasoning: ReasoningEffort | None = None
    ai_match_batch_size: int | None = Field(default=None, ge=1, le=100)
    ai_match_timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    ai_match_max_attempts: int | None = Field(default=None, ge=1, le=4)
    job_screening_model: str | None = Field(default=None, max_length=256)
    job_screening_reasoning: ReasoningEffort | None = None
    job_screening_batch_size: int | None = Field(default=None, ge=1, le=100)
    job_screening_timeout_seconds: int | None = Field(default=None, ge=10, le=600)
    job_screening_max_attempts: int | None = Field(default=None, ge=1, le=4)
    job_screening_max_description_chars: int | None = Field(
        default=None,
        ge=1_000,
        le=200_000,
    )


def mask_secret(value: str | None) -> str:
    if not value:
        return ""

    if len(value) <= 8:
        return "****"

    return f"{value[:4]}****{value[-4:]}"


def format_env_value(value: str) -> str:
    if not value:
        return ""

    if all(char.isalnum() or char in "-_." for char in value):
        return value

    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\r")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"'


def upsert_env_value(env_path: Path, key: str, value: str) -> None:
    upsert_env_values(env_path, {key: value})


def upsert_env_values(env_path: Path, values: dict[str, str]) -> None:
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    updated: set[str] = set()
    next_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()
        key = stripped.split("=", 1)[0].strip()
        if not stripped.startswith("#") and key in values:
            next_lines.append(f"{key}={format_env_value(values[key])}")
            updated.add(key)
        else:
            next_lines.append(line)

    next_lines.extend(
        f"{key}={format_env_value(value)}"
        for key, value in values.items()
        if key not in updated
    )

    env_path.write_text("\n".join(next_lines).rstrip() + "\n", encoding="utf-8")


def build_settings_response() -> AppSettingsResponse:
    settings = get_settings()
    brightdata_api_key = settings.brightdata_api_key or ""
    openai_api_key = settings.openai_api_key.strip()

    return AppSettingsResponse(
        has_brightdata_api_key=bool(brightdata_api_key.strip()),
        brightdata_api_key_preview=mask_secret(brightdata_api_key.strip()),
        ai_backend=settings.ai_backend_mode,
        openai_api_key_configured=bool(openai_api_key),
        openai_api_key_preview=mask_secret(openai_api_key),
        openai_api_model=settings.openai_api_model,
        openai_api_reasoning_effort=settings.openai_api_reasoning_effort,
        openai_api_timeout_seconds=settings.openai_api_timeout_seconds,
        openai_api_max_attempts=settings.openai_api_max_attempts,
        openai_api_retry_backoff_seconds=settings.openai_api_retry_backoff_seconds,
        ai_match_model=settings.ai_match_model_value(),
        ai_match_reasoning=settings.ai_match_reasoning_value(),
        ai_match_batch_size=settings.ai_match_batch_size_value(),
        ai_match_timeout_seconds=settings.ai_match_timeout_seconds_value(),
        ai_match_max_attempts=settings.ai_match_max_attempts_value(),
        job_screening_model=settings.job_screening_model,
        job_screening_reasoning=settings.normalize_reasoning_for_backend(
            settings.job_screening_reasoning
        ),
        job_screening_batch_size=settings.job_screening_batch_size,
        job_screening_timeout_seconds=settings.job_screening_timeout_seconds,
        job_screening_max_attempts=settings.job_screening_max_attempts,
        job_screening_max_description_chars=settings.job_screening_max_description_chars,
    )


@router.get("", response_model=AppSettingsResponse)
def get_app_settings() -> AppSettingsResponse:
    return build_settings_response()


@router.put("", response_model=AppSettingsResponse)
def update_app_settings(payload: AppSettingsUpdateRequest) -> AppSettingsResponse:
    current = get_settings()
    updates: dict[str, str] = {}
    submitted_openai_key = (
        payload.openai_api_key.get_secret_value().strip()
        if payload.openai_api_key is not None
        else None
    )
    if submitted_openai_key is not None and len(submitted_openai_key) > 4096:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="OpenAI API key is too long",
        )

    if payload.brightdata_api_key is not None:
        updates[BRIGHTDATA_API_KEY_ENV] = payload.brightdata_api_key.strip()
    if payload.ai_backend is not None:
        updates[AI_BACKEND_ENV] = payload.ai_backend
    if submitted_openai_key is not None:
        updates[OPENAI_API_KEY_ENV] = submitted_openai_key
    if payload.openai_api_model is not None:
        model = payload.openai_api_model.strip()
        if not model:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="OpenAI API model cannot be empty",
            )
        updates[OPENAI_API_MODEL_ENV] = model
    if payload.openai_api_reasoning_effort is not None:
        updates[OPENAI_API_REASONING_EFFORT_ENV] = payload.openai_api_reasoning_effort
    if payload.openai_api_timeout_seconds is not None:
        updates[OPENAI_API_TIMEOUT_SECONDS_ENV] = str(payload.openai_api_timeout_seconds)
    if payload.openai_api_max_attempts is not None:
        updates[OPENAI_API_MAX_ATTEMPTS_ENV] = str(payload.openai_api_max_attempts)
    if payload.openai_api_retry_backoff_seconds is not None:
        updates[OPENAI_API_RETRY_BACKOFF_SECONDS_ENV] = str(
            payload.openai_api_retry_backoff_seconds
        )
    if payload.ai_match_model is not None:
        ai_match_model = payload.ai_match_model.strip()
        if not ai_match_model:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="AI Match model cannot be empty",
            )
        updates[AI_MATCH_MODEL_ENV] = ai_match_model
    if payload.ai_match_reasoning is not None:
        updates[AI_MATCH_REASONING_ENV] = payload.ai_match_reasoning
    if payload.ai_match_batch_size is not None:
        updates[AI_MATCH_BATCH_SIZE_ENV] = str(payload.ai_match_batch_size)
    if payload.ai_match_timeout_seconds is not None:
        updates[AI_MATCH_TIMEOUT_SECONDS_ENV] = str(payload.ai_match_timeout_seconds)
    if payload.ai_match_max_attempts is not None:
        updates[AI_MATCH_MAX_ATTEMPTS_ENV] = str(payload.ai_match_max_attempts)
    if payload.job_screening_model is not None:
        screening_model = payload.job_screening_model.strip()
        if not screening_model:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Job screening model cannot be empty",
            )
        updates[JOB_SCREENING_MODEL_ENV] = screening_model
    if payload.job_screening_reasoning is not None:
        updates[JOB_SCREENING_REASONING_ENV] = payload.job_screening_reasoning
    if payload.job_screening_batch_size is not None:
        updates[JOB_SCREENING_BATCH_SIZE_ENV] = str(payload.job_screening_batch_size)
    if payload.job_screening_timeout_seconds is not None:
        updates[JOB_SCREENING_TIMEOUT_SECONDS_ENV] = str(
            payload.job_screening_timeout_seconds
        )
    if payload.job_screening_max_attempts is not None:
        updates[JOB_SCREENING_MAX_ATTEMPTS_ENV] = str(
            payload.job_screening_max_attempts
        )
    if payload.job_screening_max_description_chars is not None:
        updates[JOB_SCREENING_MAX_DESCRIPTION_CHARS_ENV] = str(
            payload.job_screening_max_description_chars
        )

    next_backend = payload.ai_backend or current.ai_backend_mode
    next_openai_key = (
        submitted_openai_key
        if submitted_openai_key is not None
        else current.openai_api_key.strip()
    )
    if next_backend == "openai_api" and not next_openai_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Configure an OpenAI API key before enabling openai_api",
        )

    if not updates:
        return build_settings_response()

    try:
        upsert_env_values(REPO_ROOT / ".env", updates)
    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Settings file is unavailable",
        ) from exc

    os.environ.update(updates)
    get_settings.cache_clear()
    return build_settings_response()
