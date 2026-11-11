"""Readiness checks and immutable execution snapshots for document generation."""

from __future__ import annotations

import importlib.util
import shutil
from dataclasses import asdict, dataclass
from typing import Any, Literal

from app.core.ai_models import AI_BACKEND_MODES, AIBackendMode, is_direct_api_backend
from app.services.generation_resources import INSTRUCTION_VERSION, UPSTREAM_SHA

RuntimeStatus = Literal["ready", "missing"]


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
    instruction_version: str = INSTRUCTION_VERSION
    upstream_sha: str = UPSTREAM_SHA

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
        model, reasoning = (
            (settings.anthropic_api_model, settings.anthropic_api_effort)
            if backend == "anthropic_api"
            else (settings.openai_api_model, settings.openai_api_reasoning_effort)
        )
        timeout = settings.openai_api_timeout_seconds
        attempts = settings.openai_api_max_attempts
        backoff = settings.openai_api_retry_backoff_seconds
    else:
        model = settings.openclaw_assistant_model
        reasoning = settings.openclaw_assistant_thinking
        timeout = settings.openclaw_assistant_timeout_seconds
        attempts = settings.openclaw_assistant_max_attempts
        backoff = settings.openclaw_assistant_retry_backoff_seconds
    return GenerationExecutionSnapshot(
        backend=backend,
        model=model,
        reasoning_effort=reasoning,
        timeout_seconds=timeout,
        max_attempts=attempts,
        retry_backoff_seconds=backoff,
    )


def probe_generation_runtime(
    settings: Any,
    *,
    backend: AIBackendMode,
    which: Any = shutil.which,
) -> GenerationRuntimeReport:
    dependencies = [
        _command_dependency("lualatex", which),
        _command_dependency("xelatex", which),
        _command_dependency("pdftotext", which),
        _command_dependency("pdfinfo", which),
        _command_dependency("pdftoppm", which),
        _module_dependency("pypdf"),
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
    "GenerationExecutionSnapshot",
    "GenerationRuntimeReport",
    "RuntimeDependency",
    "probe_both_generation_backends",
    "probe_generation_runtime",
    "snapshot_generation_execution",
]
