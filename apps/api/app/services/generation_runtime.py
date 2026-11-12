"""Readiness checks and immutable execution snapshots for document generation."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.ai_models import (
    AI_BACKEND_MODES,
    AIBackendMode,
    is_direct_api_backend,
    resolve_workload_model,
)

RuntimeStatus = Literal["ready", "missing"]

# Version of the tailoring pipeline that produced a run: planner, wording
# contract and fact checks. Bump it when a change alters generated content.
TAILORING_ENGINE_VERSION = "2.0.0"


@dataclass(frozen=True)
class RuntimeDependency:
    name: str
    status: RuntimeStatus
    detail: str


@dataclass(frozen=True)
class GenerationExecutionSnapshot:
    backend: AIBackendMode
    model: str
    reasoning_effort: str
    timeout_seconds: int
    max_attempts: int
    retry_backoff_seconds: float
    # Cheaper model that parses the vacancy; empty in snapshots of earlier versions.
    parsing_model: str = ""
    engine_version: str = TAILORING_ENGINE_VERSION

    def as_dict(self) -> dict[str, str | int | float]:
        return asdict(self)


@dataclass(frozen=True)
class GenerationRuntimeReport:
    backend: AIBackendMode
    available: bool
    dependencies: tuple[RuntimeDependency, ...]


def snapshot_generation_execution(settings: Any) -> GenerationExecutionSnapshot:
    backend: AIBackendMode = settings.ai_backend_mode
    if is_direct_api_backend(backend):
        reasoning = (
            settings.anthropic_api_effort
            if backend == "anthropic_api"
            else settings.openai_api_reasoning_effort
        )
        timeout = settings.openai_api_timeout_seconds
        attempts = settings.openai_api_max_attempts
        backoff = settings.openai_api_retry_backoff_seconds
    else:
        reasoning = settings.openclaw_assistant_thinking
        timeout = settings.openclaw_assistant_timeout_seconds
        attempts = settings.openclaw_assistant_max_attempts
        backoff = settings.openclaw_assistant_retry_backoff_seconds
    document_model = getattr(settings, "document_model_value", None)
    if callable(document_model):
        model = document_model()
    elif backend == "anthropic_api":
        model = settings.anthropic_api_model
    elif backend == "openai_api":
        model = settings.openai_api_model
    else:
        model = settings.openclaw_assistant_model
    return GenerationExecutionSnapshot(
        backend=backend,
        model=model,
        reasoning_effort=reasoning,
        timeout_seconds=timeout,
        max_attempts=attempts,
        retry_backoff_seconds=backoff,
        parsing_model=resolve_workload_model(
            backend, "screening", getattr(settings, "job_screening_model", "")
        ),
    )


def probe_generation_runtime(
    settings: Any,
    *,
    backend: AIBackendMode,
    which: Any = shutil.which,
) -> GenerationRuntimeReport:
    """Report what a run needs: the AI backend, Chromium for PDFs and the DOCX writer.

    Poppler is optional. Without it the text check of a finished PDF uses pypdf.
    """
    dependencies = [
        _module_dependency("playwright"),
        _module_dependency("pypdf"),
        _module_dependency("docx"),
    ]
    if is_direct_api_backend(backend):
        provider, key, env_name = (
            ("Anthropic", getattr(settings, "anthropic_api_key", ""), "ANTHROPIC_API_KEY")
            if backend == "anthropic_api"
            else ("OpenAI", settings.openai_api_key, "OPENAI_API_KEY")
        )
        dependencies.insert(
            0,
            RuntimeDependency(
                name=backend,
                status="ready" if key.strip() else "missing",
                detail=(
                    f"{provider} API key configured"
                    if key.strip()
                    else f"{env_name} is not configured"
                ),
            ),
        )
    else:
        dependencies.insert(0, _command_dependency(settings.openclaw_command, which))
    return GenerationRuntimeReport(
        backend=backend,
        available=all(item.status == "ready" for item in dependencies),
        dependencies=tuple(dependencies),
    )


def probe_both_generation_backends(
    settings: Any,
    *,
    which: Any = shutil.which,
) -> dict[AIBackendMode, GenerationRuntimeReport]:
    return {
        backend: probe_generation_runtime(settings, backend=backend, which=which)
        for backend in AI_BACKEND_MODES
    }


def _command_dependency(name: str, which: Any) -> RuntimeDependency:
    path = which(name)
    return RuntimeDependency(
        name=name,
        status="ready" if path else "missing",
        detail=str(path or f"{name} is not installed"),
    )


def _module_dependency(name: str) -> RuntimeDependency:
    found = importlib.util.find_spec(name) is not None
    return RuntimeDependency(
        name=name,
        status="ready" if found else "missing",
        detail=f"Python module {name} {'available' if found else 'is not installed'}",
    )


__all__ = [
    "TAILORING_ENGINE_VERSION",
    "GenerationExecutionSnapshot",
    "GenerationRuntimeReport",
    "RuntimeDependency",
    "probe_both_generation_backends",
    "probe_generation_runtime",
    "snapshot_generation_execution",
]
