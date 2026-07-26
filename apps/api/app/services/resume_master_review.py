from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.resume import (
    MASTER_RESUME_REVIEW_SECTIONS,
    MasterResume,
    MasterResumeConfirmationResponse,
    MasterResumeReviewSection,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    ResumeSourceExtraction,
    ResumeSourceFileRecord,
)
from app.services.resume_master_import import (
    MasterResumeImportError,
    validate_master_resume_source_evidence,
)


PDF_CONTENT_TYPE = "application/pdf"
DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


class MasterResumeReviewError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def build_master_resume_review_sections(
    master_resume: MasterResume,
) -> list[MasterResumeReviewSection]:
    contact_count = sum(
        bool(value)
        for value in (
            master_resume.basics.full_name,
            master_resume.basics.headline,
            master_resume.basics.email,
            master_resume.basics.phone,
            master_resume.basics.location,
            master_resume.basics.work_authorization,
            master_resume.basics.linkedin,
            master_resume.basics.github,
            master_resume.basics.portfolio,
        )
    )
    counts = {
        "contacts": contact_count,
        "summary": int(master_resume.summary is not None),
        "skills": len(master_resume.skills),
        "experience": len(master_resume.experiences),
        "education": len(master_resume.education),
        "projects": len(master_resume.projects),
        "certifications": len(master_resume.certifications),
    }
    return [
        MasterResumeReviewSection(name=name, item_count=counts[name])
        for name in MASTER_RESUME_REVIEW_SECTIONS
    ]


def persist_master_resume_import_source(
    db: Session,
    *,
    file_name: str,
    content: bytes,
    source: ResumeSourceExtraction,
    draft_resume_id: str,
) -> ResumeSourceFileRecord:
    content_type = (
        PDF_CONTENT_TYPE
        if source.source_format == "pdf"
        else DOCX_CONTENT_TYPE
    )
    record = ResumeSourceFileRecord(
        id=uuid4().hex,
        resume_master_id=None,
        draft_resume_id=draft_resume_id,
        file_name=file_name,
        content_type=content_type,
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        content=content,
        extraction=source.model_dump(mode="json", by_alias=True),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def confirm_master_resume(
    db: Session,
    *,
    source_file_id: str,
    master_resume: MasterResume,
) -> MasterResumeConfirmationResponse:
    source_file = db.get(ResumeSourceFileRecord, source_file_id)
    if source_file is None:
        raise MasterResumeReviewError(
            "Master resume import source was not found",
            code="not_found",
        )
    if source_file.draft_resume_id is None:
        raise MasterResumeReviewError(
            "Import source is not a reviewable master resume draft",
            code="not_reviewable",
        )
    if master_resume.id != source_file.draft_resume_id:
        raise MasterResumeReviewError(
            "Reviewed master resume ID does not match the import draft",
            code="invalid_review",
        )

    try:
        extraction = ResumeSourceExtraction.model_validate(source_file.extraction)
        validate_master_resume_source_evidence(
            master_resume,
            source=extraction,
            expected_master_resume_id=source_file.draft_resume_id,
        )
    except (MasterResumeImportError, ValidationError) as exc:
        raise MasterResumeReviewError(
            "Reviewed master resume contains invalid source evidence",
            code="invalid_review",
        ) from exc

    canonical_data = master_resume.model_dump(mode="json", by_alias=True)
    content_sha256 = _canonical_resume_hash(canonical_data)
    if source_file.resume_master_id is not None:
        return _confirmed_response(
            db,
            source_file=source_file,
            master_resume=master_resume,
            expected_hash=content_sha256,
        )

    master_record = ResumeMasterRecord(
        id=master_resume.id,
        name=master_resume.basics.full_name,
        language=master_resume.language,
        current_version=1,
    )
    version_record = ResumeMasterVersionRecord(
        id=uuid4().hex,
        resume_master_id=master_record.id,
        version=1,
        schema_version=master_resume.schema_version,
        data=canonical_data,
        content_sha256=content_sha256,
        source_file_id=source_file.id,
    )
    source_file.resume_master_id = master_record.id
    db.add_all([master_record, version_record])
    db.commit()
    db.refresh(version_record)
    return MasterResumeConfirmationResponse(
        master_resume_id=master_record.id,
        version=version_record.version,
        source_file_id=source_file.id,
        master_resume=master_resume,
        created_at=version_record.created_at,
    )


def _confirmed_response(
    db: Session,
    *,
    source_file: ResumeSourceFileRecord,
    master_resume: MasterResume,
    expected_hash: str,
) -> MasterResumeConfirmationResponse:
    version_record = db.scalar(
        select(ResumeMasterVersionRecord).where(
            ResumeMasterVersionRecord.resume_master_id
            == source_file.resume_master_id,
            ResumeMasterVersionRecord.version == 1,
            ResumeMasterVersionRecord.source_file_id == source_file.id,
        )
    )
    if version_record is None:
        raise MasterResumeReviewError(
            "Confirmed master resume version is unavailable",
            code="conflict",
        )
    if version_record.content_sha256 != expected_hash:
        raise MasterResumeReviewError(
            "Import source was already confirmed with different review edits",
            code="conflict",
        )
    persisted_resume = MasterResume.model_validate(version_record.data)
    return MasterResumeConfirmationResponse(
        master_resume_id=version_record.resume_master_id,
        version=version_record.version,
        source_file_id=source_file.id,
        master_resume=persisted_resume,
        created_at=version_record.created_at,
    )


def _canonical_resume_hash(data: dict[str, object]) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


__all__ = [
    "MasterResumeReviewError",
    "build_master_resume_review_sections",
    "confirm_master_resume",
    "persist_master_resume_import_source",
]
