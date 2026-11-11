from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    InternalServerError,
    OpenAI,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
import anthropic
from pydantic import BaseModel

from app.core.ai_models import (
    AI_BACKEND_PROVIDER_NAMES,  # noqa: F401 - re-exported for existing importers
    AIBackendMode,
    ai_backend_provider_name,  # noqa: F401 - re-exported for existing importers
    is_openclaw_backend,
    openclaw_model_id,
    provider_model_id,
)

OPENCLAW_MULTIMODAL_RUNNER = Path(__file__).with_name("openclaw_multimodal_runner.mjs")
ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS = 16_000
ANTHROPIC_WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 6}


PromptTransport = Literal["argument", "file"]


class AIBackendError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "backend_error",
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code


@dataclass(frozen=True)
class AIUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    source: str = "unavailable"

    def as_dict(self) -> dict[str, int | str]:
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "totalTokens": self.total_tokens or self.input_tokens + self.output_tokens,
            "tokenCountSource": self.source,
        }


@dataclass(frozen=True)
class AIRequest:
    prompt: str
    model: str = ""
    agent_id: str = ""
    thinking: str = "off"
    timeout_seconds: int = 120
    session_id: str = ""
    structured: bool = False
    response_model: type[BaseModel] | None = None
    enable_web_search: bool = False
    image_inputs: tuple[AIImageInput, ...] = ()


@dataclass(frozen=True)
class AIImageInput:
    content: bytes
    media_type: Literal["image/png", "image/jpeg", "image/webp"] = "image/png"
    detail: Literal["low", "high", "auto"] = "high"


@dataclass(frozen=True)
class AIResult:
    text: str
    structured_data: Any | None
    model: str
    backend: AIBackendMode
    usage: AIUsage
    latency_ms: int
    session_id: str
    raw_response: str = field(default="", repr=False)


class AIBackend(Protocol):
    name: AIBackendMode

    def generate(self, request: AIRequest) -> AIResult: ...

    async def agenerate(self, request: AIRequest) -> AIResult: ...


SyncRunner = Callable[..., subprocess.CompletedProcess[str]]
AsyncProcessFactory = Callable[..., Any]


class OpenClawCodexBackend:
    """Runs a configured OpenClaw agent; the model family follows the backend name."""

    name: AIBackendMode = "openclaw_codex"

    def __init__(
        self,
        *,
        name: AIBackendMode = "openclaw_codex",
        command: str = "openclaw",
        sync_runner: SyncRunner = subprocess.run,
        async_process_factory: AsyncProcessFactory = asyncio.create_subprocess_exec,
        prompt_transport: PromptTransport = "argument",
        include_cli_timeout: bool = False,
        model_after_timeout: bool = False,
    ) -> None:
        self.name = name
        self.command = command
        self.executable = shutil.which(command) or command
        self.sync_runner = sync_runner
        self.async_process_factory = async_process_factory
        self.prompt_transport = prompt_transport
        self.include_cli_timeout = include_cli_timeout
        self.model_after_timeout = model_after_timeout

    def generate(self, request: AIRequest) -> AIResult:
        started_at = time.perf_counter()
        if request.image_inputs:
            with tempfile.TemporaryDirectory(prefix="tasko-ai-images-") as directory:
                request_file = _write_openclaw_multimodal_request(
                    request,
                    directory=Path(directory),
                    openclaw_executable=self.executable,
                )
                return self._generate_once(
                    request,
                    [
                        shutil.which("node") or "node",
                        str(OPENCLAW_MULTIMODAL_RUNNER),
                        str(request_file),
                    ],
                    started_at=started_at,
                )
        if self.prompt_transport == "file":
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".txt"
            ) as prompt_file:
                prompt_file.write(request.prompt)
                prompt_file.flush()
                return self._generate_once(
                    request,
                    self._arguments(request, prompt_file=Path(prompt_file.name)),
                    started_at=started_at,
                )
        return self._generate_once(
            request,
            self._arguments(request),
            started_at=started_at,
        )

    def _generate_once(
        self,
        request: AIRequest,
        arguments: list[str],
        *,
        started_at: float,
    ) -> AIResult:
        try:
            result = self.sync_runner(
                arguments,
                capture_output=True,
                check=True,
                text=True,
                timeout=request.timeout_seconds + 5,
            )
        except FileNotFoundError as exc:
            raise AIBackendError(
                f"AI backend command was not found: {self.command}",
                code="runtime_missing",
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise AIBackendError(
                "AI backend request timed out",
                code="timeout",
                retryable=True,
            ) from exc
        except subprocess.CalledProcessError as exc:
            raw_error = (exc.stderr or exc.stdout or "OpenClaw command failed").strip()
            raise AIBackendError(
                raw_error,
                code="execution_failed",
                retryable=True,
            ) from exc
        except OSError as exc:
            raise AIBackendError(
                f"AI backend command could not start: {exc}",
                code="runtime_unavailable",
            ) from exc

        return build_ai_result(
            raw_response=result.stdout,
            fallback_model=request.model,
            backend=self.name,
            session_id=request.session_id,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )

    async def agenerate(self, request: AIRequest) -> AIResult:
        started_at = time.perf_counter()
        if request.image_inputs:
            with tempfile.TemporaryDirectory(prefix="tasko-ai-images-") as directory:
                request_file = _write_openclaw_multimodal_request(
                    request,
                    directory=Path(directory),
                    openclaw_executable=self.executable,
                )
                return await self._agenerate_once(
                    request,
                    [
                        shutil.which("node") or "node",
                        str(OPENCLAW_MULTIMODAL_RUNNER),
                        str(request_file),
                    ],
                    started_at=started_at,
                )
        return await self._agenerate_once(
            request,
            self._arguments(request),
            started_at=started_at,
        )

    async def _agenerate_once(
        self,
        request: AIRequest,
        arguments: list[str],
        *,
        started_at: float,
    ) -> AIResult:
        try:
            process = await self.async_process_factory(
                *arguments,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AIBackendError(
                f"AI backend command was not found: {self.command}",
                code="runtime_missing",
            ) from exc

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(),
                timeout=request.timeout_seconds + 5,
            )
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise AIBackendError(
                "AI backend request timed out",
                code="timeout",
                retryable=True,
            ) from exc

        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        if process.returncode != 0:
            raise AIBackendError(
                (stderr or stdout or "OpenClaw command failed").strip(),
                code="execution_failed",
                retryable=True,
            )
        return build_ai_result(
            raw_response=stdout,
            fallback_model=request.model,
            backend=self.name,
            session_id=request.session_id,
            latency_ms=round((time.perf_counter() - started_at) * 1000),
        )

    def _arguments(self, request: AIRequest, *, prompt_file: Path | None = None) -> list[str]:
        arguments = [self.executable, "agent", "--local"]
        if request.agent_id:
            arguments.extend(["--agent", request.agent_id])
        if request.session_id:
            arguments.extend(["--session-key", request.session_id])
        if prompt_file is not None:
            arguments.extend(["--message-file", str(prompt_file)])
        else:
            arguments.extend(["--message", request.prompt])
        model = openclaw_model_id(self.name, request.model)
        if model and not self.model_after_timeout:
            arguments.extend(["--model", model])
        if request.thinking:
            arguments.extend(["--thinking", request.thinking])
        if self.include_cli_timeout:
            arguments.extend(["--timeout", str(request.timeout_seconds)])
        if model and self.model_after_timeout:
            arguments.extend(["--model", model])
        arguments.append("--json")
        return arguments


class OpenAIAPIBackend:
    name: AIBackendMode = "openai_api"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "",
        client: OpenAI | Any | None = None,
        async_client: AsyncOpenAI | Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.client = client
        self.async_client = async_client

    def generate(self, request: AIRequest) -> AIResult:
        started_at = time.perf_counter()
        try:
            client = self._sync_client()
            if request.response_model is not None:
                response = client.responses.parse(
                    **self._request_options(request),
                    text_format=request.response_model,
                )
            else:
                response = client.responses.create(**self._request_options(request))
        except OpenAIError as exc:
            raise openai_sdk_error(exc) from exc
        return self._result(response, request, started_at)

    async def agenerate(self, request: AIRequest) -> AIResult:
        started_at = time.perf_counter()
        try:
            client = self._async_client()
            if request.response_model is not None:
                response = await client.responses.parse(
                    **self._request_options(request),
                    text_format=request.response_model,
                )
            else:
                response = await client.responses.create(**self._request_options(request))
        except OpenAIError as exc:
            raise openai_sdk_error(exc) from exc
        return self._result(response, request, started_at)

    def _require_api_key(self) -> str:
        if not self.api_key.strip():
            raise AIBackendError(
                "OPENAI_API_KEY is required for openai_api mode",
                code="authentication",
            )
        return self.api_key

    def _sync_client(self) -> OpenAI | Any:
        if self.client is None:
            self.client = OpenAI(
                api_key=self._require_api_key(),
                base_url=self.base_url,
                max_retries=0,
            )
        return self.client

    def _async_client(self) -> AsyncOpenAI | Any:
        if self.async_client is None:
            self.async_client = AsyncOpenAI(
                api_key=self._require_api_key(),
                base_url=self.base_url,
                max_retries=0,
            )
        return self.async_client

    def _request_options(self, request: AIRequest) -> dict[str, Any]:
        input_value: str | list[dict[str, Any]] = request.prompt
        if request.image_inputs:
            content: list[dict[str, Any]] = [{"type": "input_text", "text": request.prompt}]
            content.extend(
                {
                    "type": "input_image",
                    "image_url": (
                        f"data:{image.media_type};base64,"
                        f"{base64.b64encode(image.content).decode('ascii')}"
                    ),
                    "detail": image.detail,
                }
                for image in request.image_inputs
            )
            input_value = [{"role": "user", "content": content}]
        options: dict[str, Any] = {
            "model": normalize_openai_model(request.model or self.default_model),
            "input": input_value,
            "store": False,
            "timeout": request.timeout_seconds,
        }
        if request.thinking and request.thinking != "off":
            options["reasoning"] = {"effort": request.thinking}
        if request.structured and request.response_model is None:
            options["text"] = {"format": {"type": "json_object"}}
        if request.enable_web_search:
            options["tools"] = [{"type": "web_search"}]
            options["include"] = ["web_search_call.action.sources"]
            options["max_tool_calls"] = 6
        return options

    def _result(
        self,
        response: Any,
        request: AIRequest,
        started_at: float,
    ) -> AIResult:
        response_error = getattr(response, "error", None)
        if response_error is not None:
            message = getattr(response_error, "message", None) or str(response_error)
            raise AIBackendError(message, code="provider_error", retryable=True)
        refusal = extract_openai_refusal(response)
        if refusal:
            raise AIBackendError(refusal, code="refusal")
        status = getattr(response, "status", "completed")
        if status == "incomplete":
            raise AIBackendError(
                "OpenAI response was incomplete",
                code="incomplete_response",
                retryable=True,
            )

        raw_response = serialize_openai_response(response)
        parsed = getattr(response, "output_parsed", None)
        structured_data = (
            parsed.model_dump(mode="json", by_alias=True)
            if isinstance(parsed, BaseModel)
            else parsed
        )
        text = str(getattr(response, "output_text", "") or "").strip()
        if not text and structured_data is not None:
            text = json.dumps(structured_data, ensure_ascii=False)
        usage = getattr(response, "usage", None)
        input_tokens = nonnegative_int(getattr(usage, "input_tokens", 0))
        output_tokens = nonnegative_int(getattr(usage, "output_tokens", 0))
        total_tokens = nonnegative_int(getattr(usage, "total_tokens", 0))
        if structured_data is None:
            structured_data = extract_structured_data(text, extract_json_values(raw_response))
        return AIResult(
            text=text,
            structured_data=structured_data,
            model=str(
                getattr(response, "model", "")
                or normalize_openai_model(request.model or self.default_model)
            ),
            backend=self.name,
            usage=AIUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens or input_tokens + output_tokens,
                source="provider",
            ),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
            session_id=str(getattr(response, "id", "") or ""),
            raw_response=raw_response,
        )


class AnthropicAPIBackend:
    """Anthropic Messages API with structured output, vision input and web search."""

    name: AIBackendMode = "anthropic_api"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com",
        default_model: str = "",
        max_output_tokens: int = ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS,
        client: Any | None = None,
        async_client: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.max_output_tokens = max_output_tokens
        self.client = client
        self.async_client = async_client

    def generate(self, request: AIRequest) -> AIResult:
        started_at = time.perf_counter()
        client = self._sync_client()
        options = self._request_options(request)
        try:
            if _anthropic_uses_schema(request):
                try:
                    response = client.messages.parse(
                        **options, output_format=request.response_model
                    )
                except anthropic.BadRequestError as exc:
                    if not _anthropic_schema_rejected(exc):
                        raise
                    response = client.messages.create(**self._schema_fallback_options(request))
            else:
                response = client.messages.create(**options)
        except anthropic.AnthropicError as exc:
            raise anthropic_sdk_error(exc) from exc
        return self._result(response, request, started_at)

    async def agenerate(self, request: AIRequest) -> AIResult:
        started_at = time.perf_counter()
        client = self._async_client()
        options = self._request_options(request)
        try:
            if _anthropic_uses_schema(request):
                try:
                    response = await client.messages.parse(
                        **options, output_format=request.response_model
                    )
                except anthropic.BadRequestError as exc:
                    if not _anthropic_schema_rejected(exc):
                        raise
                    response = await client.messages.create(
                        **self._schema_fallback_options(request)
                    )
            else:
                response = await client.messages.create(**options)
        except anthropic.AnthropicError as exc:
            raise anthropic_sdk_error(exc) from exc
        return self._result(response, request, started_at)

    def _require_api_key(self) -> str:
        if not self.api_key.strip():
            raise AIBackendError(
                "ANTHROPIC_API_KEY is required for anthropic_api mode",
                code="authentication",
            )
        return self.api_key

    def _sync_client(self) -> Any:
        if self.client is None:
            self.client = anthropic.Anthropic(
                api_key=self._require_api_key(),
                base_url=self.base_url,
                max_retries=0,
            )
        return self.client

    def _async_client(self) -> Any:
        if self.async_client is None:
            self.async_client = anthropic.AsyncAnthropic(
                api_key=self._require_api_key(),
                base_url=self.base_url,
                max_retries=0,
            )
        return self.async_client

    def _model(self, request: AIRequest) -> str:
        return provider_model_id(request.model or self.default_model)

    def _request_options(self, request: AIRequest, *, prompt: str | None = None) -> dict[str, Any]:
        content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": base64.b64encode(image.content).decode("ascii"),
                },
            }
            for image in request.image_inputs
        ]
        content.append({"type": "text", "text": prompt if prompt is not None else request.prompt})
        model = self._model(request)
        options: dict[str, Any] = {
            "model": model,
            "max_tokens": self.max_output_tokens,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": anthropic_effort(request.thinking, model=model)},
            "timeout": request.timeout_seconds,
        }
        if request.enable_web_search:
            options["tools"] = [dict(ANTHROPIC_WEB_SEARCH_TOOL)]
        return options

    def _schema_fallback_options(self, request: AIRequest) -> dict[str, Any]:
        """Ask for the schema in the prompt when the provider rejects it as a format."""
        assert request.response_model is not None
        schema = json.dumps(request.response_model.model_json_schema(), ensure_ascii=False)
        prompt = (
            f"{request.prompt}\n\nReturn only one JSON object that validates against this "
            f"JSON Schema, with no surrounding text:\n{schema}"
        )
        return self._request_options(request, prompt=prompt)

    def _result(self, response: Any, request: AIRequest, started_at: float) -> AIResult:
        stop_reason = str(getattr(response, "stop_reason", "") or "")
        if stop_reason == "refusal":
            raise AIBackendError("The model declined this request", code="refusal")
        if stop_reason == "max_tokens":
            raise AIBackendError(
                "Anthropic response reached the output token limit",
                code="incomplete_response",
            )
        text = "\n".join(
            block_text
            for block in getattr(response, "content", []) or []
            if getattr(block, "type", "") == "text"
            and (block_text := str(getattr(block, "text", "") or "").strip())
        ).strip()
        parsed = getattr(response, "parsed_output", None)
        structured_data = (
            parsed.model_dump(mode="json", by_alias=True)
            if isinstance(parsed, BaseModel)
            else parsed
        )
        if not text and structured_data is not None:
            text = json.dumps(structured_data, ensure_ascii=False)
        raw_response = serialize_openai_response(response)
        if structured_data is None and (request.structured or request.response_model is not None):
            structured_data = extract_structured_data(text, [])
        usage = getattr(response, "usage", None)
        input_tokens = sum(
            nonnegative_int(getattr(usage, name, 0))
            for name in (
                "input_tokens",
                "cache_creation_input_tokens",
                "cache_read_input_tokens",
            )
        )
        output_tokens = nonnegative_int(getattr(usage, "output_tokens", 0))
        return AIResult(
            text=text,
            structured_data=structured_data,
            model=str(getattr(response, "model", "") or self._model(request)),
            backend=self.name,
            usage=AIUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
                source="provider",
            ),
            latency_ms=round((time.perf_counter() - started_at) * 1000),
            session_id=str(getattr(response, "id", "") or ""),
            raw_response=raw_response,
        )


def _anthropic_uses_schema(request: AIRequest) -> bool:
    # Web search results carry citations, which the provider does not combine
    # with a JSON schema format; those requests are parsed from the reply text.
    return request.response_model is not None and not request.enable_web_search


def _anthropic_schema_rejected(exc: Exception) -> bool:
    message = str(exc).lower()
    return "schema" in message or "output_config" in message or "output_format" in message


def anthropic_effort(thinking: str, *, model: str = "") -> str:
    """Map the application's reasoning setting to an Anthropic effort level."""
    effort = {"": "low", "off": "low", "none": "low", "minimal": "low"}.get(
        thinking.strip().lower(), thinking.strip().lower()
    )
    if effort not in {"low", "medium", "high", "xhigh", "max"}:
        return "medium"
    if effort in {"xhigh", "max"} and "opus" not in model:
        return "high"
    return effort


def anthropic_sdk_error(exc: Exception) -> AIBackendError:
    status_code = getattr(exc, "status_code", None)
    message = str(exc).strip()
    if isinstance(exc, anthropic.APITimeoutError):
        return AIBackendError("AI backend request timed out", code="timeout", retryable=True)
    if isinstance(exc, anthropic.RateLimitError):
        return AIBackendError(
            message or "AI backend is rate-limited",
            code="rate_limited",
            retryable=True,
            status_code=status_code or 429,
        )
    if isinstance(exc, anthropic.AuthenticationError):
        return AIBackendError(
            message or "AI backend authentication failed",
            code="authentication",
            status_code=status_code or 401,
        )
    if isinstance(exc, anthropic.PermissionDeniedError):
        return AIBackendError(
            message or "AI backend permission was denied",
            code="permission_denied",
            status_code=status_code or 403,
        )
    if isinstance(exc, anthropic.APIConnectionError):
        return AIBackendError(
            "AI backend could not reach the provider",
            code="provider_unreachable",
            retryable=True,
        )
    if isinstance(exc, anthropic.APIStatusError):
        retryable = bool(status_code in {408, 409, 429, 529} or (status_code or 0) >= 500)
        return AIBackendError(
            message or "AI request was rejected",
            code="provider_error" if retryable else "invalid_request",
            retryable=retryable,
            status_code=status_code,
        )
    return AIBackendError(message or "Anthropic SDK request failed", code="backend_error")


def build_ai_result(
    *,
    raw_response: str,
    fallback_model: str,
    backend: AIBackendMode,
    session_id: str,
    latency_ms: int,
) -> AIResult:
    payloads = extract_json_values(raw_response)
    text = extract_ai_text(payloads)
    structured_data = extract_structured_data(text, payloads)
    model = find_string_field(payloads, {"model", "modelid"}) or fallback_model
    usage = extract_ai_usage(payloads)
    response_id = extract_response_id(payloads) if backend == "openai_api" else ""
    return AIResult(
        text=text,
        structured_data=structured_data,
        model=model or "configured-agent-model",
        backend=backend,
        usage=usage,
        latency_ms=latency_ms,
        session_id=session_id or response_id,
        raw_response=raw_response,
    )


def _write_openclaw_multimodal_request(
    request: AIRequest,
    *,
    directory: Path,
    openclaw_executable: str,
) -> Path:
    request_file = directory / "request.json"
    request_file.write_text(
        json.dumps(
            {
                "prompt": request.prompt,
                "model": request.model,
                "agentId": request.agent_id,
                "thinking": request.thinking,
                "timeoutSeconds": request.timeout_seconds,
                "sessionId": request.session_id,
                "openclawExecutable": openclaw_executable,
                "images": [
                    {
                        "data": base64.b64encode(image.content).decode("ascii"),
                        "mimeType": image.media_type,
                    }
                    for image in request.image_inputs
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return request_file


def extract_json_values(value: str) -> list[Any]:
    decoder = json.JSONDecoder()
    values: list[Any] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character not in "[{":
            index += 1
            continue
        try:
            payload, end = decoder.raw_decode(value[index:])
        except json.JSONDecodeError:
            index += 1
            continue
        values.append(payload)
        index += max(1, end)
    return values


def extract_ai_text(payloads: list[Any]) -> str:
    texts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = key.replace("_", "").lower()
                if (
                    normalized
                    in {
                        "outputtext",
                        "finalassistantvisibletext",
                        "finalassistantrawtext",
                    }
                    and isinstance(item, str)
                    or key == "text"
                    and isinstance(item, str)
                ):
                    texts.append(item)
                else:
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for payload in payloads:
        visit(payload)
    return next((text.strip() for text in reversed(texts) if text.strip()), "")


def extract_structured_data(text: str, payloads: list[Any]) -> Any | None:
    candidates = [text.strip()]
    if text.strip().startswith("```"):
        candidates.append(re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip()))
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except (TypeError, json.JSONDecodeError):
            pass
    for payload in reversed(payloads):
        if isinstance(payload, dict) and not any(
            key in payload for key in ("status", "result", "response", "output", "payloads")
        ):
            return payload
    return None


def extract_ai_usage(payloads: list[Any]) -> AIUsage:
    usage_values: list[dict[str, Any]] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.replace("_", "").lower() in {"usage", "tokenusage", "tokens"} and isinstance(
                    item, dict
                ):
                    usage_values.append(item)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for payload in payloads:
        visit(payload)
    best = AIUsage()
    for usage in usage_values:
        input_tokens = usage_int(
            usage, "input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "input"
        )
        output_tokens = usage_int(
            usage,
            "output_tokens",
            "outputTokens",
            "completion_tokens",
            "completionTokens",
            "output",
        )
        total_tokens = (
            usage_int(usage, "total_tokens", "totalTokens", "total") or input_tokens + output_tokens
        )
        if total_tokens >= best.total_tokens:
            best = AIUsage(input_tokens, output_tokens, total_tokens, source="provider")
    return best


def usage_int(value: dict[str, Any], *keys: str) -> int:
    for key in keys:
        item = value.get(key)
        if isinstance(item, (int, float)) and not isinstance(item, bool) and item >= 0:
            return int(item)
    return 0


def find_string_field(payloads: list[Any], names: set[str]) -> str:
    result = ""

    def visit(value: Any) -> None:
        nonlocal result
        if isinstance(value, dict):
            for key, item in value.items():
                if key.replace("_", "").lower() in names and isinstance(item, str) and item:
                    result = item
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    for payload in payloads:
        visit(payload)
    return result


def extract_response_id(payloads: list[Any]) -> str:
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        response_id = payload.get("id")
        if isinstance(response_id, str) and response_id:
            return response_id
    return ""


def normalize_openai_model(model: str) -> str:
    return provider_model_id(model)


def serialize_openai_response(response: Any) -> str:
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        try:
            payload = model_dump(mode="json", warnings=False)
        except TypeError:
            payload = model_dump(mode="json")
        return json.dumps(payload, ensure_ascii=False)
    model_dump_json = getattr(response, "model_dump_json", None)
    if callable(model_dump_json):
        return str(model_dump_json())
    return json.dumps(response, ensure_ascii=False, default=str)


def extract_openai_refusal(response: Any) -> str:
    for output_item in getattr(response, "output", []) or []:
        for content_item in getattr(output_item, "content", []) or []:
            refusal = getattr(content_item, "refusal", "")
            if isinstance(refusal, str) and refusal.strip():
                return refusal.strip()
    return ""


def nonnegative_int(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
        return int(value)
    return 0


def openai_sdk_error(exc: OpenAIError) -> AIBackendError:
    status_code = getattr(exc, "status_code", None)
    message = str(exc).strip()
    if isinstance(exc, APITimeoutError):
        return AIBackendError(
            "AI backend request timed out",
            code="timeout",
            retryable=True,
        )
    if isinstance(exc, RateLimitError):
        return AIBackendError(
            message or "AI backend is rate-limited",
            code="rate_limited",
            retryable=True,
            status_code=status_code or 429,
        )
    if isinstance(exc, AuthenticationError):
        return AIBackendError(
            message or "AI backend authentication failed",
            code="authentication",
            status_code=status_code or 401,
        )
    if isinstance(exc, PermissionDeniedError):
        return AIBackendError(
            message or "AI backend permission was denied",
            code="permission_denied",
            status_code=status_code or 403,
        )
    if isinstance(exc, APIConnectionError):
        return AIBackendError(
            "AI backend could not reach the provider",
            code="provider_unreachable",
            retryable=True,
        )
    if isinstance(exc, InternalServerError):
        return AIBackendError(
            message or "AI provider failed",
            code="provider_error",
            retryable=True,
            status_code=status_code,
        )
    if isinstance(exc, APIStatusError):
        retryable = bool(status_code in {408, 409, 429} or (status_code or 0) >= 500)
        return AIBackendError(
            message or "AI request was rejected",
            code="provider_error" if retryable else "invalid_request",
            retryable=retryable,
            status_code=status_code,
        )
    return AIBackendError(message or "OpenAI SDK request failed", code="backend_error")


def create_ai_backend(
    *,
    mode: AIBackendMode,
    openclaw_command: str = "openclaw",
    openai_api_key: str = "",
    openai_api_base_url: str = "https://api.openai.com/v1",
    openai_api_model: str = "",
    anthropic_api_key: str = "",
    anthropic_api_base_url: str = "https://api.anthropic.com",
    anthropic_api_model: str = "",
    anthropic_api_max_output_tokens: int = ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS,
    sync_runner: SyncRunner = subprocess.run,
    async_process_factory: AsyncProcessFactory = asyncio.create_subprocess_exec,
    openclaw_prompt_transport: PromptTransport = "argument",
    openclaw_include_cli_timeout: bool = False,
    openclaw_model_after_timeout: bool = False,
) -> AIBackend:
    if is_openclaw_backend(mode):
        return OpenClawCodexBackend(
            name=mode,
            command=openclaw_command,
            sync_runner=sync_runner,
            async_process_factory=async_process_factory,
            prompt_transport=openclaw_prompt_transport,
            include_cli_timeout=openclaw_include_cli_timeout,
            model_after_timeout=openclaw_model_after_timeout,
        )
    if mode == "openai_api":
        return OpenAIAPIBackend(
            api_key=openai_api_key,
            base_url=openai_api_base_url,
            default_model=openai_api_model,
        )
    if mode == "anthropic_api":
        return AnthropicAPIBackend(
            api_key=anthropic_api_key,
            base_url=anthropic_api_base_url,
            default_model=anthropic_api_model,
            max_output_tokens=anthropic_api_max_output_tokens,
        )
    raise AIBackendError(f"Unsupported AI backend mode: {mode}", code="unsupported_backend")


def create_configured_ai_backend(
    settings: Any,
    *,
    mode: AIBackendMode | None = None,
    model: str | None = None,
    sync_runner: SyncRunner = subprocess.run,
    async_process_factory: AsyncProcessFactory = asyncio.create_subprocess_exec,
    openclaw_prompt_transport: PromptTransport = "argument",
    openclaw_include_cli_timeout: bool = False,
    openclaw_model_after_timeout: bool = False,
) -> AIBackend:
    """Build the backend from settings; `mode` and `model` pin a persisted run's choice."""
    return create_ai_backend(
        mode=mode or settings.ai_backend_mode,
        openclaw_command=settings.openclaw_command,
        openai_api_key=settings.openai_api_key,
        openai_api_base_url=settings.openai_api_base_url,
        openai_api_model=model or settings.openai_api_model,
        anthropic_api_key=getattr(settings, "anthropic_api_key", ""),
        anthropic_api_base_url=getattr(
            settings, "anthropic_api_base_url", "https://api.anthropic.com"
        ),
        anthropic_api_model=model or getattr(settings, "anthropic_api_model", ""),
        anthropic_api_max_output_tokens=getattr(
            settings, "anthropic_api_max_output_tokens", ANTHROPIC_DEFAULT_MAX_OUTPUT_TOKENS
        ),
        sync_runner=sync_runner,
        async_process_factory=async_process_factory,
        openclaw_prompt_transport=openclaw_prompt_transport,
        openclaw_include_cli_timeout=openclaw_include_cli_timeout,
        openclaw_model_after_timeout=openclaw_model_after_timeout,
    )


def generate_with_retries(
    backend: AIBackend,
    request: AIRequest,
    *,
    max_attempts: int = 1,
    retry_backoff_seconds: float = 0,
) -> AIResult:
    attempts = max(1, max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            return backend.generate(request)
        except AIBackendError as exc:
            if not exc.retryable or attempt >= attempts:
                raise
            if retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds * (2 ** (attempt - 1)))
    raise AIBackendError("AI backend request failed", code="backend_error")
