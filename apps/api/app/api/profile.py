from binascii import Error as BinasciiError
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

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
    MasterResumeImportRequest,
    MasterResumeImportResponse,
    ResumeSourceExtraction,
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
from app.services.resume_source_extraction import (
    ResumeSourceExtractionError,
    extract_resume_source,
)
from app.services.ai_privacy import require_current_ai_consent
from app.services.profile_versions import (
    is_suspicious_profile_replacement,
    record_profile_version,
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
        record_profile_version(db, profile, reason="legacy_normalization")
        profile.data = normalized_data
        db.commit()
        db.refresh(profile)

    return ProfilePayload.model_validate(profile.data)


def get_or_create_profile(db: Session) -> ProfileRecord:
    profile = db.get(ProfileRecord, "default")
    if profile:
        return profile

    profile = ProfileRecord(id="default", data=default_profile.model_dump())
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.get("", response_model=ProfilePayload)
def get_profile(db: Session = Depends(get_db)) -> ProfilePayload:
    try:
        profile = get_or_create_profile(db)
        return normalize_profile_record(profile, db)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile database is unavailable",
        ) from exc


@router.put("", response_model=ProfilePayload)
def update_profile(
    payload: ProfilePayload,
    allow_destructive: bool = False,
    db: Session = Depends(get_db),
) -> ProfilePayload:
    try:
        profile = db.get(ProfileRecord, "default")
        if profile:
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
                )
            if current_profile != payload:
                record_profile_version(db, profile, reason="api_update")
            profile.data = payload.model_dump()
        else:
            profile = ProfileRecord(id="default", data=payload.model_dump())
            db.add(profile)

        db.commit()
        db.refresh(profile)
        return ProfilePayload.model_validate(profile.data)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Profile database is unavailable",
        ) from exc


@router.post("/import-experience-from-resume", response_model=ResumeExperienceImportResponse)
def import_experience_from_resume(
    payload: ResumeExperienceImportRequest,
    _consent=Depends(require_current_ai_consent),
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
    _consent=Depends(require_current_ai_consent),
    settings: Settings = Depends(get_settings),
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

    return MasterResumeImportResponse(
        master_resume=outcome.master_resume,
        source=source,
        model=outcome.model,
        backend=outcome.backend,
    )


@router.post("/import-education-from-resume", response_model=ResumeEducationImportResponse)
def import_education_from_resume(
    payload: ResumeExperienceImportRequest,
    _consent=Depends(require_current_ai_consent),
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
    _consent=Depends(require_current_ai_consent),
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
