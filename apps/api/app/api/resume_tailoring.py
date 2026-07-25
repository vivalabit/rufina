from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.database import get_db
from app.core.identity import bind_request_identity, get_bound_owner_id
from app.core.settings import Settings, get_settings
from app.models.jobs import StoredJobRecord
from app.models.resume import (
    AtsFinalReviewRequest,
    AtsFinalReviewResponse,
    ExperienceRewrite,
    ExperienceRewriteRecord,
    ExperienceRewriteRequest,
    ExperienceRewriteResponse,
    MasterResume,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    SeniorRecruiterAnalysisRequest,
    SeniorRecruiterAnalysis,
    SeniorRecruiterAnalysisRecord,
    SeniorRecruiterAnalysisResponse,
)
from app.services.ai_privacy import require_current_ai_consent
from app.services.resume_tailoring import (
    ResumeTailoringError,
    create_resume_tailoring_ai_facade,
    persist_ats_final_review,
    persist_experience_rewrite,
    persist_senior_recruiter_analysis,
)


router = APIRouter(dependencies=[Depends(bind_request_identity)])


@router.post(
    "/senior-recruiter-analysis",
    response_model=SeniorRecruiterAnalysisResponse,
)
def run_senior_recruiter_analysis(
    payload: SeniorRecruiterAnalysisRequest,
    _consent=Depends(require_current_ai_consent),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> SeniorRecruiterAnalysisResponse:
    if not settings.openclaw_resume_tailoring_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume tailoring is disabled.",
        )

    try:
        master = db.get(ResumeMasterRecord, payload.master_resume_id)
        if master is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Master resume not found",
            )
        master_version = db.scalar(
            select(ResumeMasterVersionRecord).where(
                ResumeMasterVersionRecord.resume_master_id == master.id,
                ResumeMasterVersionRecord.version == master.current_version,
            )
        )
        if master_version is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Current master resume version is unavailable",
            )

        job = db.get(
            StoredJobRecord,
            (get_bound_owner_id(), payload.target_job_id),
        )
        if job is None or job.status != "active":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target job not found",
            )

        master_resume = MasterResume.model_validate(master_version.data)
        outcome = create_resume_tailoring_ai_facade(
            settings
        ).analyze_as_senior_recruiter(
            master_resume=master_resume,
            target_job_id=job.id,
            vacancy=job.data,
        )
        return persist_senior_recruiter_analysis(
            db,
            master_version=master_version,
            target_job_id=job.id,
            outcome=outcome,
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeTailoringError as exc:
        db.rollback()
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code in {"invalid_input", "context_too_large"}
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Senior recruiter analysis storage is temporarily unavailable",
        ) from exc


@router.post(
    "/experience-rewrite",
    response_model=ExperienceRewriteResponse,
)
def run_xyz_experience_rewrite(
    payload: ExperienceRewriteRequest,
    _consent=Depends(require_current_ai_consent),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ExperienceRewriteResponse:
    if not settings.openclaw_resume_tailoring_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume tailoring is disabled.",
        )

    try:
        recruiter_analysis = db.get(
            SeniorRecruiterAnalysisRecord,
            payload.senior_recruiter_analysis_id,
        )
        if recruiter_analysis is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Senior recruiter analysis not found",
            )
        master_version = db.get(
            ResumeMasterVersionRecord,
            recruiter_analysis.resume_master_version_id,
        )
        if master_version is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Analyzed Master Resume version is unavailable",
            )

        master_resume = MasterResume.model_validate(master_version.data)
        saved_analysis = SeniorRecruiterAnalysis.model_validate(
            recruiter_analysis.result
        )
        outcome = create_resume_tailoring_ai_facade(
            settings
        ).rewrite_experience_with_xyz(
            master_resume=master_resume,
            target_job_id=recruiter_analysis.target_job_id,
            recruiter_analysis=saved_analysis,
        )
        return persist_experience_rewrite(
            db,
            recruiter_analysis=recruiter_analysis,
            master_version=master_version,
            master_resume=master_resume,
            outcome=outcome,
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeTailoringError as exc:
        db.rollback()
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code in {"invalid_input", "context_too_large"}
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Experience rewrite storage is temporarily unavailable",
        ) from exc


@router.post(
    "/ats-final-review",
    response_model=AtsFinalReviewResponse,
    response_model_exclude_none=True,
)
def run_ats_final_review(
    payload: AtsFinalReviewRequest,
    _consent=Depends(require_current_ai_consent),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AtsFinalReviewResponse:
    if not settings.openclaw_resume_tailoring_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI resume tailoring is disabled.",
        )

    try:
        experience_rewrite = db.get(
            ExperienceRewriteRecord,
            payload.experience_rewrite_id,
        )
        if experience_rewrite is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experience rewrite not found",
            )
        master_version = db.get(
            ResumeMasterVersionRecord,
            experience_rewrite.resume_master_version_id,
        )
        recruiter_analysis = db.get(
            SeniorRecruiterAnalysisRecord,
            experience_rewrite.senior_recruiter_analysis_id,
        )
        if master_version is None or recruiter_analysis is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ATS final review inputs are unavailable",
            )

        master_resume = MasterResume.model_validate(master_version.data)
        saved_rewrite = ExperienceRewrite.model_validate(
            experience_rewrite.result
        )
        saved_analysis = SeniorRecruiterAnalysis.model_validate(
            recruiter_analysis.result
        )
        outcome = create_resume_tailoring_ai_facade(
            settings
        ).review_final_resume_for_ats(
            master_resume=master_resume,
            target_job_id=experience_rewrite.target_job_id,
            recruiter_analysis=saved_analysis,
            experience_rewrite=saved_rewrite,
        )
        return persist_ats_final_review(
            db,
            experience_rewrite=experience_rewrite,
            master_version=master_version,
            outcome=outcome,
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeTailoringError as exc:
        db.rollback()
        status_code = (
            status.HTTP_422_UNPROCESSABLE_ENTITY
            if exc.code in {"invalid_input", "context_too_large"}
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ATS final review storage is temporarily unavailable",
        ) from exc


__all__ = [
    "router",
    "run_ats_final_review",
    "run_senior_recruiter_analysis",
    "run_xyz_experience_rewrite",
]
