import base64
from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest

from app.core.settings import Settings, get_settings
from app.main import app
from app.models.resume import (
    MasterResume,
    ResumeSourceExtraction,
    ResumeSourceFragment,
)
from app.services.ai_backend import AIRequest, AIResult, AIUsage
from app.services.ai_privacy import require_current_ai_consent
from app.services.resume_master_import import (
    MasterResumeImportError,
    MasterResumeImportOutcome,
    import_master_resume_with_ai,
)


@pytest.fixture(autouse=True)
def bypass_ai_consent_boundary() -> Generator[None, None, None]:
    app.dependency_overrides[require_current_ai_consent] = lambda: None
    try:
        yield
    finally:
        app.dependency_overrides.pop(require_current_ai_consent, None)


def source_extraction() -> ResumeSourceExtraction:
    return ResumeSourceExtraction(
        source_format="docx",
        layout="one_column",
        page_count=None,
        used_ocr=False,
        fragments=[
            ResumeSourceFragment(
                id="source:fragment-000001",
                text="Ada Lovelace",
                order=0,
                kind="paragraph",
                extraction_method="docx",
            ),
            ResumeSourceFragment(
                id="source:fragment-000002",
                text="Platform engineer building reliable Python services.",
                order=1,
                kind="paragraph",
                extraction_method="docx",
            ),
        ],
    )


def master_resume_payload(master_resume_id: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": master_resume_id,
        "language": "English",
        "basics": {
            "fullName": "Ada Lovelace",
            "headline": "Platform Engineer",
        },
        "summary": {
            "text": "Platform engineer building reliable Python services.",
            "evidenceIds": ["source:fragment-000002"],
        },
        "experiences": [],
        "skills": [],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [
            {
                "id": "source:fragment-000002",
                "type": "source",
                "text": "Platform engineer building reliable Python services.",
            }
        ],
        "sectionOrder": ["summary"],
    }


def test_master_resume_import_uses_exactly_one_typed_ai_request() -> None:
    requests: list[AIRequest] = []
    master_resume_id = "master-import-1"

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            return AIResult(
                text="",
                structured_data=master_resume_payload(master_resume_id),
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="response-master-import",
            )

    outcome = import_master_resume_with_ai(
        source=source_extraction(),
        master_resume_id=master_resume_id,
        backend=FakeBackend(),
        model="gpt-5.6-terra",
        agent_id="rufina-assistant",
        thinking="medium",
        timeout_seconds=120,
    )

    assert len(requests) == 1
    assert requests[0].structured is True
    assert requests[0].response_model is MasterResume
    assert "ONE-TIME MASTER RESUME IMPORT" in requests[0].prompt
    assert "not a vacancy analysis" in requests[0].prompt
    assert "source:fragment-000002" in requests[0].prompt
    assert outcome.master_resume.id == master_resume_id
    assert outcome.master_resume.summary is not None
    assert outcome.backend == "openai_api"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda payload: payload.update({"id": "ai-changed-id"}),
            "changed the server-assigned resume ID",
        ),
        (
            lambda payload: payload["evidence"][0].update(
                {"text": "AI changed the source"}
            ),
            "changed source evidence",
        ),
    ],
)
def test_master_resume_import_rejects_untrusted_ids_and_evidence(
    mutation,
    message: str,
) -> None:
    master_resume_id = "master-import-1"
    payload = master_resume_payload(master_resume_id)
    mutation(payload)

    class FakeBackend:
        name = "openai_api"

        def generate(self, _request: AIRequest) -> AIResult:
            return AIResult(
                text="",
                structured_data=payload,
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="response-master-import",
            )

    with pytest.raises(MasterResumeImportError, match=message):
        import_master_resume_with_ai(
            source=source_extraction(),
            master_resume_id=master_resume_id,
            backend=FakeBackend(),
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="medium",
            timeout_seconds=120,
        )


def test_master_resume_import_endpoint_returns_typed_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = source_extraction()
    master_resume = MasterResume.model_validate(
        master_resume_payload("master-import-endpoint")
    )
    calls: list[tuple[ResumeSourceExtraction, str]] = []

    def fake_parse(
        extracted_source: ResumeSourceExtraction,
        master_resume_id: str,
        _settings: Settings,
    ) -> MasterResumeImportOutcome:
        calls.append((extracted_source, master_resume_id))
        return MasterResumeImportOutcome(
            master_resume=master_resume,
            model="gpt-5.6-terra",
            backend="openai_api",
        )

    monkeypatch.setattr(
        "app.api.profile.extract_resume_source",
        lambda **_kwargs: source,
    )
    monkeypatch.setattr(
        "app.api.profile.parse_master_resume_with_selected_backend",
        fake_parse,
    )
    app.dependency_overrides[get_settings] = lambda: Settings(
        openclaw_resume_import_enabled=True
    )
    encoded = base64.b64encode(b"fake-docx").decode()
    try:
        response = TestClient(app).post(
            "/profile/import-master-resume",
            json={
                "resume_file_name": "resume.docx",
                "resume_data_url": (
                    "data:application/vnd.openxmlformats-officedocument."
                    f"wordprocessingml.document;base64,{encoded}"
                ),
            },
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert len(calls) == 1
    assert len(calls[0][1]) == 32
    assert response.json()["masterResume"]["id"] == "master-import-endpoint"
    assert response.json()["source"]["fragments"][0]["text"] == "Ada Lovelace"
    assert response.json()["backend"] == "openai_api"
