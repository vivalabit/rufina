from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import ProfilePayload, ProfileVersionRecord
from app.models.resume import (
    MASTER_RESUME_REVIEW_SECTIONS,
    MasterResume,
    MasterResumeConfirmationResponse,
    MasterResumeReviewSection,
    ResumeSourceExtraction,
    ResumeSourceFileRecord,
)
from app.services.candidate_profile import profile_resume
from app.services.profile_migration import ensure_candidate_profile, merge_master_into_profile
from app.services.profile_versions import StaleProfileRevisionError, update_profile_data
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
    expected_profile_revision: int,
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
    profile = ensure_candidate_profile(db)
    payload = ProfilePayload.model_validate(profile.data)
    source_key = f"import:{source_file.id}"
    previous = next((item for item in payload.sources if item.get("key") == source_key), None)
    if previous:
        if previous["content_sha256"] != content_sha256:
            raise MasterResumeReviewError("Import was already confirmed with different edits", code="conflict")
        version = db.scalar(select(ProfileVersionRecord).where(
            ProfileVersionRecord.owner_id == profile.owner_id,
            ProfileVersionRecord.profile_id == profile.id,
            ProfileVersionRecord.revision == previous["profile_revision"],
        ))
        return MasterResumeConfirmationResponse(
            master_resume_id=profile.id, version=version.revision, source_file_id=source_file.id,
            master_resume=profile_resume(ProfilePayload.model_validate(version.data), profile.id),
            created_at=version.created_at,
        )
    if profile.revision != expected_profile_revision:
        raise MasterResumeReviewError("Profile changed during review; reload and review the import again", code="conflict")
    merged = merge_master_into_profile(payload, master_resume, source_key=source_key,
                                      source_file_id=source_file.id, content_sha256=content_sha256)
    data = merged.model_dump(mode="json")
    data["sources"][-1]["profile_revision"] = profile.revision + 1
    data["sources"][-1]["source_content_sha256"] = source_file.content_sha256
    try:
        revision = update_profile_data(db, profile, data=data, reason="resume_import_confirmed")
        db.flush()
    except StaleProfileRevisionError as exc:
        raise MasterResumeReviewError("Profile changed during review", code="conflict") from exc
    version = db.scalar(select(ProfileVersionRecord).where(
        ProfileVersionRecord.owner_id == profile.owner_id,
        ProfileVersionRecord.profile_id == profile.id,
        ProfileVersionRecord.revision == revision,
    ))
    response = MasterResumeConfirmationResponse(
        master_resume_id=profile.id, version=revision, source_file_id=source_file.id,
        master_resume=profile_resume(ProfilePayload.model_validate(data), profile.id),
        created_at=version.created_at,
    )
    db.commit()
    return response


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
