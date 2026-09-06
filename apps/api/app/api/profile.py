import asyncio
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.core.settings import Settings, get_settings
from app.models.profile import (
    ImportedEducationEntry,
    ImportedExperienceEntry,
    ProfileFileImportRequest,
    ProfileFileKind,
    ProfileFileMetadataUpdateRequest,
    ProfileFilePayload,
    ProfileFileRecord,
    ProfilePayload,
    ProfileRecord,
    ResumeEducationImportResponse,
    ResumeExperienceImportResponse,
    ResumeSkillsImportResponse,
)
from app.models.resume import (
    CurrentMasterResumeResponse,
    MasterResumeConfirmationRequest,
    MasterResumeConfirmationResponse,
    MasterResumeImportResponse,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    ResumeSourceExtraction,
)
from app.services.ai_privacy import record_ai_activity
from app.services.profile_files import (
    ProfileFileAlreadyExistsError,
    ProfileFileValidationError,
    best_effort_extracted_text,
    extract_profile_resume_source,
    get_profile_file,
    list_profile_files,
    normalize_content_type,
    profile_file_content_disposition,
    profile_file_payload,
    profile_file_size_limit,
    store_profile_file,
    update_profile_file_metadata,
    validate_profile_file_upload,
)
from app.services.profile_versions import (
    StaleProfileRevisionError,
    create_profile_record,
    get_profile_record,
    is_suspicious_profile_replacement,
    profile_etag,
    update_profile_data,
)
from app.services.resume_import import ResumeImportError, create_resume_import_ai_facade
from app.services.resume_master_import import (
    MasterResumeImportError,
    MasterResumeImportOutcome,
    create_master_resume_import_ai_facade,
)
from app.services.resume_master_review import (
    MasterResumeReviewError,
    build_master_resume_review_sections,
    confirm_master_resume,
    persist_master_resume_import_source,
)
from app.services.resume_source_extraction import ResumeSourceExtractionError

router = APIRouter(dependencies=[Depends(bind_request_identity)])

default_profile = ProfilePayload()

def parse_resume_experience_with_selected_backend(
    text: str,
    settings: Settings,
) -> list[ImportedExperienceEntry]:
    return create_resume_import_ai_facade(settings).parse_experience(text)


def parse_resume_education_with_selected_backend(
    text: str,
    settings: Settings,
) -> list[ImportedEducationEntry]:
    return create_resume_import_ai_facade(settings).parse_education(text)


def parse_resume_skills_with_selected_backend(
    text: str,
    settings: Settings,
) -> list[str]:
    return create_resume_import_ai_facade(settings).parse_skills(text)


def parse_master_resume_with_selected_backend(
    source: ResumeSourceExtraction,
    master_resume_id: str,
    settings: Settings,
) -> MasterResumeImportOutcome:
    return create_master_resume_import_ai_facade(settings).import_source(
        source=source,
        master_resume_id=master_resume_id,
    )


def normalize_profile_record(profile: ProfileRecord) -> ProfilePayload:
    return ProfilePayload.model_validate(profile.data)


def get_or_create_profile(db: Session) -> ProfileRecord:
    profile = get_profile_record(db)
    if profile:
        return profile

    profile = create_profile_record(default_profile.model_dump())
    db.add(profile)
    try:
        db.commit()
        db.refresh(profile)
        return profile
    except IntegrityError:
        db.rollback()
        concurrent_profile = get_profile_record(db)
        if concurrent_profile is None:
            raise
        return concurrent_profile


def require_matching_profile_revision(if_match: str | None, revision: int) -> None:
    if if_match is None:
        return
    tags = [tag.strip() for tag in if_match.split(",") if tag.strip()]
    if not tags:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="If-Match must contain a profile revision",
        )
    if "*" in tags:
        return

    revisions: set[int] = set()
    for tag in tags:
        if tag.startswith("W/"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="If-Match requires a strong profile ETag",
            )
        normalized = tag[1:-1] if tag.startswith('"') and tag.endswith('"') else tag
        if not normalized.isdigit() or int(normalized) < 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="If-Match contains an invalid profile revision",
            )
        revisions.add(int(normalized))
    if revision not in revisions:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Profile has changed; reload it before saving",
            headers={"ETag": profile_etag(revision)},
        )


def private_file_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, no-store",
        "Cross-Origin-Resource-Policy": "same-site",
        "Vary": "X-Rufina-Owner-Id, X-Tasko-Owner-Id",
        "X-Content-Type-Options": "nosniff",
    }


def require_profile_file(db: Session, file_id: str) -> ProfileFileRecord:
    record = get_profile_file(db, file_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile file not found",
        )
    return record


def require_import_profile_resume(
    db: Session,
    payload: ProfileFileImportRequest,
) -> ProfileFileRecord:
    record = require_profile_file(db, payload.profile_file_id)
    if record.kind != "primary_resume":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected profile file is not the primary resume",
        )
    return record


def extract_resume_import_text(
    db: Session,
    payload: ProfileFileImportRequest,
) -> str:
    record = require_import_profile_resume(db, payload)
    if record.extracted_text.strip():
        return record.extracted_text
    try:
        source = extract_profile_resume_source(record)
    except (ProfileFileValidationError, ResumeSourceExtractionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read text from the stored resume",
        ) from exc
    record.extracted_text = source.text[:200_000]
    try:
        db.commit()
        db.refresh(record)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Extracted resume text could not be saved",
        ) from exc
    return record.extracted_text


@router.get("", response_model=ProfilePayload)
def get_profile(
    response: Response,
    db: Session = Depends(get_db),
) -> ProfilePayload:
    try:
        profile = get_or_create_profile(db)
        payload = normalize_profile_record(profile)
        response.headers["ETag"] = profile_etag(profile.revision)
        return payload
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile database is unavailable",
        ) from exc


@router.put("", response_model=ProfilePayload)
def update_profile(
    payload: ProfilePayload,
    response: Response,
    allow_destructive: bool = False,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
    db: Session = Depends(get_db),
) -> ProfilePayload:
    try:
        profile = get_profile_record(db)
        if profile:
            require_matching_profile_revision(if_match, profile.revision)
            current_profile = ProfilePayload.model_validate(profile.data)
            if not allow_destructive and is_suspicious_profile_replacement(
                current_profile, payload
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Profile update would remove most existing data. "
                        "Reload the profile or explicitly allow a destructive replacement."
                    ),
                    headers={"ETag": profile_etag(profile.revision)},
                )
            if current_profile != payload:
                update_profile_data(
                    db,
                    profile,
                    data=payload.model_dump(),
                    reason="api_update",
                )
        else:
            if if_match is not None:
                raise HTTPException(
                    status_code=status.HTTP_412_PRECONDITION_FAILED,
                    detail="Profile does not exist for the requested If-Match condition",
                )
            profile = create_profile_record(payload.model_dump())
            db.add(profile)

        db.commit()
        db.refresh(profile)
        response.headers["ETag"] = profile_etag(profile.revision)
        return ProfilePayload.model_validate(profile.data)
    except HTTPException:
        db.rollback()
        raise
    except StaleProfileRevisionError as exc:
        db.rollback()
        current_profile = get_profile_record(db)
        headers = (
            {"ETag": profile_etag(current_profile.revision)}
            if current_profile is not None
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail="Profile has changed; reload it before saving",
            headers=headers,
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        current_profile = get_profile_record(db)
        if current_profile is not None:
            raise HTTPException(
                status_code=status.HTTP_412_PRECONDITION_FAILED,
                detail="Profile was created concurrently; reload it before saving",
                headers={"ETag": profile_etag(current_profile.revision)},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile database is unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile database is unavailable",
        ) from exc


@router.post(
    "/files",
    response_model=ProfileFilePayload,
    status_code=status.HTTP_201_CREATED,
)
async def upload_profile_file(
    request: Request,
    response: Response,
    kind: ProfileFileKind = Query(),
    file_name: str = Query(min_length=1, max_length=500),
    title: str = Query(default="", max_length=240),
    category: str = Query(default="", max_length=80),
    language: str = Query(default="", max_length=40),
    issuer: str = Query(default="", max_length=240),
    notes: str = Query(default="", max_length=2_000),
    replace_existing: bool = Query(default=True, alias="replaceExisting"),
    db: Session = Depends(get_db),
) -> ProfileFilePayload:
    limit = profile_file_size_limit(kind)
    declared_length = request.headers.get("content-length")
    if declared_length is not None:
        try:
            parsed_length = int(declared_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must be an integer",
            ) from exc
        if parsed_length < 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Content-Length must not be negative",
            )
        if parsed_length > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Profile file exceeds the {limit}-byte limit",
            )

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"Profile file exceeds the {limit}-byte limit",
            )
        body.extend(chunk)
    content = bytes(body)
    content_type = normalize_content_type(request.headers.get("content-type", ""))
    try:
        safe_name, safe_content_type = validate_profile_file_upload(
            kind=kind,
            file_name=file_name,
            content_type=content_type,
            content=content,
        )
        extracted_text = await asyncio.to_thread(
            best_effort_extracted_text,
            file_name=safe_name,
            content_type=safe_content_type,
            content=content,
        )
        record = store_profile_file(
            db,
            kind=kind,
            file_name=safe_name,
            content_type=safe_content_type,
            content=content,
            extracted_text=extracted_text,
            title=title,
            category=category,
            language=language,
            issuer=issuer,
            notes=notes,
            replace_singleton=replace_existing,
        )
        db.commit()
        db.refresh(record)
    except ProfileFileAlreadyExistsError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED,
            detail=str(exc),
        ) from exc
    except ProfileFileValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Profile file changed concurrently; retry the upload",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile file storage is temporarily unavailable",
        ) from exc

    response.headers.update(private_file_headers())
    response.headers["Location"] = f"/profile/files/{record.id}"
    return profile_file_payload(record)


@router.get("/files", response_model=list[ProfileFilePayload])
def get_profile_files(
    response: Response,
    kind: ProfileFileKind | None = Query(default=None),
    db: Session = Depends(get_db),
) -> list[ProfileFilePayload]:
    try:
        records = list_profile_files(db, kind=kind)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile file storage is temporarily unavailable",
        ) from exc
    response.headers.update(private_file_headers())
    return [
        profile_file_payload(record, extracted_text_available=has_extracted_text)
        for record, has_extracted_text in records
    ]


@router.get("/files/{file_id}")
def download_profile_file(
    file_id: str,
    db: Session = Depends(get_db),
) -> Response:
    try:
        record = require_profile_file(db, file_id)
        return Response(
            content=record.content,
            media_type=record.content_type,
            headers={
                **private_file_headers(),
                "Content-Disposition": profile_file_content_disposition(
                    record.file_name,
                    inline=record.kind == "avatar",
                ),
            },
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile file storage is temporarily unavailable",
        ) from exc


@router.patch("/files/{file_id}", response_model=ProfileFilePayload)
def patch_profile_file_metadata(
    file_id: str,
    payload: ProfileFileMetadataUpdateRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> ProfileFilePayload:
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one metadata field",
        )
    try:
        record = require_profile_file(db, file_id)
        update_profile_file_metadata(record, changes)
        db.commit()
        db.refresh(record)
    except ProfileFileValidationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile file storage is temporarily unavailable",
        ) from exc
    response.headers.update(private_file_headers())
    return profile_file_payload(record)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile_file(
    file_id: str,
    db: Session = Depends(get_db),
) -> None:
    try:
        record = require_profile_file(db, file_id)
        db.delete(record)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile file storage is temporarily unavailable",
        ) from exc


@router.get(
    "/master-resume",
    response_model=CurrentMasterResumeResponse,
)
def get_current_master_resume(
    db: Session = Depends(get_db),
) -> CurrentMasterResumeResponse:
    try:
        master = db.scalar(
            select(ResumeMasterRecord)
            .order_by(
                ResumeMasterRecord.updated_at.desc(),
                ResumeMasterRecord.created_at.desc(),
            )
            .limit(1)
        )
        if master is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Confirmed Master Resume not found",
            )
        version = db.scalar(
            select(ResumeMasterVersionRecord).where(
                ResumeMasterVersionRecord.resume_master_id == master.id,
                ResumeMasterVersionRecord.version == master.current_version,
            )
        )
        if version is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Current Master Resume version is unavailable",
            )
        return CurrentMasterResumeResponse(
            master_resume_id=master.id,
            version=version.version,
            master_resume=version.data,
            created_at=version.created_at,
            updated_at=master.updated_at,
        )
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Master Resume is temporarily unavailable",
        ) from exc


@router.post("/import-experience-from-resume", response_model=ResumeExperienceImportResponse)
def import_experience_from_resume(
    payload: ProfileFileImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ResumeExperienceImportResponse:
    text = extract_resume_import_text(db, payload)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read text from the attached resume",
        )

    if not settings.openclaw_resume_import_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is disabled.",
        )

    try:
        experience = parse_resume_experience_with_selected_backend(text, settings)
    except ResumeImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is temporarily unavailable. Please try again.",
        ) from exc

    if not experience:
        return ResumeExperienceImportResponse(
            experience=[],
            message="No structured experience entries were found in the attached resume",
        )

    return ResumeExperienceImportResponse(
        experience=experience,
        message=f"Imported {len(experience)} experience entr{'y' if len(experience) == 1 else 'ies'} from CV",
    )


@router.post(
    "/import-master-resume",
    response_model=MasterResumeImportResponse,
)
def import_master_resume(
    payload: ProfileFileImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> MasterResumeImportResponse:
    if not settings.openclaw_resume_import_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is disabled.",
        )

    profile_file = require_import_profile_resume(db, payload)
    try:
        file_name = profile_file.file_name
        content = profile_file.content
        source = extract_profile_resume_source(profile_file)
    except (ResumeSourceExtractionError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract source fragments from the attached resume",
        ) from exc
    if not source.fragments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract source fragments from the attached resume",
        )

    try:
        outcome = parse_master_resume_with_selected_backend(
            source,
            uuid4().hex,
            settings,
        )
    except MasterResumeImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI master resume import is temporarily unavailable. Please try again.",
        ) from exc

    try:
        source_file = persist_master_resume_import_source(
            db,
            file_name=file_name,
            content=content,
            source=source,
            draft_resume_id=outcome.master_resume.id,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Master resume import storage is temporarily unavailable",
        ) from exc

    return MasterResumeImportResponse(
        source_file_id=source_file.id,
        master_resume=outcome.master_resume,
        source=source,
        review_sections=build_master_resume_review_sections(outcome.master_resume),
        model=outcome.model,
        backend=outcome.backend,
    )


@router.post(
    "/import-master-resume/confirm",
    response_model=MasterResumeConfirmationResponse,
)
def confirm_imported_master_resume(
    payload: MasterResumeConfirmationRequest,
    db: Session = Depends(get_db),
) -> MasterResumeConfirmationResponse:
    try:
        return confirm_master_resume(
            db,
            source_file_id=payload.source_file_id,
            master_resume=payload.master_resume,
        )
    except MasterResumeReviewError as exc:
        db.rollback()
        status_code = {
            "not_found": status.HTTP_404_NOT_FOUND,
            "invalid_review": status.HTTP_422_UNPROCESSABLE_ENTITY,
            "not_reviewable": status.HTTP_409_CONFLICT,
            "conflict": status.HTTP_409_CONFLICT,
        }.get(exc.code, status.HTTP_409_CONFLICT)
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Master resume confirmation storage is temporarily unavailable",
        ) from exc


@router.post("/import-education-from-resume", response_model=ResumeEducationImportResponse)
def import_education_from_resume(
    payload: ProfileFileImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ResumeEducationImportResponse:
    text = extract_resume_import_text(db, payload)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read text from the attached resume",
        )

    if not settings.openclaw_resume_import_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is disabled.",
        )

    try:
        education = parse_resume_education_with_selected_backend(text, settings)
    except ResumeImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is temporarily unavailable. Please try again.",
        ) from exc

    if not education:
        return ResumeEducationImportResponse(
            education=[],
            message="No structured education entries were found in the attached resume",
        )

    return ResumeEducationImportResponse(
        education=education,
        message=f"Imported {len(education)} education entr{'y' if len(education) == 1 else 'ies'} from CV",
    )


@router.post("/import-skills-from-resume", response_model=ResumeSkillsImportResponse)
def import_skills_from_resume(
    payload: ProfileFileImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ResumeSkillsImportResponse:
    text = extract_resume_import_text(db, payload)
    if not text.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not read text from the attached resume",
        )

    if not settings.openclaw_resume_import_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is disabled.",
        )

    try:
        skills = parse_resume_skills_with_selected_backend(text, settings)
    except ResumeImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is temporarily unavailable. Please try again.",
        ) from exc

    if not skills:
        return ResumeSkillsImportResponse(
            skills=[],
            message="No skills were found in the attached resume",
        )

    return ResumeSkillsImportResponse(
        skills=skills,
        message=f"Imported {len(skills)} skill{'s' if len(skills) != 1 else ''} from CV",
    )
