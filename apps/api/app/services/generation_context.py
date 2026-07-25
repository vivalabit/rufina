import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from math import isfinite
from typing import Any

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.core.settings import get_settings
from app.models.applications import CandidateConfirmationRecord, StoredApplicationRecord
from app.models.documents import DocumentTemplateRecord
from app.services.resume_template_registry import (
    is_bundled_resume_template_id,
    materialize_bundled_resume_template,
)
from app.models.jobs import JobMatchRecord, StoredJobRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.ai_match import (
    MATCHER_VERSION,
    MATCH_PROMPT_VERSION,
    build_job_snapshot,
    build_job_snapshot_hash,
    detect_job_language,
)
from app.services.candidate_snapshot import get_candidate_match_snapshot
from app.services.experience_evidence import build_atomic_experience_evidence
from app.services.job_match_store import (
    authoritative_match_record,
    authoritative_match_to_ai_match,
    has_job_match_record,
    latest_job_match_record,
    match_record_to_ai_match,
)

GENERATION_FINGERPRINT_VERSION = "generation-fingerprint-v4"
PROFILE_EVIDENCE_FIELDS = (
    "name",
    "current_role",
    "desired_role",
    "location",
    "headline",
    "skills",
    "experience",
    "education",
)
DIRECT_PROFILE_EVIDENCE_FIELDS = tuple(
    field for field in PROFILE_EVIDENCE_FIELDS if field != "experience"
)
VACANCY_EVIDENCE_FIELDS = (
    "title",
    "company",
    "overview",
    "responsibilities",
    "requirements",
    "skills",
)


class GenerationContextError(ValueError):
    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ClarificationQuestion:
    question_id: str
    requirement: str
    question: str
    blocking: bool


SYSTEM_DOCUMENT_QUESTIONS = (
    ClarificationQuestion(
        question_id="cover-letter-recipient-name",
        requirement="Named recruiter or intended hiring contact",
        question="Is a recruiter or intended hiring contact named for this application? If yes, provide their full name.",
        blocking=False,
    ),
    ClarificationQuestion(
        question_id="cover-letter-company-contact",
        requirement="Known employee at the hiring company",
        question="Do you know or have you spoken with an employee at this company? If yes, provide their full name.",
        blocking=False,
    ),
    ClarificationQuestion(
        question_id="cover-letter-additional-context",
        requirement="Optional cover-letter context",
        question="Is there anything else the letter should emphasize or avoid?",
        blocking=False,
    ),
)


@dataclass(frozen=True)
class AuthoritativeConfirmation:
    question_id: str
    requirement: str
    question: str
    response: str
    example_text: str
    blocking: bool


@dataclass(frozen=True)
class AuthoritativeGenerationProvenance:
    generation_fingerprint: str
    generation_backend: str
    input_versions: dict[str, Any]


@dataclass(frozen=True)
class AuthoritativeApplicationGenerationContext:
    application_id: str
    job_id: str
    application: dict[str, Any]
    vacancy: dict[str, Any]
    profile: dict[str, Any]
    application_guide: dict[str, Any]
    analysis_revision: str
    analysis_fingerprint: str
    confirmations: tuple[AuthoritativeConfirmation, ...]
    language: str
    generation_date: str
    generation_backend: str

    def with_template(
        self,
        template: DocumentTemplateRecord,
    ) -> "AuthoritativeGenerationContext":
        return AuthoritativeGenerationContext(
            application_id=self.application_id,
            job_id=self.job_id,
            application=self.application,
            vacancy=self.vacancy,
            profile=self.profile,
            application_guide=self.application_guide,
            analysis_revision=self.analysis_revision,
            analysis_fingerprint=self.analysis_fingerprint,
            confirmations=self.confirmations,
            language=self.language,
            generation_date=self.generation_date,
            generation_backend=self.generation_backend,
            template=template,
        )

    def provenance_for_source_document(
        self,
        source_document: dict[str, Any],
    ) -> AuthoritativeGenerationProvenance:
        confirmations = [asdict(confirmation) for confirmation in self.confirmations]
        fingerprint_inputs = {
            "fingerprintVersion": GENERATION_FINGERPRINT_VERSION,
            "backend": self.generation_backend,
            "vacancy": self.vacancy,
            "profile": self.profile,
            "applicationGuide": self.application_guide,
            "analysisRevision": self.analysis_revision,
            "analysisFingerprint": self.analysis_fingerprint,
            "sourceDocument": source_document,
            "language": self.language,
            "confirmations": confirmations,
        }
        input_versions: dict[str, Any] = {
            "fingerprintVersion": GENERATION_FINGERPRINT_VERSION,
            "backend": self.generation_backend,
            "vacancy": canonical_hash(self.vacancy),
            "profile": canonical_hash(self.profile),
            "applicationGuide": canonical_hash(self.application_guide),
            "analysisRevision": self.analysis_revision,
            "analysisFingerprint": self.analysis_fingerprint,
            "sourceDocument": {
                **canonical_value(source_document),
                "fingerprint": canonical_hash(source_document),
            },
            "language": canonical_hash(self.language),
            "confirmations": canonical_hash(confirmations),
        }
        return AuthoritativeGenerationProvenance(
            generation_fingerprint=canonical_hash(fingerprint_inputs),
            generation_backend=self.generation_backend,
            input_versions=input_versions,
        )


@dataclass(frozen=True)
class AuthoritativeGenerationContext(AuthoritativeApplicationGenerationContext):
    template: DocumentTemplateRecord

    def input_snapshot(self, *, prompt: str) -> dict[str, Any]:
        return canonical_value(
            {
                "applicationId": self.application_id,
                "jobId": self.job_id,
                "documentType": self.template.type,
                "application": self.application,
                "vacancy": self.vacancy,
                "profile": self.profile,
                "applicationGuide": self.application_guide,
                "analysisRevision": self.analysis_revision,
                "analysisFingerprint": self.analysis_fingerprint,
                "confirmations": [asdict(confirmation) for confirmation in self.confirmations],
                "language": self.language,
                "generationDate": self.generation_date,
                "generationBackend": self.generation_backend,
                "sourceDocument": {
                    "id": self.template.id,
                    "name": self.template.name,
                    "fileName": self.template.file_name,
                    "contentType": self.template.content_type,
                    "updatedAt": self.template.updated_at,
                    "contentSha256": self.template.content_sha256,
                },
                "prompt": prompt,
            }
        )

    def provenance(self) -> AuthoritativeGenerationProvenance:
        source_document = {
            "id": self.template.id,
            "name": self.template.name,
            "fileName": self.template.file_name,
            "contentType": self.template.content_type,
            "updatedAt": self.template.updated_at,
            "contentSha256": self.template.content_sha256,
        }
        return self.provenance_for_source_document(source_document)

    def validation_evidence(self) -> dict[str, Any]:
        evidence_matrix = self.application_guide.get("evidenceMatrix")
        verified_guide_evidence = (
            [
                {
                    "requirement": str(item.get("requirement") or "").strip(),
                    "evidence": str(item.get("evidence") or "").strip(),
                }
                for item in evidence_matrix
                if isinstance(item, dict) and item.get("status") in {"verified", "transferable"}
            ]
            if isinstance(evidence_matrix, list)
            else []
        )
        profile_evidence = [
            {
                "id": f"profile:{field}",
                "type": "profile",
                "text": str(self.profile.get(field) or "").strip(),
            }
            for field in DIRECT_PROFILE_EVIDENCE_FIELDS
            if str(self.profile.get(field) or "").strip()
        ]
        experience_evidence = build_atomic_experience_evidence(
            self.profile.get("experience")
        )
        confirmation_evidence = [
            {
                "id": f"confirmation:{confirmation.question_id}",
                "type": "confirmation",
                "text": "\n".join(
                    value
                    for value in (
                        confirmation.requirement,
                        confirmation.question,
                        confirmation.example_text,
                    )
                    if value.strip()
                ),
            }
            for confirmation in self.confirmations
            if confirmation.response != "no"
        ]
        vacancy_evidence = [
            {
                "id": f"vacancy:{field}",
                "type": "vacancy",
                "text": evidence_text(self.vacancy.get(field)),
            }
            for field in VACANCY_EVIDENCE_FIELDS
            if evidence_text(self.vacancy.get(field))
        ]
        generation_evidence = {
            "id": "generation:date",
            "type": "generation",
            "text": self.generation_date,
        }
        return {
            "profile": {
                field: self.profile.get(field, "") for field in PROFILE_EVIDENCE_FIELDS
            },
            "confirmations": [
                {
                    "requirement": confirmation.requirement,
                    "response": confirmation.response,
                    "exampleText": confirmation.example_text,
                }
                for confirmation in self.confirmations
                if confirmation.response != "no"
            ],
            "verifiedGuideEvidence": verified_guide_evidence,
            "language": self.language,
            "evidenceCatalog": [
                *profile_evidence,
                *experience_evidence,
                *confirmation_evidence,
                *vacancy_evidence,
                generation_evidence,
            ],
        }


def evidence_text(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def load_authoritative_application_generation_context(
    db: Session,
    *,
    application_id: str,
    generation_backend: str | None = None,
) -> AuthoritativeApplicationGenerationContext:
    application_record = db.get(StoredApplicationRecord, application_id)
    if not application_record:
        raise GenerationContextError("Application not found", status_code=404)

    application = application_record.data if isinstance(application_record.data, dict) else {}
    application_job = application.get("job")
    job_id = (
        str(application_job.get("id") or "").strip() if isinstance(application_job, dict) else ""
    )
    if not job_id:
        raise GenerationContextError("Application does not reference a vacancy")
    job_record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
    if not job_record or not isinstance(job_record.data, dict):
        raise GenerationContextError("Stored application vacancy is unavailable")
    vacancy = dict(job_record.data)
    vacancy["id"] = job_id

    profile_record = db.get(ProfileRecord, "default")
    if not profile_record:
        raise GenerationContextError("Candidate profile is unavailable")
    try:
        profile = ProfilePayload.model_validate(profile_record.data).model_dump()
    except ValidationError as exc:
        raise GenerationContextError("Candidate profile is invalid") from exc

    match_record = current_authoritative_match_record(
        db,
        job_id=job_id,
        profile=ProfilePayload.model_validate(profile),
        vacancy=vacancy,
    )
    if not match_record:
        if has_job_match_record(db, job_id=job_id):
            raise GenerationContextError("analysis_stale")
        raise GenerationContextError("Stored ai-match-v3 is required")
    authoritative_analysis = authoritative_match_to_ai_match(match_record)
    application_guide = authoritative_analysis.get("applicationGuide")
    if not isinstance(application_guide, dict):
        raise GenerationContextError("Stored ai-match-v3 application guide is unavailable")
    questions = clarification_questions(application_guide)
    confirmation_records = {
        record.question_id: record
        for record in db.query(CandidateConfirmationRecord)
        .filter(CandidateConfirmationRecord.application_id == application_id)
        .all()
    }
    confirmations: list[AuthoritativeConfirmation] = []
    missing_required: list[str] = []
    for question in questions:
        record = confirmation_records.get(question.question_id)
        if record is None:
            if question.blocking:
                missing_required.append(question.question_id)
            continue
        if record.response not in {"yes", "no", "partial"}:
            raise GenerationContextError(
                f"Saved confirmation {question.question_id} has an invalid response"
            )
        if question.blocking and not meaningful_confirmation(
            response=record.response,
            example_text=record.example_text,
        ):
            missing_required.append(question.question_id)
            continue
        confirmations.append(
            AuthoritativeConfirmation(
                question_id=question.question_id,
                requirement=question.requirement,
                question=question.question,
                response=record.response,
                example_text=record.example_text.strip(),
                blocking=question.blocking,
            )
        )
    if missing_required:
        raise GenerationContextError(
            "Required candidate confirmations are incomplete: "
            + ", ".join(sorted(missing_required))
        )

    language = str(application_guide.get("language") or "").strip()
    if language not in {"English", "German"}:
        language = detect_job_language(vacancy)

    selected_generation_backend = generation_backend or get_settings().ai_backend_mode
    return AuthoritativeApplicationGenerationContext(
        application_id=application_id,
        job_id=job_id,
        application=dict(application),
        vacancy=vacancy,
        profile=profile,
        application_guide=application_guide,
        analysis_revision=str(authoritative_analysis["revision"]),
        analysis_fingerprint=str(authoritative_analysis["fingerprint"]),
        confirmations=tuple(confirmations),
        language=language,
        generation_date=date.today().isoformat(),
        generation_backend=selected_generation_backend,
    )


def load_authoritative_generation_context(
    db: Session,
    *,
    application_id: str,
    template_id: str,
    document_type: str,
    expected_job_id: str | None = None,
    template_override: DocumentTemplateRecord | None = None,
    generation_backend: str | None = None,
) -> AuthoritativeGenerationContext:
    application_context = load_authoritative_application_generation_context(
        db,
        application_id=application_id,
        generation_backend=generation_backend,
    )
    if expected_job_id and expected_job_id != application_context.job_id:
        raise GenerationContextError(
            "Generation job does not match the application vacancy",
            status_code=422,
        )
    if template_override is not None:
        template = template_override
    elif document_type == "tailored_resume":
        if not is_bundled_resume_template_id(template_id):
            raise GenerationContextError(
                "Tailored resumes require a bundled resume template",
                status_code=422,
            )
        template = materialize_bundled_resume_template(db, template_id)
    elif is_bundled_resume_template_id(template_id):
        raise GenerationContextError(
            "Bundled resume templates can only render tailored resumes",
            status_code=422,
        )
    else:
        template = db.get(DocumentTemplateRecord, template_id)
    if not template:
        raise GenerationContextError("Document template not found", status_code=404)
    if template.type != document_type:
        raise GenerationContextError(
            "Document template type does not match document type",
            status_code=422,
        )
    return application_context.with_template(template)


def load_stored_application_guide(db: Session, *, job_id: str) -> dict[str, Any]:
    match_record = latest_job_match_record(db, job_id=job_id)
    if not match_record:
        raise GenerationContextError("Stored ai-match-v3 is required")
    application_guide = match_record_to_ai_match(match_record).get("applicationGuide")
    if not isinstance(application_guide, dict):
        raise GenerationContextError("Stored ai-match-v3 application guide is unavailable")
    return application_guide


def current_authoritative_match_record(
    db: Session,
    *,
    job_id: str,
    profile: ProfilePayload,
    vacancy: dict[str, Any],
) -> JobMatchRecord | None:
    settings = get_settings()
    candidate_snapshot = get_candidate_match_snapshot(db, profile=profile, settings=settings)
    return authoritative_match_record(
        db,
        owner_id=get_bound_owner_id(),
        job_id=job_id,
        profile_hash=candidate_snapshot.profile_hash,
        vacancy_hash=build_job_snapshot_hash(build_job_snapshot(vacancy)),
        model=(
            settings.openai_api_model
            if settings.ai_backend_mode == "openai_api"
            else settings.openclaw_ai_match_model
        ),
        backend=settings.ai_backend_mode,
        prompt_version=MATCH_PROMPT_VERSION,
        matcher_version=MATCHER_VERSION,
    )


def clarification_questions(
    application_guide: dict[str, Any],
) -> tuple[ClarificationQuestion, ...]:
    raw_questions = application_guide.get("clarificationQuestions")
    if not isinstance(raw_questions, list):
        raw_questions = []
    questions: list[ClarificationQuestion] = []
    seen_ids: set[str] = set()
    system_question_ids = {
        question.question_id for question in SYSTEM_DOCUMENT_QUESTIONS
    }
    for raw_question in raw_questions:
        if not isinstance(raw_question, dict):
            continue
        question_id = str(raw_question.get("id") or "").strip()
        question_text = str(raw_question.get("question") or "").strip()
        requirement = str(raw_question.get("requirement") or question_text).strip()[:500]
        if not question_id or not requirement:
            continue
        if question_id in system_question_ids:
            continue
        if question_id in seen_ids:
            raise GenerationContextError(
                "Stored ai-match-v3 contains duplicate clarification question IDs"
            )
        seen_ids.add(question_id)
        questions.append(
            ClarificationQuestion(
                question_id=question_id,
                requirement=requirement,
                question=question_text,
                blocking=bool(raw_question.get("blocking")),
            )
        )
    questions.extend(SYSTEM_DOCUMENT_QUESTIONS)
    return tuple(questions)


def meaningful_confirmation(*, response: str, example_text: str) -> bool:
    if response == "no":
        return True
    normalized = " ".join(example_text.split())
    words = [
        word for word in normalized.split(" ") if any(character.isalnum() for character in word)
    ]
    return len(normalized) >= 10 and len(words) >= 2


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        canonical_value(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and not isfinite(value):
        return None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
