import asyncio
import base64
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError, OpenAI, RateLimitError
from pydantic import BaseModel

from app.services.ai_backend import (
    AIBackendError,
    AIImageInput,
    AIRequest,
    AIResult,
    AIUsage,
    OpenAIAPIBackend,
    OpenClawCodexBackend,
    create_ai_backend,
    generate_with_retries,
)


class AnswerPayload(BaseModel):
    answer: str


def fake_openai_response(
    *,
    text: str,
    response_id: str,
    parsed: BaseModel | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=response_id,
        model="gpt-5.6-terra",
        status="completed",
        error=None,
        output=[],
        output_text=text,
        output_parsed=parsed,
        usage=SimpleNamespace(input_tokens=18, output_tokens=4, total_tokens=22),
        model_dump_json=lambda: json.dumps(
            {
                "id": response_id,
                "model": "gpt-5.6-terra",
                "output_text": text,
                "usage": {"input_tokens": 18, "output_tokens": 4, "total_tokens": 22},
            }
        ),
    )


def test_openclaw_adapter_preserves_cli_and_returns_neutral_result() -> None:
    captured: list[str] = []

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        captured.extend(args)
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps(
                {
                    "result": {"payloads": [{"text": '{"answer":"ready"}'}]},
                    "meta": {
                        "model": "openai/gpt-5.6-terra",
                        "usage": {"input": 20, "output": 5, "total": 25},
                    },
                }
            ),
            stderr="",
        )

    result = OpenClawCodexBackend(
        command="/custom/openclaw",
        sync_runner=fake_run,
    ).generate(
        AIRequest(
            prompt="Return JSON",
            model="openai/gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="low",
            timeout_seconds=30,
            session_id="agent:rufina-assistant:test-session",
            structured=True,
        )
    )

    assert captured[:5] == [
        "/custom/openclaw",
        "agent",
        "--local",
        "--agent",
        "rufina-assistant",
    ]
    assert captured[captured.index("--session-key") + 1] == ("agent:rufina-assistant:test-session")
    assert captured[captured.index("--message") + 1] == "Return JSON"
    assert captured[-1] == "--json"
    assert result.text == '{"answer":"ready"}'
    assert result.structured_data == {"answer": "ready"}
    assert result.model == "openai/gpt-5.6-terra"
    assert result.backend == "openclaw_codex"
    assert result.usage.input_tokens == 20
    assert result.usage.output_tokens == 5
    assert result.usage.total_tokens == 25
    assert result.latency_ms >= 0
    assert result.session_id == "agent:rufina-assistant:test-session"


def test_openclaw_adapter_sends_page_images_through_multimodal_runner() -> None:
    captured_request_path = ""

    def fake_run(args: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        nonlocal captured_request_path
        assert Path(args[1]).name == "openclaw_multimodal_runner.mjs"
        captured_request_path = args[2]
        request = json.loads(Path(captured_request_path).read_text(encoding="utf-8"))
        assert request["prompt"] == "Inspect the page"
        assert Path(request["openclawExecutable"]).name == "openclaw"
        assert request["images"][0]["mimeType"] == "image/png"
        assert base64.b64decode(request["images"][0]["data"]) == b"png-bytes"
        return subprocess.CompletedProcess(
            args,
            0,
            stdout=json.dumps({"payloads": [{"text": "reviewed"}]}),
            stderr="",
        )

    result = OpenClawCodexBackend(command="openclaw", sync_runner=fake_run).generate(
        AIRequest(
            prompt="Inspect the page",
            image_inputs=(AIImageInput(content=b"png-bytes"),),
        )
    )

    assert result.text == "reviewed"
    assert not Path(captured_request_path).exists()


def test_openai_api_adapter_uses_responses_api_and_returns_same_contract() -> None:
    create = Mock(
        return_value=fake_openai_response(
            text='{"answer":"ready"}',
            response_id="resp_tasko_123",
        )
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    result = OpenAIAPIBackend(
        api_key="test-key",
        base_url="https://api.openai.test/v1/",
        client=client,
    ).generate(
        AIRequest(
            prompt="Return JSON",
            model="openai/gpt-5.6-terra",
            thinking="low",
            structured=True,
        )
    )

    create.assert_called_once_with(
        model="gpt-5.6-terra",
        input="Return JSON",
        store=False,
        timeout=120,
        reasoning={"effort": "low"},
        text={"format": {"type": "json_object"}},
    )
    assert result.text == '{"answer":"ready"}'
    assert result.structured_data == {"answer": "ready"}
    assert result.model == "gpt-5.6-terra"
    assert result.backend == "openai_api"
    assert result.usage.total_tokens == 22
    assert result.session_id == "resp_tasko_123"


def test_openai_api_adapter_uses_pydantic_structured_outputs() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            request=request,
            json={
                "id": "resp_structured_123",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "error": None,
                "incomplete_details": None,
                "model": "gpt-5.6-terra",
                "output": [
                    {
                        "id": "msg_123",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"answer":"ready"}',
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 18,
                    "output_tokens": 4,
                    "total_tokens": 22,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as http_client:
        sdk_client = OpenAI(
            api_key="test-key",
            max_retries=0,
            http_client=http_client,
        )
        result = OpenAIAPIBackend(api_key="test-key", client=sdk_client).generate(
            AIRequest(
                prompt="Return a strict answer",
                model="gpt-5.6-terra",
                timeout_seconds=45,
                response_model=AnswerPayload,
            )
        )

    assert captured["store"] is False
    assert captured["model"] == "gpt-5.6-terra"
    assert captured["input"] == "Return a strict answer"
    text_format = captured["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"]["additionalProperties"] is False
    assert result.structured_data == {"answer": "ready"}


def test_openai_api_adapter_supports_async_chat_calls() -> None:
    create = AsyncMock(
        return_value=fake_openai_response(
            text="Async response",
            response_id="resp_async_123",
        )
    )
    async_client = SimpleNamespace(responses=SimpleNamespace(create=create))

    async def invoke() -> AIResult:
        backend = OpenAIAPIBackend(api_key="test-key", async_client=async_client)
        return await backend.agenerate(AIRequest(prompt="Answer", model="gpt-5.6-terra"))

    result = asyncio.run(invoke())

    assert result.text == "Async response"
    assert result.session_id == "resp_async_123"
    assert result.usage.total_tokens == 22
    create.assert_awaited_once_with(
        model="gpt-5.6-terra",
        input="Answer",
        store=False,
        timeout=120,
    )


def test_openai_api_adapter_supports_web_search_and_pdf_page_images() -> None:
    create = Mock(
        return_value=fake_openai_response(
            text='{"answer":"looks clean"}',
            response_id="resp_review_123",
        )
    )
    client = SimpleNamespace(responses=SimpleNamespace(create=create))

    OpenAIAPIBackend(api_key="test-key", client=client).generate(
        AIRequest(
            prompt="Inspect the rendered page and research Acme.",
            model="gpt-5.6-terra",
            enable_web_search=True,
            image_inputs=(AIImageInput(content=b"png-bytes"),),
        )
    )

    request = create.call_args.kwargs
    assert request["tools"] == [{"type": "web_search"}]
    assert request["include"] == ["web_search_call.action.sources"]
    assert request["max_tool_calls"] == 6
    content = request["input"][0]["content"]
    assert content[0] == {
        "type": "input_text",
        "text": "Inspect the rendered page and research Acme.",
    }
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert content[1]["detail"] == "high"


@pytest.mark.parametrize(
    ("sdk_error", "code", "retryable"),
    [
        (
            APITimeoutError(httpx.Request("POST", "https://api.openai.test/v1/responses")),
            "timeout",
            True,
        ),
        (
            RateLimitError(
                "rate limit",
                response=httpx.Response(
                    429,
                    request=httpx.Request("POST", "https://api.openai.test/v1/responses"),
                ),
                body=None,
            ),
            "rate_limited",
            True,
        ),
        (
            AuthenticationError(
                "invalid key",
                response=httpx.Response(
                    401,
                    request=httpx.Request("POST", "https://api.openai.test/v1/responses"),
                ),
                body=None,
            ),
            "authentication",
            False,
        ),
    ],
)
def test_openai_api_adapter_classifies_sdk_errors(
    sdk_error: Exception,
    code: str,
    retryable: bool,
) -> None:
    client = SimpleNamespace(responses=SimpleNamespace(create=Mock(side_effect=sdk_error)))

    with pytest.raises(AIBackendError) as exc_info:
        OpenAIAPIBackend(api_key="test-key", client=client).generate(
            AIRequest(prompt="test", model="gpt-5.6-terra")
        )

    assert exc_info.value.code == code
    assert exc_info.value.retryable is retryable


def test_backend_factory_supports_both_modes_and_requires_direct_api_credentials() -> None:
    assert create_ai_backend(mode="openclaw_codex").name == "openclaw_codex"
    assert create_ai_backend(mode="openai_api", openai_api_key="key").name == "openai_api"

    backend = create_ai_backend(mode="openai_api")
    with pytest.raises(AIBackendError, match="OPENAI_API_KEY"):
        backend.generate(AIRequest(prompt="test", model="gpt-5.6-terra"))


def test_provider_neutral_retry_policy_uses_exponential_backoff(monkeypatch) -> None:
    attempts = 0
    delays: list[float] = []

    class FlakyBackend:
        name = "openai_api"

        def generate(self, _: AIRequest) -> AIResult:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise AIBackendError("temporary", retryable=True)
            return AIResult(
                text="ready",
                structured_data=None,
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="resp-ready",
            )

    monkeypatch.setattr("app.services.ai_backend.time.sleep", delays.append)

    result = generate_with_retries(
        FlakyBackend(),
        AIRequest(prompt="test"),
        max_attempts=3,
        retry_backoff_seconds=0.5,
    )

    assert result.text == "ready"
    assert attempts == 3
    assert delays == [0.5, 1.0]
