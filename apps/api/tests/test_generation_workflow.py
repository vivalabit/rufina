import hashlib
import json
from collections import deque
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.documents import DocumentFileRecord, DocumentRecord
from app.models.generation_runs import (
    GenerationRunArtifactRecord,
    GenerationRunCheckRecord,
    GenerationRunMessageRecord,
    GenerationRunStartRequest,
)
from app.models.generation_workflow import DraftBundle
from app.models.resume import MasterResume, ResumeMasterVersionRecord
from app.services.ai_backend import AIResult, AIUsage
from app.services.generation_grounding import (
    GenerationGroundingError,
    validate_grounded_bundle,
)
from app.services.generation_input import GenerationInputError
from app.services.generation_latex import CompiledDocument, build_resume_tex
from app.services.generation_resume_templates import resolve_generation_resume_template
from app.services.generation_store import create_generation_run
from app.services.generation_verification import PdfCheck, PdfVerificationReport, VerifiedPdf
from app.services.generation_workflow import GenerationWorkflow, GenerationWorkflowError


class FakeBackend:
    def __init__(
        self,
        payloads: list[dict[str, object]],
        *,
        name: str = "openclaw_codex",
    ) -> None:
        self.name = name
        self.payloads = deque(payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        payload = self.payloads.popleft()
        return AIResult(
            text=json.dumps(payload),
            structured_data=payload,
            model=request.model,
            backend=self.name,
            usage=AIUsage(input_tokens=10, output_tokens=20, total_tokens=30),
            latency_ms=5,
            session_id=request.session_id,
            raw_response=json.dumps(payload),
        )


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _settings(backend: str = "openclaw_codex") -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend_mode=backend,
        openai_api_model="gpt-direct",
        openai_api_reasoning_effort="medium",
        openai_api_timeout_seconds=120,
        openai_api_max_attempts=2,
        openai_api_retry_backoff_seconds=0,
        openclaw_command="openclaw",
        openclaw_assistant_agent_id="rufina-assistant",
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=1,
        openclaw_assistant_retry_backoff_seconds=0,
        openai_api_key="",
        openai_api_base_url="https://api.openai.com/v1",
    )


def _start() -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single"}},
        userPreferences="Keep it factual.",
        idempotencyKey="workflow-1",
    )


def _seed(sessions: sessionmaker[Session]) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        version = db.scalar(
            select(ResumeMasterVersionRecord).where(
                ResumeMasterVersionRecord.resume_master_id == "master-profile",
                ResumeMasterVersionRecord.version == 2,
            )
        )
        assert version is not None
        data = dict(version.data)
        data["summary"] = {"text": "Builds reliable platforms.", "evidenceIds": ["source:one"]}
        data["evidence"] = [
            {"id": "source:one", "type": "source", "text": "Builds reliable platforms."}
        ]
        data["sectionOrder"] = ["summary"]
        canonical = json.dumps(
            data, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode()
        db.execute(
            update(ResumeMasterVersionRecord)
            .where(ResumeMasterVersionRecord.id == version.id)
            .values(data=data, content_sha256=hashlib.sha256(canonical).hexdigest())
        )
        db.commit()


def _fit() -> dict[str, object]:
    return {
        "eligible": True,
        "overallScore": 82,
        "recommendation": "yes",
        "summary": "Good evidence-backed fit.",
        "strengths": ["Platform experience"],
        "gaps": ["No explicit Go experience"],
        "keywords": [
            {
                "term": "Python",
                "importance": "required",
                "support": "supported",
                "evidenceIds": [],
            }
        ],
        "clarificationQuestions": [],
    }


def _draft() -> dict[str, object]:
    return {
        "resume": {
            "schemaVersion": "1.0",
            "id": "tailored-1",
            "masterResumeId": "master-profile",
            "targetJobId": "vacancy-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace", "headline": "Platform Engineer"},
            "summary": {
                "text": "Builds reliable platforms.",
                "evidenceIds": ["source:one"],
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
                    "id": "source:one",
                    "type": "source",
                    "text": "Builds reliable platforms.",
                }
            ],
            "sectionOrder": ["summary"],
        },
        "coverLetter": None,
    }


def _review() -> dict[str, object]:
    return {
        "approved": True,
        "summary": "Grounded and consistent.",
        "findings": [],
        "meaningfulChanges": ["Focused the headline on platform engineering"],
        "companySources": [],
    }


def _visual_review() -> dict[str, object]:
    return {
        "approved": True,
        "summary": "Both rendered pages are balanced and readable.",
        "findings": [],
    }


def _renderer(bundle: DraftBundle) -> tuple[CompiledDocument, ...]:
    assert bundle.resume is not None
    return (
        CompiledDocument(
            document_type="tailored_resume",
            engine="lualatex",
            file_name="cv.pdf",
            tex_source=build_resume_tex(bundle.resume),
            pdf=b"%PDF-1.7\nfake",
            compile_log="ok",
        ),
    )


def _verifier(document: CompiledDocument, **_kwargs) -> VerifiedPdf:
    return VerifiedPdf(
        report=PdfVerificationReport(
            documentType=document.document_type,
            pageCount=1,
            extractedText="Ada Lovelace builds reliable platforms with Python.",
            checks=(PdfCheck(name="text_layer", status="passed", message="Readable"),),
        ),
        page_images=(b"fake-png",),
    )


@pytest.mark.parametrize("backend_name", ["openai_api", "openclaw_codex"])
def test_workflow_pauses_after_fit_then_uses_separate_author_and_reviewer_sessions(
    sessions: sessionmaker[Session],
    backend_name: str,
) -> None:
    _seed(sessions)
    settings = _settings(backend_name)
    backend = FakeBackend(
        [_fit(), _draft(), _review(), _visual_review()],
        name=backend_name,
    )
    workflow = GenerationWorkflow(
        settings=settings,
        backend=backend,
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=settings,
        )
        evaluation = workflow.evaluate_fit(db, run)
        assert evaluation.overall_score == 82
        assert run.status == "awaiting_approval"
        assert run.pending_question["id"] == "continue_after_fit"

        outcome = workflow.respond_to_fit(db, run, continue_generation=True)
        messages = db.scalars(
            select(GenerationRunMessageRecord)
            .where(GenerationRunMessageRecord.run_id == run.id)
            .order_by(GenerationRunMessageRecord.sequence)
        ).all()
        artifacts = db.scalars(
            select(GenerationRunArtifactRecord).where(GenerationRunArtifactRecord.run_id == run.id)
        ).all()
        checks = db.scalars(
            select(GenerationRunCheckRecord).where(GenerationRunCheckRecord.run_id == run.id)
        ).all()

    assert outcome is not None and outcome.review.approved is True
    assert run.status == "completed" and run.stage == "final_review"
    assert run.backend == backend_name
    assert any(request.enable_web_search for request in backend.requests)
    assert backend.requests[-1].image_inputs
    sessions_used = {request.session_id.rsplit(":", 1)[-1] for request in backend.requests}
    assert sessions_used == {"fit", "author", "reviewer"}
    assert {message.actor for message in messages} >= {"author", "reviewer", "user"}
    assert any(message.raw_response.startswith("{") for message in messages)
    assert "BEGIN UNTRUSTED APPLICATION DATA" in backend.requests[0].prompt
    assert {artifact.artifact_type for artifact in artifacts} >= {
        "fit_evaluation_json",
        "draft_bundle_json",
        "review_feedback_json",
        "reviewed_draft_bundle_json",
        "resume_pdf",
        "resume_tex",
        "visual_review_json",
    }
    assert checks and all(check.artifact_sha256 for check in checks)
    assert run.result["documents"][0]["pdfUrl"].endswith("/pdf")


@pytest.mark.parametrize("template_id", ["moderncv_banking", "ishchenko_classic"])
@pytest.mark.parametrize("recovered", [False, True])
def test_selected_resume_template_survives_draft_repair_recovery_and_import(
    sessions: sessionmaker[Session],
    template_id: str,
    recovered: bool,
) -> None:
    _seed(sessions)
    seen_templates: list[str] = []

    def selected_renderer(bundle: DraftBundle, *, resume_template_id: str):
        seen_templates.append(resume_template_id)
        return _renderer(bundle)

    visual_failure = {
        "approved": False,
        "summary": "Shorten the last paragraph to fit the page.",
        "findings": [],
    }
    payloads = [visual_failure, _draft(), _visual_review()]
    if not recovered:
        payloads = [_fit(), _draft(), _review(), *payloads]
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend(payloads),
        renderer=selected_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start().model_copy(
                update={"formatting_parameters": {"tailored_resume": {"templateId": template_id}}}
            ),
            settings=_settings(),
        )
        if recovered:
            run.stage = "pdf_checks"
            run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
            db.commit()
            workflow.resume_pdf_checks(db, run)
        else:
            workflow.evaluate_fit(db, run)
            workflow.respond_to_fit(db, run, continue_generation=True)
        assert run.status == "completed"
        document_file = db.scalar(select(DocumentFileRecord))
        assert document_file is not None
        assert document_file.renderer_template_id == template_id
        assert document_file.renderer_design_sha256 == (
            resolve_generation_resume_template(template_id).content_sha256
        )
        pdf = db.scalar(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type == "resume_pdf",
            )
        )
        assert pdf is not None and pdf.artifact_metadata["templateId"] == template_id
    assert seen_templates == [template_id, template_id]


@pytest.mark.parametrize(
    ("legacy_id", "legacy_version"),
    [("classic_single", "1.0.1"), ("b426540f-a1e2-4e8b-965e-10ab38b28b40", "2")],
)
def test_recovered_legacy_snapshot_keeps_input_and_records_actual_banking_artifact_metadata(
    sessions: sessionmaker[Session],
    legacy_id: str,
    legacy_version: str,
) -> None:
    _seed(sessions)
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([_visual_review()]),
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        legacy = {
            **run.input_snapshot["templates"][0],
            "templateId": legacy_id,
            "templateVersion": legacy_version,
            "contentSha256": "f" * 64,
        }
        run.input_snapshot = {**run.input_snapshot, "templates": [legacy]}
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        workflow.resume_pdf_checks(db, run)

        assert run.status == "completed"
        assert run.input_snapshot["templates"] == [legacy]
        document_file = db.scalar(select(DocumentFileRecord))
        assert document_file is not None
        assert document_file.renderer_template_id == "moderncv_banking"
        assert document_file.renderer_design_sha256 != legacy["contentSha256"]


def test_recovery_rejects_changed_template_before_rendering_or_publication(
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _seed(sessions)
    from app.services import generation_resume_templates

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([]),
        renderer=lambda _bundle: pytest.fail("Changed template must not be rendered"),
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        changed_source = tmp_path / "generation_latex.py"
        changed_source.write_text("# A different deployed renderer\n")
        monkeypatch.setattr(generation_resume_templates, "_RENDERER_SOURCE", changed_source)

        with pytest.raises(GenerationInputError, match="Start a new generation run") as failure:
            workflow.resume_pdf_checks(db, run)

        assert failure.value.code == "resume_template_changed"
        assert run.status == "failed"
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_renderer_type_error_is_not_retried_without_template_selection(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    calls: list[str] = []

    def broken_renderer(_bundle: DraftBundle, *, resume_template_id: str):
        calls.append(resume_template_id)
        raise TypeError("An internal rendering error")

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([]),
        renderer=broken_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        with pytest.raises(TypeError, match="internal rendering error"):
            workflow.resume_pdf_checks(db, run)
        assert run.status == "failed"
    assert calls == ["moderncv_banking"]


def test_declining_fit_finishes_without_drafting(sessions: sessionmaker[Session]) -> None:
    _seed(sessions)
    backend = FakeBackend([_fit()])
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        workflow.evaluate_fit(db, run)
        assert workflow.respond_to_fit(db, run, continue_generation=False) is None

    assert run.status == "cancelled"
    assert len(backend.requests) == 1


def test_recovered_pdf_failure_is_terminal_and_does_not_publish_partial_documents(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)

    def unavailable_compiler(_bundle: DraftBundle):
        raise GenerationWorkflowError(
            "No supported TeX compiler is installed",
            code="pdf_compiler_unavailable",
        )

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([]),
        renderer=unavailable_compiler,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "queued"
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()

        with pytest.raises(GenerationWorkflowError, match="No supported TeX"):
            workflow.resume_pdf_checks(db, run)

        assert run.status == "failed"
        assert run.error == {
            "code": "pdf_compiler_unavailable",
            "message": "No supported TeX compiler is installed",
            "retryable": False,
        }
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_pdf_verification_failure_preserves_actionable_terminal_diagnostics(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    visual_failure = {
        "approved": False,
        "summary": "The last page is visually unsafe.",
        "findings": [
            {
                "document": "resume",
                "page": 1,
                "severity": "blocking",
                "message": "Experience text overlaps the footer.",
            }
        ],
    }

    def failing_verifier(document: CompiledDocument, **_kwargs) -> VerifiedPdf:
        return VerifiedPdf(
            report=PdfVerificationReport(
                documentType=document.document_type,
                pageCount=3,
                extractedText="Ada Lovelace builds reliable platforms.",
                checks=(
                    PdfCheck(name="text_layer", status="passed", message="Readable"),
                    PdfCheck(
                        name="page_count",
                        status="failed",
                        message="Found 3 page(s); allowed 1-2",
                    ),
                    PdfCheck(
                        name="keyword:Python",
                        status="warning",
                        message="Keyword missing: Python",
                    ),
                ),
            ),
            page_images=(b"fake-png",),
        )

    backend = FakeBackend(
        [visual_failure, _draft(), visual_failure, _draft(), visual_failure]
    )
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=_renderer,
        verifier=failing_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "queued"
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()

        with pytest.raises(GenerationWorkflowError) as exc_info:
            workflow.resume_pdf_checks(db, run)

        message = str(exc_info.value)
        assert exc_info.value.code == "pdf_verification_failed"
        assert exc_info.value.retryable is True
        assert message.startswith("PDF verification did not pass after three attempts:")
        assert "Found 3 page(s); allowed 1-2" in message
        assert "The last page is visually unsafe." in message
        assert "Experience text overlaps the footer." in message
        assert "Readable" not in message
        assert "Keyword missing: Python" not in message
        assert run.status == "failed"
        assert run.error == {
            "code": "pdf_verification_failed",
            "message": message,
            "retryable": True,
        }
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        visual_artifacts = db.scalars(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type == "visual_review_json",
            )
        ).all()
        assert len(visual_artifacts) == 3


def test_visual_rejection_blocks_publication_after_deterministic_checks_pass(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    visual_failure = {
        "approved": False,
        "summary": "The rendered page could not be safely approved.",
        "findings": [
            {
                "document": "resume",
                "page": 1,
                "severity": "blocking",
                "message": "Experience text overlaps the footer.",
            }
        ],
    }
    backend = FakeBackend(
        [visual_failure, _draft(), visual_failure, _draft(), visual_failure]
    )
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "queued"
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()

        with pytest.raises(GenerationWorkflowError) as exc_info:
            workflow.resume_pdf_checks(db, run)

        message = str(exc_info.value)
        assert "The rendered page could not be safely approved." in message
        assert "Experience text overlaps the footer." in message
        assert "CV:" not in message
        assert run.status == "failed"
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_grounding_rejects_modified_canonical_evidence() -> None:
    master = MasterResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "master-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace"},
            "summary": {"text": "Built APIs.", "evidenceIds": ["source:one"]},
            "evidence": [{"id": "source:one", "type": "source", "text": "Built APIs."}],
            "sectionOrder": ["summary"],
        }
    )
    bundle = DraftBundle.model_validate(
        {
            "resume": {
                "schemaVersion": "1.0",
                "id": "tailored-1",
                "masterResumeId": "master-1",
                "targetJobId": "job-1",
                "language": "English",
                "basics": {"fullName": "Ada Lovelace"},
                "summary": {
                    "text": "Built APIs for millions of users.",
                    "evidenceIds": ["source:one"],
                },
                "evidence": [
                    {
                        "id": "source:one",
                        "type": "source",
                        "text": "Built APIs for millions of users.",
                    }
                ],
                "sectionOrder": ["summary"],
            }
        }
    )

    with pytest.raises(GenerationGroundingError, match="non-canonical"):
        validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")
