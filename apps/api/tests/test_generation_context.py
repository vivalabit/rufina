from datetime import UTC, date, datetime
from dataclasses import replace
import hashlib
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.api.assistant import assistant_inputs_from_generation_context
from app.api.resume_tailoring import resume_tailoring_master_resume
from app.models.applications import CandidateConfirmationRecord, StoredApplicationRecord
from app.models.documents import DocumentTemplateRecord
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.models.resume import MasterResume
from app.services.ai_match import (
    DEFAULT_AI_MATCH_MODEL,
    MATCHER_VERSION,
    MATCH_PROMPT_VERSION,
    build_job_snapshot,
    build_job_snapshot_hash,
)
from app.services.candidate_snapshot import get_candidate_match_snapshot
from app.services.generation_context import (
    GenerationContextError,
    clarification_questions,
    load_authoritative_generation_context,
)
from app.services.job_match_store import APPLICATION_GUIDE_STORAGE_KEY


def generation_context_session(*, include_confirmation: bool = True) -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = Session(engine)
    now = datetime.now(UTC)
    profile_data = {
        "name": "Alex",
        "skills": "Python",
        "experience": json.dumps(
            [
                {
                    "id": "experience-acme",
                    "title": "Platform Engineer",
                    "company": "Acme",
                    "start_date": "2022-01",
                    "end_date": "2024-06",
                    "is_current": False,
                    "description": (
                        "Built production Python and FastAPI services. "
                        "Reduced request latency by 30%."
                    ),
                }
            ]
        ),
    }
    vacancy_data = {
        "id": "job-context",
        "title": "Platform Engineer",
        "company": "Acme",
    }
    profile = ProfilePayload.model_validate(profile_data)
    profile_hash = get_candidate_match_snapshot(db, profile=profile).profile_hash
    records = [
        StoredApplicationRecord(
            id="application-context",
            data={
                "id": "application-context",
                "status": "draft",
                "job": {"id": "job-context", "title": "Client vacancy copy"},
            },
        ),
        StoredJobRecord(
            id="job-context",
            data=vacancy_data,
        ),
        ProfileRecord(
            id="default",
            data=profile_data,
        ),
        JobMatchRecord(
            id="match-context",
            job_id="job-context",
            profile_hash=profile_hash,
            vacancy_hash=build_job_snapshot_hash(build_job_snapshot(vacancy_data)),
            model=DEFAULT_AI_MATCH_MODEL,
            prompt_version=MATCH_PROMPT_VERSION,
            matcher_version=MATCHER_VERSION,
            cache_key="cache-context",
            score=88,
            source="openclaw_codex",
            confidence="high",
            breakdown={
                APPLICATION_GUIDE_STORAGE_KEY: {
                    "language": "German",
                    "clarificationQuestions": [
                        {
                            "id": "production-python",
                            "requirement": "Production Python",
                            "question": "Have you used Python in production?",
                            "blocking": True,
                        }
                    ],
                    "evidenceMatrix": [],
                }
            },
            reasons=[],
            gaps=[],
            heuristic_score=88,
            created_at=now,
        ),
        DocumentTemplateRecord(
            id="template-context",
            type="cover_letter",
            name="Cover letter",
            file_name="cover.docx",
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            content_sha256=hashlib.sha256(b"docx").hexdigest(),
            content=b"docx",
            extracted_text="Original cover letter",
            created_at=now,
            updated_at=now,
        ),
    ]
    if include_confirmation:
        records.append(
            CandidateConfirmationRecord(
                application_id="application-context",
                question_id="production-python",
                requirement="Stale client requirement",
                response="yes",
                example_text="Built two production Python services.",
                blocking=False,
                updated_at=now,
            )
        )
    db.add_all(records)
    db.commit()
    return db


def test_loads_complete_authoritative_generation_context() -> None:
    with generation_context_session() as db:
        context = load_authoritative_generation_context(
            db,
            application_id="application-context",
            template_id="template-context",
            document_type="cover_letter",
            expected_job_id="job-context",
        )

        assert context.application["status"] == "draft"
        assert context.vacancy["title"] == "Platform Engineer"
        assert context.profile["skills"] == "Python"
        assert context.application_guide["language"] == "German"
        assert context.analysis_revision == "match-context"
        assert len(context.analysis_fingerprint) == 64
        assert context.language == "German"
        assert context.generation_date == date.today().isoformat()
        assert context.template.id == "template-context"
        assert context.confirmations[0].requirement == "Production Python"
        assert context.confirmations[0].blocking is True
        evidence = context.validation_evidence()
        evidence_by_id = {
            item["id"]: item for item in evidence["evidenceCatalog"]
        }
        assert set(evidence_by_id) >= {
            "profile:skills",
            "profile:experience:experience-acme:employer",
            "profile:experience:experience-acme:title",
            "profile:experience:experience-acme:period",
            "confirmation:production-python",
            "vacancy:title",
            "vacancy:company",
            "generation:date",
        }
        assert evidence_by_id["vacancy:title"]["text"] == "Platform Engineer"
        assert evidence_by_id["generation:date"] == {
            "id": "generation:date",
            "type": "generation",
            "text": date.today().isoformat(),
        }
        assistant_inputs = assistant_inputs_from_generation_context(context)
        assert assistant_inputs.job is not None
        assert assistant_inputs.job.ai_match is None
        assert assistant_inputs.application is not None
        assert assistant_inputs.application.status == ""
        assert assistant_inputs.confirmations == ()
        experience_claims = [
            item
            for item in evidence["evidenceCatalog"]
            if item["id"].startswith("profile:experience:")
        ]
        assert {item["claimType"] for item in experience_claims} == {
            "employer",
            "title",
            "period",
            "technology",
            "achievement",
        }
        assert "profile:experience" not in evidence_by_id


def test_resume_recruiter_stage_loads_application_confirmation_evidence() -> None:
    master_resume = MasterResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "master-context",
            "language": "English",
            "basics": {"fullName": "Alex"},
            "experiences": [],
            "skills": [],
            "education": [],
            "projects": [],
            "certifications": [],
            "languages": [],
            "additionalSections": [],
            "evidence": [],
            "sectionOrder": [],
        }
    )
    with generation_context_session() as db:
        enriched = resume_tailoring_master_resume(
            db,
            master_resume=master_resume,
            application_id="application-context",
            target_job_id="job-context",
        )

    evidence = {
        item.id: item.text for item in enriched.evidence
    }
    assert "confirmation:production-python" in evidence
    assert "Built two production Python services." in (
        evidence["confirmation:production-python"]
    )


def test_cover_letter_context_questions_are_always_authoritative() -> None:
    question_by_id = {
        question.question_id: question
        for question in clarification_questions(
            {
                "clarificationQuestions": [
                    {
                        "id": "cover-letter-company-contact",
                        "requirement": "Untrusted replacement",
                        "question": "Untrusted replacement?",
                        "blocking": True,
                    }
                ]
            }
        )
    }

    assert question_by_id["cover-letter-recipient-name"].requirement == (
        "Named recruiter or intended hiring contact"
    )
    assert question_by_id["cover-letter-company-contact"].blocking is False
    assert question_by_id["cover-letter-company-contact"].requirement == (
        "Known employee at the hiring company"
    )
    assert "full name" in question_by_id["cover-letter-company-contact"].question.lower()
    assert question_by_id["cover-letter-additional-context"].blocking is False
    assert len(clarification_questions({})) == 3


def test_rejects_generation_when_required_confirmation_is_missing() -> None:
    with generation_context_session(include_confirmation=False) as db:
        with pytest.raises(
            GenerationContextError,
            match="Required candidate confirmations are incomplete",
        ):
            load_authoritative_generation_context(
                db,
                application_id="application-context",
                template_id="template-context",
                document_type="cover_letter",
            )


def test_rejects_generation_when_saved_confirmation_is_only_a_draft() -> None:
    with generation_context_session() as db:
        confirmation = db.get(
            CandidateConfirmationRecord,
            ("application-context", "production-python"),
        )
        assert confirmation is not None
        confirmation.example_text = "yes"
        db.commit()

        with pytest.raises(
            GenerationContextError,
            match="Required candidate confirmations are incomplete",
        ):
            load_authoritative_generation_context(
                db,
                application_id="application-context",
                template_id="template-context",
                document_type="cover_letter",
            )


def test_computes_stable_provenance_from_authoritative_context() -> None:
    with generation_context_session() as db:
        context = load_authoritative_generation_context(
            db,
            application_id="application-context",
            template_id="template-context",
            document_type="cover_letter",
        )

        first = context.provenance()
        second = context.provenance()

        assert first == second
        assert len(first.generation_fingerprint) == 64
        assert first.input_versions["fingerprintVersion"] == "generation-fingerprint-v4"
        assert first.input_versions["backend"] == "openclaw_codex"
        assert first.input_versions["analysisRevision"] == "match-context"
        assert first.input_versions["analysisFingerprint"] == context.analysis_fingerprint
        assert first.input_versions["sourceDocument"]["id"] == "template-context"
        assert len(first.input_versions["sourceDocument"]["contentSha256"]) == 64
        assert replace(context, generation_backend="openai_api").provenance().generation_fingerprint != (
            first.generation_fingerprint
        )


def test_rejects_generation_when_stored_profile_changes() -> None:
    with generation_context_session() as db:
        load_authoritative_generation_context(
            db,
            application_id="application-context",
            template_id="template-context",
            document_type="cover_letter",
        )
        profile = db.get(ProfileRecord, "default")
        assert profile is not None
        profile.data = {**profile.data, "skills": "Python, PostgreSQL"}
        db.commit()

        with pytest.raises(GenerationContextError, match="^analysis_stale$") as stale:
            load_authoritative_generation_context(
                db,
                application_id="application-context",
                template_id="template-context",
                document_type="cover_letter",
            )

        assert stale.value.status_code == 409


def test_rejects_generation_when_stored_vacancy_changes() -> None:
    with generation_context_session() as db:
        vacancy = db.get(StoredJobRecord, ("local-owner", "job-context"))
        assert vacancy is not None
        vacancy.data = {**vacancy.data, "title": "Principal Platform Engineer"}
        db.commit()

        with pytest.raises(GenerationContextError, match="^analysis_stale$") as stale:
            load_authoritative_generation_context(
                db,
                application_id="application-context",
                template_id="template-context",
                document_type="cover_letter",
            )

        assert stale.value.status_code == 409


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model", "openai/different-model"),
        ("prompt_version", "ai-match-prompt-old"),
        ("matcher_version", "ai-match-v2"),
    ],
)
def test_rejects_generation_when_analysis_runtime_provenance_differs(
    field: str,
    value: str,
) -> None:
    with generation_context_session() as db:
        match_record = db.get(JobMatchRecord, "match-context")
        assert match_record is not None
        setattr(match_record, field, value)
        db.commit()

        with pytest.raises(GenerationContextError, match="^analysis_stale$") as stale:
            load_authoritative_generation_context(
                db,
                application_id="application-context",
                template_id="template-context",
                document_type="cover_letter",
            )

        assert stale.value.status_code == 409
