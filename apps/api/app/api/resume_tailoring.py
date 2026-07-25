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
    ATS_FINAL_REVIEW_PROMPT_VERSION,
    EXPERIENCE_REWRITE_PROMPT_VERSION,
    SENIOR_RECRUITER_PROMPT_VERSION,
    ResumeTailoringError,
    create_resume_tailoring_ai_facade,
    persist_ats_final_review,
    persist_experience_rewrite,
    persist_senior_recruiter_analysis,
)
from app.services.resume_tailoring_runs import (
    ATS_FINAL_REVIEW_REQUEST_TYPE,
    EXPERIENCE_REWRITE_REQUEST_TYPE,
    SENIOR_RECRUITER_REQUEST_TYPE,
    ResumeTailoringAttempt,
    ResumeTailoringTransitionError,
    begin_first_stage,
    begin_next_stage,
    bootstrap_successful_stage,
    complete_stage_attempt,
    fail_stage_attempt,
    tailoring_input_fingerprint,
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
    stage_attempt: ResumeTailoringAttempt | None = None
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
        stage_attempt = begin_first_stage(
            db,
            resume_master_id=master.id,
            resume_master_version_id=master_version.id,
            target_job_id=job.id,
            input_fingerprint=tailoring_input_fingerprint(
                SENIOR_RECRUITER_REQUEST_TYPE,
                {
                    "promptVersion": SENIOR_RECRUITER_PROMPT_VERSION,
                    "masterResumeVersionId": master_version.id,
                    "masterResume": master_version.data,
                    "targetJobId": job.id,
                    "vacancy": job.data,
                },
            ),
            model=configured_tailoring_model(settings),
            backend=settings.ai_backend_mode,
        )
        outcome = create_resume_tailoring_ai_facade(
            settings
        ).analyze_as_senior_recruiter(
            master_resume=master_resume,
            target_job_id=job.id,
            vacancy=job.data,
        )
        response = persist_senior_recruiter_analysis(
            db,
            master_version=master_version,
            target_job_id=job.id,
            outcome=outcome,
        )
        complete_stage_attempt(
            db,
            attempt=stage_attempt,
            structured_output=outcome.analysis.model_dump(
                by_alias=True,
                exclude_none=True,
            ),
            result=outcome.result,
            output_record_id=response.id,
        )
        return response.model_copy(
            update={
                "run_id": stage_attempt.run_id,
                "attempt": stage_attempt.attempt,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeTailoringTransitionError as exc:
        fail_attempt_safely(db, stage_attempt, str(exc))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ResumeTailoringError as exc:
        fail_attempt_safely(db, stage_attempt, str(exc))
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
        fail_attempt_safely(db, stage_attempt, str(exc))
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
    stage_attempt: ResumeTailoringAttempt | None = None
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
        ensure_analysis_stage(db, recruiter_analysis)
        saved_analysis = SeniorRecruiterAnalysis.model_validate(
            recruiter_analysis.result
        )
        stage_attempt = begin_next_stage(
            db,
            previous_output_record_id=recruiter_analysis.id,
            previous_output=recruiter_analysis.result,
            stage_number=2,
            input_fingerprint=tailoring_input_fingerprint(
                EXPERIENCE_REWRITE_REQUEST_TYPE,
                {
                    "promptVersion": EXPERIENCE_REWRITE_PROMPT_VERSION,
                    "masterResumeVersionId": master_version.id,
                    "masterResume": master_version.data,
                    "targetJobId": recruiter_analysis.target_job_id,
                    "recruiterAnalysisId": recruiter_analysis.id,
                    "recruiterAnalysis": recruiter_analysis.result,
                },
            ),
            model=configured_tailoring_model(settings),
            backend=settings.ai_backend_mode,
        )
        outcome = create_resume_tailoring_ai_facade(
            settings
        ).rewrite_experience_with_xyz(
            master_resume=master_resume,
            target_job_id=recruiter_analysis.target_job_id,
            recruiter_analysis=saved_analysis,
        )
        response = persist_experience_rewrite(
            db,
            recruiter_analysis=recruiter_analysis,
            master_version=master_version,
            master_resume=master_resume,
            outcome=outcome,
        )
        complete_stage_attempt(
            db,
            attempt=stage_attempt,
            structured_output=outcome.rewrite.model_dump(
                by_alias=True,
                exclude_none=True,
            ),
            result=outcome.result,
            output_record_id=response.id,
        )
        return response.model_copy(
            update={
                "run_id": stage_attempt.run_id,
                "attempt": stage_attempt.attempt,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeTailoringTransitionError as exc:
        fail_attempt_safely(db, stage_attempt, str(exc))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ResumeTailoringError as exc:
        fail_attempt_safely(db, stage_attempt, str(exc))
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
        fail_attempt_safely(db, stage_attempt, str(exc))
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
    stage_attempt: ResumeTailoringAttempt | None = None
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
        ensure_rewrite_stage(db, experience_rewrite, recruiter_analysis)
        saved_rewrite = ExperienceRewrite.model_validate(
            experience_rewrite.result
        )
        saved_analysis = SeniorRecruiterAnalysis.model_validate(
            recruiter_analysis.result
        )
        stage_attempt = begin_next_stage(
            db,
            previous_output_record_id=experience_rewrite.id,
            previous_output=experience_rewrite.result,
            stage_number=3,
            input_fingerprint=tailoring_input_fingerprint(
                ATS_FINAL_REVIEW_REQUEST_TYPE,
                {
                    "promptVersion": ATS_FINAL_REVIEW_PROMPT_VERSION,
                    "masterResumeVersionId": master_version.id,
                    "masterResume": master_version.data,
                    "targetJobId": experience_rewrite.target_job_id,
                    "recruiterAnalysisId": recruiter_analysis.id,
                    "recruiterAnalysis": recruiter_analysis.result,
                    "experienceRewriteId": experience_rewrite.id,
                    "experienceRewrite": experience_rewrite.result,
                },
            ),
            model=configured_tailoring_model(settings),
            backend=settings.ai_backend_mode,
        )
        outcome = create_resume_tailoring_ai_facade(
            settings
        ).review_final_resume_for_ats(
            master_resume=master_resume,
            target_job_id=experience_rewrite.target_job_id,
            recruiter_analysis=saved_analysis,
            experience_rewrite=saved_rewrite,
        )
        response = persist_ats_final_review(
            db,
            experience_rewrite=experience_rewrite,
            master_version=master_version,
            outcome=outcome,
        )
        complete_stage_attempt(
            db,
            attempt=stage_attempt,
            structured_output=outcome.review.model_dump(
                by_alias=True,
                exclude_none=True,
            ),
            result=outcome.result,
            output_record_id=response.id,
        )
        return response.model_copy(
            update={
                "run_id": stage_attempt.run_id,
                "attempt": stage_attempt.attempt,
            }
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeTailoringTransitionError as exc:
        fail_attempt_safely(db, stage_attempt, str(exc))
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ResumeTailoringError as exc:
        fail_attempt_safely(db, stage_attempt, str(exc))
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
        fail_attempt_safely(db, stage_attempt, str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="ATS final review storage is temporarily unavailable",
        ) from exc


def ensure_analysis_stage(
    db: Session,
    analysis: SeniorRecruiterAnalysisRecord,
) -> None:
    bootstrap_successful_stage(
        db,
        stage_number=1,
        output_record_id=analysis.id,
        structured_output=analysis.result,
        input_fingerprint=tailoring_input_fingerprint(
            SENIOR_RECRUITER_REQUEST_TYPE,
            {
                "legacyArtifactId": analysis.id,
                "resumeMasterVersionId": analysis.resume_master_version_id,
                "targetJobId": analysis.target_job_id,
                "vacancyHash": analysis.vacancy_hash,
                "promptVersion": analysis.prompt_version,
            },
        ),
        resume_master_id=analysis.resume_master_id,
        resume_master_version_id=analysis.resume_master_version_id,
        target_job_id=analysis.target_job_id,
        previous_output_record_id=None,
        model=analysis.model,
        backend=analysis.backend,
        latency_ms=analysis.latency_ms,
        input_tokens=analysis.input_tokens,
        output_tokens=analysis.output_tokens,
        total_tokens=analysis.total_tokens,
        token_count_source=analysis.token_count_source,
    )


def ensure_rewrite_stage(
    db: Session,
    rewrite: ExperienceRewriteRecord,
    analysis: SeniorRecruiterAnalysisRecord,
) -> None:
    ensure_analysis_stage(db, analysis)
    bootstrap_successful_stage(
        db,
        stage_number=2,
        output_record_id=rewrite.id,
        structured_output=rewrite.result,
        input_fingerprint=tailoring_input_fingerprint(
            EXPERIENCE_REWRITE_REQUEST_TYPE,
            {
                "legacyArtifactId": rewrite.id,
                "recruiterAnalysisId": analysis.id,
                "resumeMasterVersionId": rewrite.resume_master_version_id,
                "targetJobId": rewrite.target_job_id,
                "promptVersion": rewrite.prompt_version,
            },
        ),
        resume_master_id=rewrite.resume_master_id,
        resume_master_version_id=rewrite.resume_master_version_id,
        target_job_id=rewrite.target_job_id,
        previous_output_record_id=analysis.id,
        model=rewrite.model,
        backend=rewrite.backend,
        latency_ms=rewrite.latency_ms,
        input_tokens=rewrite.input_tokens,
        output_tokens=rewrite.output_tokens,
        total_tokens=rewrite.total_tokens,
        token_count_source=rewrite.token_count_source,
    )


def fail_attempt_safely(
    db: Session,
    attempt: ResumeTailoringAttempt | None,
    error: str,
) -> None:
    try:
        fail_stage_attempt(db, attempt=attempt, error=error)
    except SQLAlchemyError:
        db.rollback()


def configured_tailoring_model(settings: Settings) -> str:
    return (
        settings.openai_api_model
        if settings.ai_backend_mode == "openai_api"
        else settings.openclaw_resume_tailoring_model
    )


__all__ = [
    "router",
    "run_ats_final_review",
    "run_senior_recruiter_analysis",
    "run_xyz_experience_rewrite",
]
