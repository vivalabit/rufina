from binascii import Error as BinasciiError
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.core.settings import Settings, get_settings
from app.models.profile import (
    ImportedEducationEntry,
    ImportedExperienceEntry,
    ProfilePayload,
    ProfileRecord,
    ResumeEducationImportResponse,
    ResumeExperienceImportRequest,
    ResumeExperienceImportResponse,
    ResumeSkillsImportResponse,
)
from app.models.resume import (
    CurrentMasterResumeResponse,
    MasterResumeConfirmationRequest,
    MasterResumeConfirmationResponse,
    MasterResumeImportRequest,
    MasterResumeImportResponse,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    ResumeSourceExtraction,
)
from app.services.ai_privacy import record_ai_activity
from app.services.profile_versions import (
    StaleProfileRevisionError,
    create_profile_record,
    get_profile_record,
    is_suspicious_profile_replacement,
    profile_etag,
    update_profile_data,
)
from app.services.resume_import import (
    ResumeImportError,
    create_resume_import_ai_facade,
    decode_resume_data_url,
    extract_resume_text,
)
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
from app.services.resume_source_extraction import (
    ResumeSourceExtractionError,
    extract_resume_source,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])

default_profile = ProfilePayload()

legacy_default_profile = {
    "name": "Alex Johnson",
    "current_role": "Senior Product Designer",
    "desired_role": "Design Manager",
    "location": "San Francisco, CA, USA",
    "work_format": "Remote, open to hybrid",
    "headline": (
        "Product designer with 7+ years of experience crafting intuitive B2B and B2C "
        "digital experiences. Combines user empathy with data-driven design to ship "
        "impactful products."
    ),
    "linkedin": "linkedin.com/in/alexjohnson",
    "github": "github.com/alexjohnson",
    "portfolio": "alexjohnson.design",
    "personal_site": "alexjohnson.com",
}


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


def normalize_profile_record(profile: ProfileRecord, db: Session) -> ProfilePayload:
    normalized_data = dict(profile.data)

    for field, legacy_value in legacy_default_profile.items():
        if normalized_data.get(field) == legacy_value:
            normalized_data[field] = ""

    if normalized_data != profile.data:
        try:
            update_profile_data(
                db,
                profile,
                data=normalized_data,
                reason="legacy_normalization",
            )
            db.commit()
            db.refresh(profile)
        except StaleProfileRevisionError:
            db.rollback()
            current_profile = get_profile_record(db)
            if current_profile is None:
                raise
            return normalize_profile_record(current_profile, db)

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


@router.get("", response_model=ProfilePayload)
def get_profile(
    response: Response,
    db: Session = Depends(get_db),
) -> ProfilePayload:
    try:
        profile = get_or_create_profile(db)
        payload = normalize_profile_record(profile, db)
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
            if (
                not allow_destructive
                and is_suspicious_profile_replacement(current_profile, payload)
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
    payload: ResumeExperienceImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
) -> ResumeExperienceImportResponse:
    text = extract_resume_text(payload.resume_file_name, payload.resume_data_url)
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
    payload: MasterResumeImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> MasterResumeImportResponse:
    if not settings.openclaw_resume_import_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume analysis is disabled.",
        )

    try:
        content_type, content = decode_resume_data_url(payload.resume_data_url)
        source = extract_resume_source(
            file_name=payload.resume_file_name,
            content_type=content_type,
            content=content,
        )
    except (BinasciiError, ResumeSourceExtractionError, ValueError) as exc:
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
            file_name=payload.resume_file_name,
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
        review_sections=build_master_resume_review_sections(
            outcome.master_resume
        ),
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
    payload: ResumeExperienceImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
) -> ResumeEducationImportResponse:
    text = extract_resume_text(payload.resume_file_name, payload.resume_data_url)
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
    payload: ResumeExperienceImportRequest,
    _activity=Depends(record_ai_activity),
    settings: Settings = Depends(get_settings),
) -> ResumeSkillsImportResponse:
    text = extract_resume_text(payload.resume_file_name, payload.resume_data_url)
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
