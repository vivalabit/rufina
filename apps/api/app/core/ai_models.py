"""AI backends, provider families and per-workload model defaults.

A backend is how a request leaves the application (OpenClaw agent or a direct
provider API). A family is whose models that backend serves. Saved model
settings are only honored when they belong to the active backend's family, so
switching the backend never leaves a workload pointing at another provider.
"""

from __future__ import annotations

from typing import Literal, get_args

AIBackendMode = Literal["openclaw_codex", "openclaw_claude", "openai_api", "anthropic_api"]
AISource = Literal["openclaw_codex", "openclaw_claude", "openai_api", "anthropic_api", "local"]
AIModelFamily = Literal["openai", "anthropic"]
AIWorkload = Literal["screening", "match", "main", "documents"]

AI_BACKEND_MODES: tuple[AIBackendMode, ...] = get_args(AIBackendMode)
AI_SOURCES: tuple[AISource, ...] = get_args(AISource)
OPENCLAW_BACKENDS: frozenset[str] = frozenset({"openclaw_codex", "openclaw_claude"})
DIRECT_API_BACKENDS: frozenset[str] = frozenset({"openai_api", "anthropic_api"})

AI_BACKEND_FAMILIES: dict[str, AIModelFamily] = {
    "openclaw_codex": "openai",
    "openai_api": "openai",
    "openclaw_claude": "anthropic",
    "anthropic_api": "anthropic",
}

AI_BACKEND_PROVIDER_NAMES: dict[str, str] = {
    "openclaw_codex": "OpenAI via OpenClaw/Codex",
    "openclaw_claude": "Anthropic Claude via OpenClaw",
    "openai_api": "OpenAI Responses API",
    "anthropic_api": "Anthropic Claude API",
}

# Model identifiers carry the provider prefix used by OpenClaw. Direct API
# backends strip the prefix before calling the provider.
AI_MODEL_CATALOG: dict[AIModelFamily, tuple[tuple[str, str], ...]] = {
    "openai": (
        ("openai/gpt-6.1-sol", "GPT-6.1 Sol"),
        ("openai/gpt-6-luna", "GPT-6 Luna"),
        ("openai/gpt-5.5", "GPT-5.5"),
    ),
    "anthropic": (
        ("anthropic/claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ("anthropic/claude-haiku-5-5", "Claude Haiku 5.5"),
        ("anthropic/claude-opus-5-5", "Claude Opus 5.5"),
    ),
}

# screening: high-volume vacancy pre-screening and vacancy parsing.
# match: full profile-to-vacancy assessment.
# main: assistant chat and profile import.
# documents: resume wording and cover letters.
AI_WORKLOAD_DEFAULT_MODELS: dict[AIModelFamily, dict[AIWorkload, str]] = {
    "openai": {
        "screening": "openai/gpt-6-luna",
        "match": "openai/gpt-6.1-sol",
        "main": "openai/gpt-6.1-sol",
        "documents": "openai/gpt-6.1-sol",
    },
    "anthropic": {
        "screening": "anthropic/claude-haiku-5-5",
        "match": "anthropic/claude-sonnet-5-5",
        "main": "anthropic/claude-sonnet-5-5",
        "documents": "anthropic/claude-sonnet-5-5",
    },
}

_FAMILY_PREFIXES: dict[AIModelFamily, tuple[str, ...]] = {
    "openai": ("openai/", "gpt-", "o1", "o3", "o4"),
    "anthropic": ("anthropic/", "claude-"),
}


def is_openclaw_backend(backend: object) -> bool:
    return backend in OPENCLAW_BACKENDS


def is_direct_api_backend(backend: object) -> bool:
    return backend in DIRECT_API_BACKENDS


def backend_family(backend: object) -> AIModelFamily:
    return AI_BACKEND_FAMILIES.get(str(backend), "openai")


def ai_backend_provider_name(backend: object) -> str:
    return AI_BACKEND_PROVIDER_NAMES.get(str(backend), "Local processing")


def model_family(model: object) -> AIModelFamily | None:
    """Return the provider family a model identifier belongs to, if recognizable."""
    name = str(model or "").strip().lower()
    if not name:
        return None
    for family, prefixes in _FAMILY_PREFIXES.items():
        if name.startswith(prefixes):
            return family
    return None


def default_workload_model(backend: object, workload: AIWorkload) -> str:
    return AI_WORKLOAD_DEFAULT_MODELS[backend_family(backend)][workload]


def resolve_workload_model(backend: object, workload: AIWorkload, configured: object) -> str:
    """Use the configured model only when it belongs to the backend's provider."""
    name = str(configured or "").strip()
    if name and model_family(name) in {backend_family(backend), None}:
        return name
    return default_workload_model(backend, workload)


def provider_model_id(model: str) -> str:
    """Strip the OpenClaw provider prefix for direct provider API calls."""
    for prefix in ("openai/", "anthropic/"):
        if model.startswith(prefix):
            return model.removeprefix(prefix)
    return model


def openclaw_model_id(backend: object, model: str) -> str:
    """Add the provider prefix OpenClaw expects when a bare model name was configured."""
    name = model.strip()
    if not name or "/" in name:
        return name
    return f"{backend_family(backend)}/{name}"


__all__ = [
    "AI_BACKEND_FAMILIES",
    "AI_BACKEND_MODES",
    "AI_BACKEND_PROVIDER_NAMES",
    "AI_MODEL_CATALOG",
    "AI_WORKLOAD_DEFAULT_MODELS",
    "AIBackendMode",
    "AIModelFamily",
    "AISource",
    "AI_SOURCES",
    "AIWorkload",
    "DIRECT_API_BACKENDS",
    "OPENCLAW_BACKENDS",
    "ai_backend_provider_name",
    "backend_family",
    "default_workload_model",
    "is_direct_api_backend",
    "is_openclaw_backend",
    "model_family",
    "openclaw_model_id",
    "provider_model_id",
    "resolve_workload_model",
]
