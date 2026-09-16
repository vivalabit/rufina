"""Optional resume imports: immutable sources, separate from candidate profile files."""

import asyncio
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, defer

from app.api.profile import parse_master_resume_with_selected_backend
from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.core.settings import Settings, get_settings
from app.models.profile import ProfileFileRecord
from app.models.resume import (
    MasterResumeImportResponse,
    ResumeSourceExtraction,
    ResumeSourceFileRecord,
)
from app.services.ai_privacy import record_ai_activity
from app.services.profile_files import ProfileFileValidationError, validate_profile_file_upload
from app.services.profile_migration import ensure_candidate_profile
from app.services.profile_versions import get_profile_record
from app.services.resume_master_import import MasterResumeImportError
from app.services.resume_master_review import (
    build_master_resume_review_sections,
    persist_master_resume_import_source,
)
from app.services.resume_source_extraction import (
    MAX_SOURCE_BYTES,
    ResumeSourceExtractionError,
    extract_resume_source,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])


class ImportSource(BaseModel):
    id: str
    file_name: str = Field(alias="fileName")
    size_bytes: int = Field(alias="sizeBytes")
    created_at: datetime = Field(alias="createdAt")
    download_url: str = Field(alias="downloadUrl")
    status: Literal["pending", "imported", "stored"]
    profile_version: int | None = Field(default=None, alias="profileVersion")
    can_review: bool = Field(default=False, alias="canReview")
    model_config = ConfigDict(populate_by_name=True)


def source_payload(
    record: ResumeSourceFileRecord, *, imported: bool = False, revision: int | None = None
) -> ImportSource:
    reviewable = bool(record.draft_resume_id and record.extraction.get("fragments"))
    return ImportSource(
        id=record.id,
        file_name=record.file_name,
        size_bytes=record.size_bytes,
        created_at=record.created_at,
        download_url=f"/profile/sources/{record.id}",
        status="imported" if imported else "pending" if reviewable else "stored",
        profile_version=revision,
        can_review=not imported and reviewable,
    )


@router.get("", response_model=list[ImportSource])
def import_history(db: Session = Depends(get_db)) -> list[ImportSource]:
    profile = get_profile_record(db)
    data = profile.data if profile else {}
    confirmed = {
        item.get("source_file_id"): item.get("profile_revision") for item in data.get("sources", [])
    }
    for source_id in data.get("import_source_ids", []):
        confirmed.setdefault(source_id, None)
    sources = db.scalars(
        select(ResumeSourceFileRecord)
        .options(defer(ResumeSourceFileRecord.content))
        .order_by(ResumeSourceFileRecord.created_at.desc())
    ).all()
    result = [
        source_payload(
            source,
            imported=source.id in confirmed or bool(source.resume_master_id),
            revision=confirmed.get(source.id),
        )
        for source in sources
    ]
    # Old attachments remain downloadable even if they were never imported.
    hashes = {source.content_sha256 for source in sources}
    for file in db.scalars(
        select(ProfileFileRecord).where(ProfileFileRecord.kind == "primary_resume")
    ):
        if file.content_sha256 not in hashes:
            result.append(
                ImportSource(
                    id=f"file:{file.id}",
                    file_name=file.file_name,
                    size_bytes=file.size_bytes,
                    created_at=file.created_at,
                    download_url=f"/profile/files/{file.id}",
                    status="stored",
                )
            )
    return sorted(result, key=lambda item: item.created_at, reverse=True)


@router.post("", response_model=ImportSource, status_code=201)
async def upload_import_source(
    request: Request,
    file_name: str = Query(min_length=1, max_length=500),
    db: Session = Depends(get_db),
) -> ImportSource:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_SOURCE_BYTES:
            raise HTTPException(status_code=413, detail="Resume exceeds the import size limit")
        content.extend(chunk)
    try:
        safe_name, content_type = validate_profile_file_upload(
            kind="primary_resume",
            file_name=file_name,
            content_type=request.headers.get("content-type", ""),
            content=bytes(content),
        )
    except ProfileFileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        source = await asyncio.to_thread(
            extract_resume_source,
            file_name=safe_name,
            content_type=content_type,
            content=bytes(content),
        )
    except ResumeSourceExtractionError:
        # Keep the original available in history even if text extraction fails.
        source = ResumeSourceExtraction(
            sourceFormat="pdf" if safe_name.lower().endswith(".pdf") else "docx",
            layout="one_column",
            pageCount=None,
            usedOcr=False,
            fragments=[],
        )
    record = persist_master_resume_import_source(
        db, file_name=safe_name, content=bytes(content), source=source, draft_resume_id=uuid4().hex
    )
    return source_payload(record)


@router.post("/{source_id}/preview", response_model=MasterResumeImportResponse)
def preview_import(
    source_id: str,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> MasterResumeImportResponse:
    record = db.get(ResumeSourceFileRecord, source_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Import source not found")
    if not record.draft_resume_id:
        raise HTTPException(
            status_code=409, detail="This historical source is available for download only"
        )
    if not settings.openclaw_resume_import_enabled:
        raise HTTPException(status_code=503, detail="AI resume analysis is disabled")
    profile = ensure_candidate_profile(db)
    if any(item.get("source_file_id") == record.id for item in profile.data.get("sources", [])):
        raise HTTPException(status_code=409, detail="This import is already saved in your profile")
    revision = profile.revision
    db.commit()
    try:
        source = ResumeSourceExtraction.model_validate(record.extraction)
        if not source.fragments:
            raise HTTPException(
                status_code=422,
                detail="Could not extract text. Download the source or choose another file.",
            )
        outcome = parse_master_resume_with_selected_backend(
            source, record.draft_resume_id, settings
        )
    except MasterResumeImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Resume import is temporarily unavailable. Your source file is saved in import history.",
        ) from exc
    return MasterResumeImportResponse(
        profile_revision=revision,
        source_file_id=record.id,
        master_resume=outcome.master_resume,
        source=source,
        review_sections=build_master_resume_review_sections(outcome.master_resume),
        model=outcome.model,
        backend=outcome.backend,
    )
