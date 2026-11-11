import asyncio
import base64
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from app.core.ai_models import (
    AI_BACKEND_MODES,
    backend_family,
    default_workload_model,
    model_family,
    openclaw_model_id,
    provider_model_id,
    resolve_workload_model,
)
from app.core.settings import Settings
from app.services.ai_backend import (
    AIBackendError,
    AIImageInput,
    AIRequest,
    AnthropicAPIBackend,
    OpenClawCodexBackend,
    anthropic_effort,
    create_ai_backend,
    create_configured_ai_backend,
)


class AnswerPayload(BaseModel):
    answer: str


def fake_message(
    *,
    text: str = "",
    parsed: BaseModel | None = None,
    stop_reason: str = "end_turn",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="msg_1",
        model="claude-sonnet-5-5",
        stop_reason=stop_reason,
        content=[
            SimpleNamespace(type="thinking", thinking="private"),
            SimpleNamespace(type="text", text=text),
        ],
        parsed_output=parsed,
        usage=SimpleNamespace(
            input_tokens=20,
            cache_creation_input_tokens=3,
            cache_read_input_tokens=7,
            output_tokens=5,
        ),
        model_dump_json=lambda: "{}",
    )


def backend_with(client: Mock | None = None, async_client: Mock | None = None):
    return AnthropicAPIBackend(
        api_key="test-key",
        default_model="claude-sonnet-5-5",
        client=client,
        async_client=async_client,
    )


def status_error(cls: type[anthropic.APIStatusError], status: int, message: str):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(message, response=httpx.Response(status, request=request), body=None)


def test_anthropic_adapter_sends_messages_request_and_returns_neutral_result() -> None:
    client = Mock()
    client.messages.create.return_value = fake_message(text="Bern")

    result = backend_with(client).generate(
        AIRequest(prompt="Capital?", model="anthropic/claude-haiku-5-5", thinking="off")
    )

    options = client.messages.create.call_args.kwargs
    assert options["model"] == "claude-haiku-5-5"
    assert options["max_tokens"] == 16_000
    assert options["output_config"] == {"effort": "low"}
    assert options["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "Capital?"}]}
    ]
    assert "thinking" not in options
    assert result.text == "Bern"
    assert result.backend == "anthropic_api"
    assert result.model == "claude-sonnet-5-5"
    assert result.session_id == "msg_1"
    assert result.usage.input_tokens == 30
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 35


def test_anthropic_adapter_uses_pydantic_structured_output() -> None:
    client = Mock()
    client.messages.parse.return_value = fake_message(
        text='{"answer":"Bern"}', parsed=AnswerPayload(answer="Bern")
    )

    result = backend_with(client).generate(
        AIRequest(prompt="Capital?", structured=True, response_model=AnswerPayload)
    )

    assert client.messages.parse.call_args.kwargs["output_format"] is AnswerPayload
    assert result.structured_data == {"answer": "Bern"}
    client.messages.create.assert_not_called()


def test_anthropic_adapter_falls_back_to_prompted_json_when_schema_is_rejected() -> None:
    client = Mock()
    client.messages.parse.side_effect = status_error(
        anthropic.BadRequestError, 400, "output_config.format: schema is too complex"
    )
    client.messages.create.return_value = fake_message(text='```json\n{"answer": "Bern"}\n```')

    result = backend_with(client).generate(
        AIRequest(prompt="Capital?", structured=True, response_model=AnswerPayload)
    )

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"][-1]["text"]
    assert prompt.startswith("Capital?")
    assert '"answer"' in prompt
    assert result.structured_data == {"answer": "Bern"}


def test_anthropic_adapter_sends_images_and_web_search_without_schema_format() -> None:
    client = Mock()
    client.messages.create.return_value = fake_message(text='{"answer": "ok"}')
    image = AIImageInput(content=b"png-bytes")

    result = backend_with(client).generate(
        AIRequest(
            prompt="Review",
            structured=True,
            response_model=AnswerPayload,
            enable_web_search=True,
            image_inputs=(image,),
        )
    )

    options = client.messages.create.call_args.kwargs
    assert options["tools"][0]["name"] == "web_search"
    assert options["messages"][0]["content"][0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(b"png-bytes").decode("ascii"),
        },
    }
    client.messages.parse.assert_not_called()
    assert result.structured_data == {"answer": "ok"}


def test_anthropic_adapter_supports_async_calls() -> None:
    async_client = Mock()
    async_client.messages.create = AsyncMock(return_value=fake_message(text="Hello"))

    result = asyncio.run(backend_with(async_client=async_client).agenerate(AIRequest(prompt="Hi")))

    assert result.text == "Hello"


@pytest.mark.parametrize(
    ("stop_reason", "code"),
    [("refusal", "refusal"), ("max_tokens", "incomplete_response")],
)
def test_anthropic_adapter_rejects_unusable_responses(stop_reason: str, code: str) -> None:
    client = Mock()
    client.messages.create.return_value = fake_message(text="partial", stop_reason=stop_reason)

    with pytest.raises(AIBackendError) as error:
        backend_with(client).generate(AIRequest(prompt="Hi"))

    assert error.value.code == code
    assert error.value.retryable is False


@pytest.mark.parametrize(
    ("exception", "code", "retryable"),
    [
        (status_error(anthropic.RateLimitError, 429, "slow down"), "rate_limited", True),
        (status_error(anthropic.AuthenticationError, 401, "bad key"), "authentication", False),
        (status_error(anthropic.InternalServerError, 529, "overloaded"), "provider_error", True),
        (status_error(anthropic.BadRequestError, 400, "bad input"), "invalid_request", False),
        (
            anthropic.APITimeoutError(
                httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            ),
            "timeout",
            True,
        ),
    ],
)
def test_anthropic_adapter_classifies_sdk_errors(
    exception: Exception, code: str, retryable: bool
) -> None:
    client = Mock()
    client.messages.create.side_effect = exception

    with pytest.raises(AIBackendError) as error:
        backend_with(client).generate(AIRequest(prompt="Hi"))

    assert error.value.code == code
    assert error.value.retryable is retryable


def test_anthropic_adapter_requires_an_api_key() -> None:
    with pytest.raises(AIBackendError) as error:
        AnthropicAPIBackend(api_key=" ").generate(AIRequest(prompt="Hi"))

    assert error.value.code == "authentication"


@pytest.mark.parametrize(
    ("thinking", "model", "expected"),
    [
        ("off", "claude-sonnet-5-5", "low"),
        ("none", "claude-haiku-5-5", "low"),
        ("medium", "claude-sonnet-5-5", "medium"),
        ("max", "claude-sonnet-5-5", "high"),
        ("xhigh", "claude-opus-5-5", "xhigh"),
        ("unknown", "claude-opus-5-5", "medium"),
    ],
)
def test_anthropic_effort_mapping(thinking: str, model: str, expected: str) -> None:
    assert anthropic_effort(thinking, model=model) == expected


def test_backend_factory_supports_all_modes() -> None:
    assert set(AI_BACKEND_MODES) == {
        "openclaw_codex",
        "openclaw_claude",
        "openai_api",
        "anthropic_api",
    }
    assert create_ai_backend(mode="anthropic_api", anthropic_api_key="key").name == (
        "anthropic_api"
    )
    claude_agent = create_ai_backend(mode="openclaw_claude")
    assert isinstance(claude_agent, OpenClawCodexBackend)
    assert claude_agent.name == "openclaw_claude"


def test_configured_backend_can_pin_a_persisted_run() -> None:
    settings = SimpleNamespace(
        ai_backend_mode="openclaw_codex",
        openclaw_command="openclaw",
        openai_api_key="",
        openai_api_base_url="https://api.openai.com/v1",
        openai_api_model="gpt-6.1-sol",
        anthropic_api_key="key",
        anthropic_api_model="claude-sonnet-5-5",
    )

    backend = create_configured_ai_backend(
        settings, mode="anthropic_api", model="claude-opus-5-5"
    )

    assert isinstance(backend, AnthropicAPIBackend)
    assert backend.default_model == "claude-opus-5-5"


def test_openclaw_claude_passes_provider_prefixed_model_and_reports_its_name() -> None:
    captured: list[str] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout='{"text": "ok"}', stderr="")

    backend = OpenClawCodexBackend(name="openclaw_claude", sync_runner=fake_run)
    result = backend.generate(AIRequest(prompt="Hi", model="claude-haiku-5-5"))

    assert captured[captured.index("--model") + 1] == "anthropic/claude-haiku-5-5"
    assert result.backend == "openclaw_claude"


def test_model_helpers_keep_workloads_inside_the_backend_family() -> None:
    assert backend_family("anthropic_api") == "anthropic"
    assert backend_family("openclaw_claude") == "anthropic"
    assert model_family("openai/gpt-6-luna") == "openai"
    assert model_family("claude-opus-5-5") == "anthropic"
    assert model_family("local-llm") is None
    assert provider_model_id("anthropic/claude-haiku-5-5") == "claude-haiku-5-5"
    assert openclaw_model_id("openclaw_codex", "gpt-6.1-sol") == "openai/gpt-6.1-sol"
    assert default_workload_model("anthropic_api", "screening") == "anthropic/claude-haiku-5-5"
    assert default_workload_model("anthropic_api", "documents") == "anthropic/claude-sonnet-5-5"
    assert (
        resolve_workload_model("anthropic_api", "match", "openai/gpt-6.1-sol")
        == "anthropic/claude-sonnet-5-5"
    )
    assert resolve_workload_model("openai_api", "match", "local-llm") == "local-llm"


def test_settings_move_every_workload_to_claude_for_claude_backends() -> None:
    settings = Settings(
        _env_file=None,
        ai_backend_mode="anthropic_api",
        anthropic_api_key="key",
        job_screening_model="openai/gpt-6-luna",
        ai_match_model="openai/gpt-6.1-sol",
    )

    assert settings.uses_direct_api is True
    assert settings.job_screening_model == "anthropic/claude-haiku-5-5"
    assert settings.ai_match_model_value() == "anthropic/claude-sonnet-5-5"
    assert settings.main_model_value() == "claude-sonnet-5-5"
    assert settings.document_model_value() == "claude-sonnet-5-5"
    assert settings.ai_reasoning_for("off") == "medium"

    agent = Settings(_env_file=None, ai_backend_mode="openclaw_claude")
    assert agent.main_model_value() == "anthropic/claude-sonnet-5-5"
    assert agent.profile_import_model_value() == "anthropic/claude-sonnet-5-5"
    assert agent.job_screening_reasoning_value() == "off"


def test_settings_keep_openai_defaults_and_honor_a_document_model_override() -> None:
    settings = Settings(
        _env_file=None,
        ai_backend_mode="openai_api",
        openai_api_key="key",
        document_generation_model="openai/gpt-5.5",
    )

    assert settings.job_screening_model == "openai/gpt-6-luna"
    assert settings.document_model_value() == "openai/gpt-5.5"
    assert Settings(_env_file=None).profile_import_model_value() == ""


def test_settings_require_an_anthropic_key_for_the_direct_backend() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        Settings(_env_file=None, ai_backend_mode="anthropic_api", anthropic_api_key="")
