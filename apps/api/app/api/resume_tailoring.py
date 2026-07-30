from dataclasses import replace
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity, get_bound_owner_id
from app.core.settings import Settings, get_settings
from app.models.jobs import StoredJobRecord
from app.models.resume import (
    AtsFinalReviewRecord,
    AtsFinalReviewRequest,
    AtsFinalReviewResponse,
    ExperienceRewrite,
    ExperienceRewriteRecord,
    ExperienceRewriteRequest,
    ExperienceRewriteResponse,
    FinalResume,
    ImaginatorDraft,
    ImaginatorProtectedFactsAuditAttestation,
    ImaginatorResumeRecord,
    ImaginatorResumeRequest,
    ImaginatorResumeResponse,
    MasterResume,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    SeniorRecruiterAnalysis,
    SeniorRecruiterAnalysisRecord,
    SeniorRecruiterAnalysisRequest,
    SeniorRecruiterAnalysisResponse,
)
from app.services.ai_privacy import require_current_ai_consent
from app.services.generation_context import (
    GenerationContextError,
    load_authoritative_application_generation_context,
)
from app.services.resume_docx_renderer import (
    DOCX_CONTENT_TYPE,
    ResumeDocxRenderError,
    render_final_resume_docx,
)
from app.services.resume_imaginator import (
    ResumeImaginatorError,
    generate_imaginator_resume_with_settings,
    persist_imaginator_resume,
    validate_imaginator_draft_render_binding,
    validate_imaginator_locks,
    validate_imaginator_protected_facts_attestation,
)
from app.services.resume_pdf_artifacts import (
    StoredResumePdfArtifact,
    find_imaginator_resume_pdf_artifact,
    find_resume_pdf_artifact,
    store_imaginator_resume_pdf_artifact,
    store_resume_pdf_artifact,
)
from app.services.resume_pdf_renderer import (
    ResolvedResumeTemplate,
    ResumePdfRenderError,
    ResumeTemplateNotFoundError,
    render_final_resume_pdf,
    render_resolved_final_resume_pdf,
    resolve_resume_template,
)
from app.services.resume_tailoring import (
    ATS_FINAL_REVIEW_PROMPT_VERSION,
    EXPERIENCE_REWRITE_PROMPT_VERSION,
    SENIOR_RECRUITER_PROMPT_VERSION,
    ResumeTailoringError,
    create_resume_tailoring_ai_facade,
    master_resume_with_candidate_confirmations,
    master_resume_with_supplemental_evidence,
    persist_ats_final_review,
    persist_experience_rewrite,
    persist_senior_recruiter_analysis,
    recruiter_analysis_with_supplemental_evidence,
    senior_recruiter_analysis_payload,
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
from app.services.resume_template_registry import is_bundled_resume_template_id

router = APIRouter(dependencies=[Depends(bind_request_identity)])


def resume_tailoring_master_resume(
    db: Session,
    *,
    master_resume: MasterResume,
    application_id: str | None,
    target_job_id: str,
) -> MasterResume:
    if application_id is None:
        return master_resume
    try:
        context = load_authoritative_application_generation_context(
            db,
            application_id=application_id,
        )
    except GenerationContextError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail=str(exc),
        ) from exc
    if context.job_id != target_job_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Resume tailoring application does not match the target vacancy",
        )
    return master_resume_with_candidate_confirmations(
        master_resume,
        context.confirmations,
    )


@router.post(
    "/imaginator",
    response_model=ImaginatorResumeResponse,
    response_model_exclude_none=True,
)
def run_imaginator_resume(
    payload: ImaginatorResumeRequest,
    _consent=Depends(require_current_ai_consent),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> ImaginatorResumeResponse:
    """Run the standalone idealized-candidate resume pipeline."""

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

        master_resume = resume_tailoring_master_resume(
            db,
            master_resume=MasterResume.model_validate(master_version.data),
            application_id=payload.application_id,
            target_job_id=job.id,
        )
        outcome = generate_imaginator_resume_with_settings(
            settings=settings,
            master_resume=master_resume,
            master_resume_version_id=master_version.id,
            target_job_id=job.id,
            vacancy=job.data,
            target_language=payload.target_language,
            revision_instruction=payload.revision_instruction or "",
        )
        return persist_imaginator_resume(
            db,
            master_version=master_version,
            application_id=payload.application_id,
            outcome=outcome,
        )
    except HTTPException:
        db.rollback()
        raise
    except ResumeImaginatorError as exc:
        db.rollback()
        status_code = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
            if exc.code
            in {
                "content_too_large",
                "context_too_large",
                "immutable_violation",
                "invalid_input",
                "invalid_output",
                "protected_fact_violation",
            }
            else status.HTTP_502_BAD_GATEWAY
        )
        raise HTTPException(
            status_code=status_code,
            detail=str(exc),
        ) from exc
    except ResumeTailoringError as exc:
        db.rollback()
        status_code = (
            status.HTTP_422_UNPROCESSABLE_CONTENT
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
            detail="Imaginator resume storage is temporarily unavailable",
        ) from exc


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

        master_resume = resume_tailoring_master_resume(
            db,
            master_resume=MasterResume.model_validate(master_version.data),
            application_id=payload.application_id,
            target_job_id=job.id,
        )
        stage_attempt = begin_first_stage(
            db,
            resume_master_id=master.id,
            resume_master_version_id=master_version.id,
            target_job_id=job.id,
            input_fingerprint=tailoring_input_fingerprint(
                SENIOR_RECRUITER_REQUEST_TYPE,
                {
                    "promptVersion": SENIOR_RECRUITER_PROMPT_VERSION,
                    "generationMode": payload.generation_mode,
                    "masterResumeVersionId": master_version.id,
                    "masterResume": master_resume.model_dump(
                        by_alias=True,
                        exclude_none=True,
                    ),
                    "targetJobId": job.id,
                    "vacancy": job.data,
                    "applicationId": payload.application_id,
                    **(
                        {"targetLanguage": payload.target_language}
                        if payload.target_language
                        else {}
                    ),
                    **(
                        {"revisionInstruction": payload.revision_instruction}
                        if payload.revision_instruction
                        else {}
                    ),
                },
            ),
            model=configured_tailoring_model(settings),
            backend=settings.ai_backend_mode,
        )
        facade = create_resume_tailoring_ai_facade(settings)
        analysis_options: dict[str, str] = {}
        if payload.target_language:
            analysis_options["target_language"] = payload.target_language
        if payload.revision_instruction:
            analysis_options["revision_instruction"] = payload.revision_instruction
        outcome = facade.analyze_as_senior_recruiter(
            master_resume=master_resume,
            target_job_id=job.id,
            vacancy=job.data,
            **analysis_options,
        )
        outcome = replace(
            outcome,
            analysis=recruiter_analysis_with_supplemental_evidence(
                outcome.analysis,
                master_resume,
            ),
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
            structured_output=senior_recruiter_analysis_payload(
                outcome.analysis,
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
        saved_analysis = SeniorRecruiterAnalysis.model_validate(recruiter_analysis.result)
        master_resume = master_resume_with_supplemental_evidence(
            master_resume,
            saved_analysis.supplemental_evidence,
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
                    "masterResume": master_resume.model_dump(
                        by_alias=True,
                        exclude_none=True,
                    ),
                    "targetJobId": recruiter_analysis.target_job_id,
                    "recruiterAnalysisId": recruiter_analysis.id,
                    "recruiterAnalysis": recruiter_analysis.result,
                    **(
                        {"targetLanguage": payload.target_language}
                        if payload.target_language
                        else {}
                    ),
                },
            ),
            model=configured_tailoring_model(settings),
            backend=settings.ai_backend_mode,
        )
        rewrite_options: dict[str, str] = {}
        if payload.target_language:
            rewrite_options["target_language"] = payload.target_language
        outcome = create_resume_tailoring_ai_facade(settings).rewrite_experience_with_xyz(
            master_resume=master_resume,
            target_job_id=recruiter_analysis.target_job_id,
            recruiter_analysis=saved_analysis,
            **rewrite_options,
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
        saved_rewrite = ExperienceRewrite.model_validate(experience_rewrite.result)
        saved_analysis = SeniorRecruiterAnalysis.model_validate(recruiter_analysis.result)
        master_resume = master_resume_with_supplemental_evidence(
            master_resume,
            saved_analysis.supplemental_evidence,
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
                    "masterResume": master_resume.model_dump(
                        by_alias=True,
                        exclude_none=True,
                    ),
                    "targetJobId": experience_rewrite.target_job_id,
                    "recruiterAnalysisId": recruiter_analysis.id,
                    "recruiterAnalysis": recruiter_analysis.result,
                    "experienceRewriteId": experience_rewrite.id,
                    "experienceRewrite": experience_rewrite.result,
                    **(
                        {"targetLanguage": payload.target_language}
                        if payload.target_language
                        else {}
                    ),
                },
            ),
            model=configured_tailoring_model(settings),
            backend=settings.ai_backend_mode,
        )
        review_options: dict[str, str] = {}
        if payload.target_language:
            review_options["target_language"] = payload.target_language
        outcome = create_resume_tailoring_ai_facade(settings).review_final_resume_for_ats(
            master_resume=master_resume,
            target_job_id=experience_rewrite.target_job_id,
            recruiter_analysis=saved_analysis,
            experience_rewrite=saved_rewrite,
            **review_options,
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


@router.get("/ats-final-review/{review_id}/pdf")
def download_ats_final_resume_pdf(
    review_id: str,
    template_id: str = Query(
        default="classic_single",
        alias="templateId",
        min_length=1,
        max_length=80,
    ),
    db: Session = Depends(get_db),
) -> Response:
    resolved_template: ResolvedResumeTemplate | None = None
    try:
        record = db.scalar(
            select(AtsFinalReviewRecord).where(
                AtsFinalReviewRecord.id == review_id,
                AtsFinalReviewRecord.owner_id == get_bound_owner_id(),
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ATS final review not found",
            )
        try:
            resume = FinalResume.model_validate(record.render_input)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored FinalResume render input is invalid",
            ) from exc
        resolved_template = resolve_resume_template(db, template_id)
        existing = find_resume_pdf_artifact(
            db,
            ats_final_review_id=record.id,
            template_id=resolved_template.id,
            template_version=resolved_template.version,
            design_sha256=resolved_template.design_sha256,
        )
        if existing is not None:
            return resume_pdf_artifact_response(existing)
        rewrite = db.scalar(
            select(ExperienceRewriteRecord).where(
                ExperienceRewriteRecord.id == record.experience_rewrite_id,
                ExperienceRewriteRecord.owner_id == get_bound_owner_id(),
            )
        )
        if rewrite is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored experience rewrite provenance is unavailable",
            )
        analysis = db.scalar(
            select(SeniorRecruiterAnalysisRecord).where(
                SeniorRecruiterAnalysisRecord.id == rewrite.senior_recruiter_analysis_id,
                SeniorRecruiterAnalysisRecord.owner_id == get_bound_owner_id(),
            )
        )
        if analysis is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored recruiter analysis provenance is unavailable",
            )
        final_resume_json = resume.model_dump(by_alias=True, exclude_none=True)
        if is_bundled_resume_template_id(resolved_template.id):
            pdf = render_final_resume_pdf(
                final_resume_json,
                template_id=resolved_template.base_template_id,
            )
        else:
            pdf = render_resolved_final_resume_pdf(
                final_resume_json,
                template=resolved_template,
            )
        filename = safe_resume_pdf_filename(resume.basics.full_name)
        artifact = store_resume_pdf_artifact(
            db,
            ats_review=record,
            experience_rewrite=rewrite,
            recruiter_analysis=analysis,
            final_resume=resume,
            pdf=pdf,
            file_name=filename,
            template=resolved_template,
            created_at=datetime.now(UTC),
        )
        db.commit()
        return resume_pdf_artifact_response(artifact)
    except HTTPException:
        db.rollback()
        raise
    except ResumeTemplateNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ResumePdfRenderError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        if resolved_template is not None:
            existing = find_resume_pdf_artifact(
                db,
                ats_final_review_id=review_id,
                template_id=resolved_template.id,
                template_version=resolved_template.version,
                design_sha256=resolved_template.design_sha256,
            )
            if existing is not None:
                return resume_pdf_artifact_response(existing)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Final resume PDF is temporarily unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Final resume PDF is temporarily unavailable",
        ) from exc


@router.get("/ats-final-review/{review_id}/docx")
def download_ats_final_resume_docx(
    review_id: str,
    template_id: str = Query(
        default="classic_single",
        alias="templateId",
        min_length=1,
        max_length=80,
    ),
    db: Session = Depends(get_db),
) -> Response:
    try:
        record = db.scalar(
            select(AtsFinalReviewRecord).where(
                AtsFinalReviewRecord.id == review_id,
                AtsFinalReviewRecord.owner_id == get_bound_owner_id(),
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ATS final review not found",
            )
        try:
            resume = FinalResume.model_validate(record.render_input)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored FinalResume render input is invalid",
            ) from exc
        resolved_template = resolve_resume_template(db, template_id)
        docx = render_final_resume_docx(
            resume.model_dump(by_alias=True, exclude_none=True),
            design=resolved_template.design,
        )
        return Response(
            content=docx,
            media_type=DOCX_CONTENT_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{safe_resume_docx_filename(resume.basics.full_name)}"'
                ),
                "X-Rufina-Template-Id": resolved_template.id,
                "X-Rufina-Template-Version": resolved_template.version,
            },
        )
    except HTTPException:
        raise
    except ResumeTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ResumeDocxRenderError, ResumePdfRenderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Final resume DOCX is temporarily unavailable",
        ) from exc


@router.get("/imaginator/{resume_id}/pdf")
def download_imaginator_resume_pdf(
    resume_id: str,
    template_id: str = Query(
        default="classic_single",
        alias="templateId",
        min_length=1,
        max_length=80,
    ),
    db: Session = Depends(get_db),
) -> Response:
    resolved_template: ResolvedResumeTemplate | None = None
    try:
        record = db.scalar(
            select(ImaginatorResumeRecord).where(
                ImaginatorResumeRecord.id == resume_id,
                ImaginatorResumeRecord.owner_id == get_bound_owner_id(),
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Imaginator resume not found",
            )
        resume = validated_imaginator_render_resume(db, record)

        resolved_template = resolve_resume_template(db, template_id)
        existing = find_imaginator_resume_pdf_artifact(
            db,
            imaginator_resume_id=record.id,
            template_id=resolved_template.id,
            template_version=resolved_template.version,
            design_sha256=resolved_template.design_sha256,
        )
        if existing is not None:
            return resume_pdf_artifact_response(existing)

        final_resume_json = resume.model_dump(by_alias=True, exclude_none=True)
        if is_bundled_resume_template_id(resolved_template.id):
            pdf = render_final_resume_pdf(
                final_resume_json,
                template_id=resolved_template.base_template_id,
            )
        else:
            pdf = render_resolved_final_resume_pdf(
                final_resume_json,
                template=resolved_template,
            )
        artifact = store_imaginator_resume_pdf_artifact(
            db,
            imaginator_resume=record,
            final_resume=resume,
            pdf=pdf,
            file_name=safe_resume_pdf_filename(resume.basics.full_name),
            template=resolved_template,
            created_at=datetime.now(UTC),
        )
        db.commit()
        return resume_pdf_artifact_response(artifact)
    except HTTPException:
        db.rollback()
        raise
    except ResumeTemplateNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ResumePdfRenderError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except IntegrityError as exc:
        db.rollback()
        if resolved_template is not None:
            existing = find_imaginator_resume_pdf_artifact(
                db,
                imaginator_resume_id=resume_id,
                template_id=resolved_template.id,
                template_version=resolved_template.version,
                design_sha256=resolved_template.design_sha256,
            )
            if existing is not None:
                return resume_pdf_artifact_response(existing)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Imaginator resume PDF is temporarily unavailable",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Imaginator resume PDF is temporarily unavailable",
        ) from exc


@router.get("/imaginator/{resume_id}/docx")
def download_imaginator_resume_docx(
    resume_id: str,
    template_id: str = Query(
        default="classic_single",
        alias="templateId",
        min_length=1,
        max_length=80,
    ),
    db: Session = Depends(get_db),
) -> Response:
    try:
        record = db.scalar(
            select(ImaginatorResumeRecord).where(
                ImaginatorResumeRecord.id == resume_id,
                ImaginatorResumeRecord.owner_id == get_bound_owner_id(),
            )
        )
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Imaginator resume not found",
            )
        resume = validated_imaginator_render_resume(db, record)

        resolved_template = resolve_resume_template(db, template_id)
        docx = render_final_resume_docx(
            resume.model_dump(by_alias=True, exclude_none=True),
            design=resolved_template.design,
        )
        return Response(
            content=docx,
            media_type=DOCX_CONTENT_TYPE,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="{safe_resume_docx_filename(resume.basics.full_name)}"'
                ),
                "X-Rufina-Template-Id": resolved_template.id,
                "X-Rufina-Template-Version": resolved_template.version,
            },
        )
    except HTTPException:
        raise
    except ResumeTemplateNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ResumeDocxRenderError, ResumePdfRenderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Imaginator resume DOCX is temporarily unavailable",
        ) from exc


def resume_pdf_artifact_response(
    artifact: StoredResumePdfArtifact,
) -> Response:
    return Response(
        content=artifact.file.content,
        media_type=artifact.file.content_type,
        headers={
            "Content-Disposition": (f'attachment; filename="{artifact.file.file_name}"'),
            "X-Rufina-Document-Id": artifact.document.id,
            "X-Rufina-Document-Version": str(artifact.file.version),
            "X-Rufina-Template-Id": (artifact.file.renderer_template_id or ""),
            "X-Rufina-Template-Version": (artifact.file.renderer_template_version or ""),
        },
    )


def validated_imaginator_render_resume(
    db: Session,
    record: ImaginatorResumeRecord,
) -> FinalResume:
    master_version = db.scalar(
        select(ResumeMasterVersionRecord).where(
            ResumeMasterVersionRecord.id
            == record.resume_master_version_id,
            ResumeMasterVersionRecord.resume_master_id
            == record.resume_master_id,
        )
    )
    if master_version is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored Imaginator Master Resume version is unavailable",
        )
    try:
        master_resume = MasterResume.model_validate(master_version.data)
        draft = ImaginatorDraft.model_validate(record.result)
        protected_facts_audit = (
            ImaginatorProtectedFactsAuditAttestation.model_validate(
                record.protected_facts_audit
            )
        )
        resume = FinalResume.model_validate(record.render_input)
        validate_imaginator_locks(
            resume,
            master_resume=master_resume,
        )
        validate_imaginator_draft_render_binding(
            draft=draft,
            final_resume=resume,
            master_resume=master_resume,
        )
        validate_imaginator_protected_facts_attestation(
            protected_facts_audit,
            draft=draft,
            master_resume=master_resume,
            require_current_prompt=False,
            revalidate_source_context=False,
        )
    except (ValidationError, ResumeImaginatorError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored Imaginator resume violates locked source facts",
        ) from exc
    if resume.target_job_id != record.target_job_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored Imaginator resume target job is inconsistent",
        )
    return resume


def safe_resume_pdf_filename(full_name: str) -> str:
    return safe_resume_filename(full_name, extension="pdf")


def safe_resume_docx_filename(full_name: str) -> str:
    return safe_resume_filename(full_name, extension="docx")


def safe_resume_filename(full_name: str, *, extension: str) -> str:
    safe_name = "".join(
        character
        for character in full_name.strip()
        if character.isascii() and (character.isalnum() or character in {" ", "-", "_"})
    )
    safe_name = "-".join(safe_name.split()).strip("-_")
    return f"{safe_name}-resume.{extension}" if safe_name else f"resume.{extension}"


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
    "download_imaginator_resume_docx",
    "download_imaginator_resume_pdf",
    "router",
    "run_ats_final_review",
    "run_imaginator_resume",
    "run_senior_recruiter_analysis",
    "run_xyz_experience_rewrite",
]
