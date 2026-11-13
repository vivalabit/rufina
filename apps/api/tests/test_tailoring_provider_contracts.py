"""The tailoring response models must pass through each provider SDK's structured output.

Both SDKs convert a Pydantic model into a strict JSON schema on the client and
parse the answer back into it. These tests run the real SDK clients against a
local transport, so an unsupported model shape fails here and not in a run.
"""

from __future__ import annotations

import json

import anthropic
import httpx
import httpx2
import openai
import pytest
from pydantic import BaseModel

from app.services.ai_backend import AIRequest, AnthropicAPIBackend, OpenAIAPIBackend
from app.services.ats.cover_letter import LetterDraft
from app.services.ats.models import JobTargetDraft
from app.services.ats.wording import WordingDraft

ANSWERS: dict[type[BaseModel], dict] = {
    WordingDraft: {
        "summary": "Backend developer.",
        "statements": [{"id": "s1", "text": "Built services.", "emphasis": ["services"]}],
    },
    LetterDraft: {
        "contact_name": "",
        "paragraphs": [{"text": "I build services.", "statement_ids": ["s1"]}],
    },
    JobTargetDraft: {
        "title": "Backend Engineer",
        "seniority": "mid",
        "language": "en",
        "knockouts": [
            {
                "kind": "language",
                "requirement": "German B2",
                "language": "de",
                "cefr_level": "B2",
                "years": None,
            }
        ],
        "responsibilities": ["Build services"],
        "skills": [{"surface_form": "Python", "importance": "required", "min_years": 2}],
    },
}


def _schema_properties(schema: dict) -> set[str]:
    return set(schema.get("properties", {}))


@pytest.mark.parametrize("response_model", list(ANSWERS))
def test_openai_structured_output_accepts_the_tailoring_models(response_model) -> None:
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp_1",
                "object": "response",
                "created_at": 1,
                "model": "gpt-6.1-sol",
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg_1",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(ANSWERS[response_model]),
                                "annotations": [],
                            }
                        ],
                    }
                ],
                "parallel_tool_calls": True,
                "tool_choice": "auto",
                "tools": [],
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    client = openai.OpenAI(
        api_key="test-key",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    backend = OpenAIAPIBackend(api_key="test-key", default_model="gpt-6.1-sol", client=client)

    result = backend.generate(
        AIRequest(prompt="Return JSON.", structured=True, response_model=response_model)
    )

    schema = seen["text"]["format"]["schema"]
    assert seen["text"]["format"]["type"] == "json_schema"
    assert _schema_properties(schema) == set(response_model.model_fields)
    assert response_model.model_validate(result.structured_data) == response_model.model_validate(
        ANSWERS[response_model]
    )


@pytest.mark.parametrize("response_model", list(ANSWERS))
def test_anthropic_structured_output_accepts_the_tailoring_models(response_model) -> None:
    seen: dict = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen.update(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-sonnet-5-5",
                "content": [{"type": "text", "text": json.dumps(ANSWERS[response_model])}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        )

    client = anthropic.Anthropic(
        api_key="test-key",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    backend = AnthropicAPIBackend(
        api_key="test-key", default_model="claude-sonnet-5-5", client=client
    )

    result = backend.generate(
        AIRequest(prompt="Return JSON.", structured=True, response_model=response_model)
    )

    assert seen["model"] == "claude-sonnet-5-5"
    assert "schema" in json.dumps(seen)
    assert response_model.model_validate(result.structured_data) == response_model.model_validate(
        ANSWERS[response_model]
    )
