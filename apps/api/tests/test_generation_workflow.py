from __future__ import annotations

import json
from io import BytesIO

import pytest
from docx import Document
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from tailoring_fixtures import FakeTailoringBackend, runtime_settings, seed_tailoring_sources

from app.api.profile import get_or_create_profile
from app.core.database import Base
from app.models.documents import DocumentFileRecord, DocumentRecord
from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationRunArtifactRecord,
    GenerationRunCheckRecord,
    GenerationRunEventRecord,
    GenerationRunStartRequest,
)
from app.services.document_rendering import extract_pdf_text, pdf_page_count
from app.services.generation_store import create_generation_run, request_run_cancellation
from app.services.generation_worker import run_generation_cycle
from app.services.generation_workflow import GenerationWorkflow, GenerationWorkflowError
from app.services.profile_versions import update_profile_data

SOURCE_STATEMENT = (
    "Cut report generation time by 40% by rebuilding the export service in Python with "
    "FastAPI and PostgreSQL."
)
INGESTION_STATEMENT = (
    "Processed 2 TB of retail data per month by building ingestion pipelines that run on "
    "Kubernetes."
)


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _start(
    key: str = "run-1",
    *,
    document_types: tuple[str, ...] = ("tailored_resume",),
    formatting: dict | None = None,
    language: str = "Auto",
    preferences: str = "",
) -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=document_types,
        language=language,
        formattingParameters=formatting or {},
        userPreferences=preferences,
        idempotencyKey=key,
    )


def _execute(
    sessions: sessionmaker[Session],
    backend: FakeTailoringBackend,
    start: GenerationRunStartRequest,
    application_id: str = "application-1",
) -> str:
    settings = runtime_settings()
    with sessions() as db:
        run_id = create_generation_run(
            db, application_id=application_id, request=start, settings=settings
        ).id
    assert (
        run_generation_cycle(
            settings=settings,
            session_factory=sessions,
            workflow_factory=lambda s: GenerationWorkflow(settings=s, backend=backend),
        )
        == run_id
    )
    return run_id


def _artifact(db: Session, run_id: str, artifact_type: str) -> GenerationRunArtifactRecord:
    return db.scalars(
        select(GenerationRunArtifactRecord)
        .where(
            GenerationRunArtifactRecord.run_id == run_id,
            GenerationRunArtifactRecord.artifact_type == artifact_type,
        )
        .order_by(GenerationRunArtifactRecord.version.desc())
    ).first()


def test_one_click_run_delivers_a_checked_resume_without_pausing(sessions) -> None:
    seed_tailoring_sources(sessions)
    rewritten = (
        "Rebuilt the export service in Python with FastAPI and PostgreSQL, cutting report "
        "generation time by 40%."
    )
    backend = FakeTailoringBackend(rewrites={SOURCE_STATEMENT: rewritten})

    run_id = _execute(sessions, backend, _start())

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "completed", run.error
        assert run.stage == "final_review"
        assert run.pending_question is None
        stages = [
            event.kind
            for event in db.scalars(
                select(GenerationRunEventRecord)
                .where(GenerationRunEventRecord.run_id == run_id)
                .order_by(GenerationRunEventRecord.sequence)
            )
            if not event.kind.startswith("artifact.")
        ]
        assert stages == [
            "run.created",
            "vacancy.started",
            "plan.completed",
            "wording.started",
            "fact_check.completed",
            "render.started",
            "run.completed",
        ]
        # One request for the vacancy and one for all statements.
        assert backend.calls == ["vacancy", "wording"]

        report = run.result["tailoring"]
        assert report["score"]["after"] >= report["score"]["before"]
        assert report["statements"]["reworded"] == 1
        assert {"label": "Terraform", "importance": "preferred"} in report["gaps"]
        assert run.result["render"]["templateId"] == "swiss_classic"
        assert run.result["render"]["pages"] == {"tailored_resume": 1}
        assert run.result["usage"]["requests"] == 1

        document = db.get(DocumentRecord, run.result["documents"][0]["id"])
        assert document.type == "tailored_resume"
        pdf = _artifact(db, run_id, "resume_pdf")
        assert pdf.file_name == "Mira_Keller_CV_Northwind_Analytics_AG.pdf"
        assert pdf.document_id == document.id
        text = " ".join(extract_pdf_text(pdf.content).split())
        assert rewritten in text
        # Nothing from the profile is left out while the page has room, and the
        # statements of a role are ordered by their value for the vacancy.
        assert "Organized the weekly team lunch rota" in text
        assert text.index(rewritten) < text.index("Organized the weekly team lunch rota")
        docx = _artifact(db, run_id, "resume_docx")
        paragraphs = "\n".join(p.text for p in Document(BytesIO(docx.content)).paragraphs)
        assert rewritten in paragraphs

        checks = {
            check.check_type: check.status
            for check in db.scalars(
                select(GenerationRunCheckRecord).where(GenerationRunCheckRecord.run_id == run_id)
            )
        }
        assert checks == {"fact_check": "passed", "page_limit": "passed", "ats_text": "passed"}


def test_invented_facts_never_reach_the_document(sessions) -> None:
    seed_tailoring_sources(sessions)
    backend = FakeTailoringBackend(
        rewrites={INGESTION_STATEMENT: "Processed 9 TB per month with Kafka and Terraform."}
    )

    run_id = _execute(sessions, backend, _start())

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "completed", run.error
        # The rejected statement was retried once, then kept in the profile wording.
        assert backend.calls == ["vacancy", "wording", "wording"]
        text = extract_pdf_text(_artifact(db, run_id, "resume_pdf").content)
        assert "9 TB" not in text
        assert "Terraform" not in text
        assert "Processed 2 TB of retail data" in " ".join(text.split())
        kept = run.result["tailoring"]["keptOriginal"]
        assert len(kept) == 1
        assert any("9" in reason for reason in kept[0]["reasons"])
        assert run.result["warnings"]
        fact_check = db.scalar(
            select(GenerationRunCheckRecord).where(
                GenerationRunCheckRecord.run_id == run_id,
                GenerationRunCheckRecord.check_type == "fact_check",
            )
        )
        assert fact_check.status == "warning"


def test_cover_letter_is_written_in_the_same_run_and_design(sessions) -> None:
    seed_tailoring_sources(sessions)
    backend = FakeTailoringBackend()

    run_id = _execute(
        sessions, backend, _start(document_types=("tailored_resume", "cover_letter"))
    )

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "completed", run.error
        assert sorted(backend.calls) == ["letter", "vacancy", "wording"]
        assert [item["type"] for item in run.result["documents"]] == [
            "tailored_resume",
            "cover_letter",
        ]
        letter = _artifact(db, run_id, "cover_letter_pdf")
        assert letter.file_name == "Mira_Keller_Cover_Letter_Northwind_Analytics_AG.pdf"
        text = " ".join(extract_pdf_text(letter.content).split())
        assert "Application for Backend Engineer (Python)" in text
        assert "cut report generation time by 40%" in text
        assert pdf_page_count(letter.content) == 1
        assert _artifact(db, run_id, "cover_letter_docx") is not None


def test_template_switch_renders_the_same_content_without_a_model(sessions) -> None:
    seed_tailoring_sources(sessions)
    backend = FakeTailoringBackend()
    run_id = _execute(sessions, backend, _start())
    calls_after_run = list(backend.calls)

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        first = _artifact(db, run_id, "resume_pdf")
        first_sha, first_document_version = first.content_sha256, first.document_version
        GenerationWorkflow(settings=runtime_settings(), backend=backend).render_in_template(
            db, run, template_id="modern_single"
        )

        assert backend.calls == calls_after_run
        assert run.status == "completed"
        assert run.result["render"]["templateId"] == "modern_single"
        second = _artifact(db, run_id, "resume_pdf")
        assert second.version == 2
        assert second.content_sha256 != first_sha
        assert second.artifact_metadata["templateId"] == "modern_single"
        assert second.document_version == first_document_version + 1
        document = db.get(DocumentRecord, run.result["documents"][0]["id"])
        assert document.current_version == second.document_version
        files = db.scalars(
            select(DocumentFileRecord).where(DocumentFileRecord.document_id == document.id)
        ).all()
        assert {item.renderer_template_id for item in files} == {"swiss_classic", "modern_single"}
        assert "Cut report generation time by 40%" in " ".join(
            extract_pdf_text(second.content).split()
        )

        with pytest.raises(GenerationWorkflowError) as failure:
            GenerationWorkflow(settings=runtime_settings()).render_in_template(
                db, run, template_id="missing-template"
            )
        assert failure.value.code == "document_template_unsupported"


def test_long_profile_is_fitted_to_the_requested_page_limit(sessions) -> None:
    seed_tailoring_sources(sessions, extra_bullets_per_role=12)
    backend = FakeTailoringBackend()

    run_id = _execute(
        sessions, backend, _start(formatting={"tailored_resume": {"maxPages": 1}})
    )

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "completed", run.error
        assert run.result["render"]["pages"]["tailored_resume"] == 1
        # The complete content is kept, so a roomier template can show more of it.
        stored = run.result["content"]["resume"]["experiences"]
        fitted = run.result["draft"]["resume"]["experiences"]
        dropped = run.result["render"]["droppedStatementIds"]
        # Each role keeps its eight most valuable statements; the rest never render.
        assert sum(len(item["bullets"]) for item in stored) == 16
        assert sum(len(item["bullets"]) for item in stored) == len(dropped) + sum(
            len(item["bullets"]) for item in fitted
        )
        text = extract_pdf_text(_artifact(db, run_id, "resume_pdf").content)
        # The statements that match the vacancy survive.
        assert "Cut report generation time by 40%" in " ".join(text.split())


def test_vacancy_analysis_is_reused_by_the_next_run_of_the_application(sessions) -> None:
    seed_tailoring_sources(sessions)
    backend = FakeTailoringBackend()

    _execute(sessions, backend, _start("run-1"))
    _execute(sessions, backend, _start("run-2", preferences="More concise."))

    assert backend.calls.count("vacancy") == 1
    assert backend.calls.count("wording") == 2


def test_vacancy_model_failure_falls_back_to_the_skill_dictionary(sessions) -> None:
    seed_tailoring_sources(sessions)
    backend = FakeTailoringBackend(fail=("vacancy",))

    run_id = _execute(sessions, backend, _start())

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "completed", run.error
        assert run.result["tailoring"]["vacancy"]["parsedBy"] == "dictionary"
        target = json.loads(_artifact(db, run_id, "job_target_json").content)
        assert {skill["surfaceForm"] for skill in target["skills"]} >= {"Python", "FastAPI"}


def test_run_fails_with_the_backend_error_when_no_wording_can_be_requested(sessions) -> None:
    seed_tailoring_sources(sessions)
    backend = FakeTailoringBackend(fail=("wording",))

    run_id = _execute(sessions, backend, _start())

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "failed"
        assert run.error["code"] == "provider_error"
        assert run.error["retryable"] is True
        assert db.scalar(select(DocumentRecord)) is None


def test_cancellation_requested_during_a_run_stops_before_rendering(sessions) -> None:
    seed_tailoring_sources(sessions)

    class CancellingBackend(FakeTailoringBackend):
        def generate(self, request):
            result = super().generate(request)
            if self.calls[-1] == "wording":
                with sessions() as other:
                    run = other.scalar(select(ApplicationGenerationRunRecord))
                    request_run_cancellation(other, run=run, expected_revision=run.revision)
            return result

    run_id = _execute(sessions, CancellingBackend(), _start())

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "cancelled"
        assert _artifact(db, run_id, "resume_pdf") is None


def test_run_explains_an_empty_profile_instead_of_failing_obscurely(sessions) -> None:
    seed_tailoring_sources(sessions)
    with sessions() as db:
        profile = get_or_create_profile(db)
        update_profile_data(db, profile, data={**profile.data, "experience": "[]"}, reason="test")
        db.commit()
    backend = FakeTailoringBackend()

    run_id = _execute(sessions, backend, _start())

    with sessions() as db:
        run = db.get(ApplicationGenerationRunRecord, run_id)
        assert run.status == "failed"
        assert run.error["code"] == "profile_incomplete"
        assert "no work experience" in run.error["message"]
        assert backend.calls == []


def test_default_page_limit_is_two_pages_except_for_a_short_career() -> None:
    from types import SimpleNamespace

    from tailoring_fixtures import master_resume_payload

    from app.models.resume import MasterResume
    from app.services.generation_workflow import max_pages

    def master(start: str) -> MasterResume:
        payload = master_resume_payload()
        for role in payload["experiences"]:
            role["startDate"], role["endDate"], role["isCurrent"] = start, "", True
        return MasterResume.model_validate(payload)

    request = SimpleNamespace(formatting_parameters={})
    assert max_pages(request, "tailored_resume", master("01/2018")) == 2
    assert max_pages(request, "tailored_resume", master("01/2026")) == 1
    assert max_pages(request, "cover_letter", master("01/2018")) == 1
    configured = SimpleNamespace(formatting_parameters={"tailored_resume": {"maxPages": 3}})
    assert max_pages(configured, "tailored_resume", master("01/2026")) == 3


def test_two_applications_for_one_posting_share_the_vacancy_analysis(sessions) -> None:
    from app.models.applications import StoredApplicationRecord

    seed_tailoring_sources(sessions)
    with sessions() as db:
        db.add(
            StoredApplicationRecord(
                id="application-2",
                data={"id": "application-2", "status": "draft", "job": {"id": "job-1"}},
            )
        )
        db.commit()
    backend = FakeTailoringBackend()

    _execute(sessions, backend, _start("run-1"))
    second = _execute(sessions, backend, _start("run-2"), application_id="application-2")

    assert backend.calls.count("vacancy") == 1
    with sessions() as db:
        assert _artifact(db, second, "job_target_json").artifact_metadata["cached"] is True
