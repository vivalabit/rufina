from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.resume import (
    AtsFinalReview,
    ExperienceRewrite,
    ResumeTailoringRunRecord,
    ResumeTailoringStageRecord,
    SeniorRecruiterAnalysis,
)
from app.services.ai_backend import AIResult
from app.services.resume_tailoring import sha256_json


SENIOR_RECRUITER_REQUEST_TYPE = "senior_recruiter_analysis"
EXPERIENCE_REWRITE_REQUEST_TYPE = "xyz_experience_rewrite"
ATS_FINAL_REVIEW_REQUEST_TYPE = "ats_final_review"

STAGE_SCHEMAS: dict[int, type[BaseModel]] = {
    1: SeniorRecruiterAnalysis,
    2: ExperienceRewrite,
    3: AtsFinalReview,
}
STAGE_REQUEST_TYPES = {
    1: SENIOR_RECRUITER_REQUEST_TYPE,
    2: EXPERIENCE_REWRITE_REQUEST_TYPE,
    3: ATS_FINAL_REVIEW_REQUEST_TYPE,
}


class ResumeTailoringTransitionError(RuntimeError):
    pass


@dataclass(frozen=True)
class ResumeTailoringAttempt:
    run_id: str
    stage_id: str
    stage_number: int
    attempt: int


def tailoring_input_fingerprint(
    request_type: str,
    payload: dict[str, object],
) -> str:
    return sha256_json(
        {
            "requestType": request_type,
            "input": payload,
        }
    )


def begin_first_stage(
    db: Session,
    *,
    resume_master_id: str,
    resume_master_version_id: str,
    target_job_id: str,
    input_fingerprint: str,
    model: str,
    backend: str,
) -> ResumeTailoringAttempt:
    run = retryable_first_stage_run(
        db,
        resume_master_version_id=resume_master_version_id,
        target_job_id=target_job_id,
        input_fingerprint=input_fingerprint,
    )
    timestamp = datetime.now(UTC)
    if run is None:
        run = ResumeTailoringRunRecord(
            id=uuid4().hex,
            resume_master_id=resume_master_id,
            resume_master_version_id=resume_master_version_id,
            target_job_id=target_job_id,
            status="running",
            current_stage=1,
            error="",
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(run)
        attempt_number = 1
    else:
        attempt_number = next_attempt_number(db, run.id, 1)
        run.status = "running"
        run.current_stage = 1
        run.error = ""
        run.completed_at = None
        run.updated_at = timestamp

    stage = ResumeTailoringStageRecord(
        id=uuid4().hex,
        run_id=run.id,
        stage_number=1,
        request_type=SENIOR_RECRUITER_REQUEST_TYPE,
        input_fingerprint=input_fingerprint,
        model=model,
        backend=backend,
        status="running",
        error="",
        attempt=attempt_number,
        started_at=timestamp,
    )
    db.add(stage)
    db.commit()
    return ResumeTailoringAttempt(
        run_id=run.id,
        stage_id=stage.id,
        stage_number=1,
        attempt=attempt_number,
    )


def begin_next_stage(
    db: Session,
    *,
    previous_output_record_id: str,
    previous_output: dict[str, object],
    stage_number: int,
    input_fingerprint: str,
    model: str,
    backend: str,
) -> ResumeTailoringAttempt:
    if stage_number not in (2, 3):
        raise ValueError("Only stage 2 or 3 can follow a previous stage")
    previous_stage = db.scalar(
        select(ResumeTailoringStageRecord)
        .where(
            ResumeTailoringStageRecord.stage_number == stage_number - 1,
            ResumeTailoringStageRecord.status == "succeeded",
            ResumeTailoringStageRecord.output_record_id
            == previous_output_record_id,
        )
        .order_by(ResumeTailoringStageRecord.attempt.desc())
    )
    if previous_stage is None:
        raise ResumeTailoringTransitionError(
            "Previous resume tailoring stage has no successful validated attempt"
        )
    validate_previous_stage_output(
        previous_stage,
        persisted_output=previous_output,
    )
    run = db.get(ResumeTailoringRunRecord, previous_stage.run_id)
    if run is None:
        raise ResumeTailoringTransitionError(
            "Resume tailoring run is unavailable"
        )
    if run.status == "succeeded":
        raise ResumeTailoringTransitionError(
            "Resume tailoring run is already complete"
        )
    if run.current_stage > stage_number:
        raise ResumeTailoringTransitionError(
            "Resume tailoring run cannot move backwards"
        )

    timestamp = datetime.now(UTC)
    attempt_number = next_attempt_number(db, run.id, stage_number)
    run.status = "running"
    run.current_stage = stage_number
    run.error = ""
    run.completed_at = None
    run.updated_at = timestamp
    stage = ResumeTailoringStageRecord(
        id=uuid4().hex,
        run_id=run.id,
        stage_number=stage_number,
        request_type=STAGE_REQUEST_TYPES[stage_number],
        input_fingerprint=input_fingerprint,
        model=model,
        backend=backend,
        status="running",
        error="",
        attempt=attempt_number,
        started_at=timestamp,
    )
    db.add(stage)
    db.commit()
    return ResumeTailoringAttempt(
        run_id=run.id,
        stage_id=stage.id,
        stage_number=stage_number,
        attempt=attempt_number,
    )


def bootstrap_successful_stage(
    db: Session,
    *,
    stage_number: int,
    output_record_id: str,
    structured_output: dict[str, object],
    input_fingerprint: str,
    resume_master_id: str,
    resume_master_version_id: str,
    target_job_id: str,
    previous_output_record_id: str | None,
    model: str,
    backend: str,
    latency_ms: int,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    token_count_source: str,
) -> ResumeTailoringStageRecord:
    existing = db.scalar(
        select(ResumeTailoringStageRecord).where(
            ResumeTailoringStageRecord.stage_number == stage_number,
            ResumeTailoringStageRecord.status == "succeeded",
            ResumeTailoringStageRecord.output_record_id == output_record_id,
        )
    )
    if existing is not None:
        validate_previous_stage_output(
            existing,
            persisted_output=structured_output,
        )
        return existing

    canonical_output = validate_stage_schema(stage_number, structured_output)
    timestamp = datetime.now(UTC)
    if stage_number == 1:
        run = ResumeTailoringRunRecord(
            id=uuid4().hex,
            resume_master_id=resume_master_id,
            resume_master_version_id=resume_master_version_id,
            target_job_id=target_job_id,
            status="running",
            current_stage=1,
            error="",
            created_at=timestamp,
            updated_at=timestamp,
        )
        db.add(run)
        db.flush()
    else:
        previous_stage = db.scalar(
            select(ResumeTailoringStageRecord).where(
                ResumeTailoringStageRecord.stage_number == stage_number - 1,
                ResumeTailoringStageRecord.status == "succeeded",
                ResumeTailoringStageRecord.output_record_id
                == previous_output_record_id,
            )
        )
        if previous_stage is None:
            raise ResumeTailoringTransitionError(
                "Cannot recover stage lineage without a validated previous stage"
            )
        run = db.get(ResumeTailoringRunRecord, previous_stage.run_id)
        if run is None:
            raise ResumeTailoringTransitionError(
                "Resume tailoring run is unavailable"
            )

    attempt_number = next_attempt_number(db, run.id, stage_number)
    stage = ResumeTailoringStageRecord(
        id=uuid4().hex,
        run_id=run.id,
        stage_number=stage_number,
        request_type=STAGE_REQUEST_TYPES[stage_number],
        input_fingerprint=input_fingerprint,
        structured_output=canonical_output,
        output_record_id=output_record_id,
        model=model,
        backend=backend,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        token_count_source=token_count_source,
        status="succeeded",
        error="",
        attempt=attempt_number,
        started_at=timestamp,
        completed_at=timestamp,
    )
    db.add(stage)
    run.current_stage = stage_number
    run.updated_at = timestamp
    if stage_number == 3:
        run.status = "succeeded"
        run.completed_at = timestamp
    else:
        run.status = "running"
        run.completed_at = None
    db.commit()
    db.refresh(stage)
    return stage


def complete_stage_attempt(
    db: Session,
    *,
    attempt: ResumeTailoringAttempt,
    structured_output: dict[str, object],
    result: AIResult,
    output_record_id: str,
) -> None:
    stage = db.get(ResumeTailoringStageRecord, attempt.stage_id)
    run = db.get(ResumeTailoringRunRecord, attempt.run_id)
    if stage is None or run is None or stage.status != "running":
        raise ResumeTailoringTransitionError(
            "Resume tailoring stage attempt is not running"
        )
    canonical_output = validate_stage_schema(
        attempt.stage_number,
        structured_output,
    )
    usage = result.usage
    timestamp = datetime.now(UTC)
    stage.structured_output = canonical_output
    stage.output_record_id = output_record_id
    stage.model = result.model
    stage.backend = result.backend
    stage.latency_ms = result.latency_ms
    stage.input_tokens = usage.input_tokens
    stage.output_tokens = usage.output_tokens
    stage.total_tokens = (
        usage.total_tokens or usage.input_tokens + usage.output_tokens
    )
    stage.token_count_source = usage.source
    stage.status = "succeeded"
    stage.error = ""
    stage.completed_at = timestamp
    run.current_stage = attempt.stage_number
    run.error = ""
    run.updated_at = timestamp
    if attempt.stage_number == 3:
        run.status = "succeeded"
        run.completed_at = timestamp
    else:
        run.status = "running"
    db.commit()


def fail_stage_attempt(
    db: Session,
    *,
    attempt: ResumeTailoringAttempt | None,
    error: str,
) -> None:
    if attempt is None:
        return
    db.rollback()
    stage = db.get(ResumeTailoringStageRecord, attempt.stage_id)
    run = db.get(ResumeTailoringRunRecord, attempt.run_id)
    if stage is None or run is None or stage.status != "running":
        return
    timestamp = datetime.now(UTC)
    normalized_error = error.strip()[:20_000] or "Unknown stage error"
    started_at = stage.started_at
    comparable_timestamp = (
        timestamp.replace(tzinfo=None)
        if started_at.tzinfo is None
        else timestamp
    )
    elapsed_ms = max(
        0,
        int((comparable_timestamp - started_at).total_seconds() * 1_000),
    )
    stage.status = "failed"
    stage.error = normalized_error
    stage.latency_ms = max(stage.latency_ms, elapsed_ms)
    stage.completed_at = timestamp
    run.status = "failed"
    run.current_stage = attempt.stage_number
    run.error = normalized_error
    run.completed_at = timestamp
    run.updated_at = timestamp
    db.commit()


def validate_previous_stage_output(
    stage: ResumeTailoringStageRecord,
    *,
    persisted_output: dict[str, object],
) -> None:
    if stage.status != "succeeded" or stage.structured_output is None:
        raise ResumeTailoringTransitionError(
            "Previous resume tailoring stage is not successfully validated"
        )
    saved = validate_stage_schema(stage.stage_number, stage.structured_output)
    persisted = validate_stage_schema(stage.stage_number, persisted_output)
    if saved != persisted:
        raise ResumeTailoringTransitionError(
            "Previous stage output does not match its durable artifact"
        )


def validate_stage_schema(
    stage_number: int,
    structured_output: dict[str, object],
) -> dict[str, object]:
    schema = STAGE_SCHEMAS[stage_number]
    try:
        validated = schema.model_validate(structured_output)
    except ValidationError as exc:
        raise ResumeTailoringTransitionError(
            f"Stage {stage_number} structured output failed schema validation"
        ) from exc
    return validated.model_dump(by_alias=True, exclude_none=True)


def retryable_first_stage_run(
    db: Session,
    *,
    resume_master_version_id: str,
    target_job_id: str,
    input_fingerprint: str,
) -> ResumeTailoringRunRecord | None:
    candidates = db.scalars(
        select(ResumeTailoringRunRecord)
        .where(
            ResumeTailoringRunRecord.resume_master_version_id
            == resume_master_version_id,
            ResumeTailoringRunRecord.target_job_id == target_job_id,
            ResumeTailoringRunRecord.status == "failed",
            ResumeTailoringRunRecord.current_stage == 1,
        )
        .order_by(ResumeTailoringRunRecord.created_at.desc())
    ).all()
    for run in candidates:
        latest = db.scalar(
            select(ResumeTailoringStageRecord)
            .where(
                ResumeTailoringStageRecord.run_id == run.id,
                ResumeTailoringStageRecord.stage_number == 1,
            )
            .order_by(ResumeTailoringStageRecord.attempt.desc())
        )
        if (
            latest is not None
            and latest.status == "failed"
            and latest.input_fingerprint == input_fingerprint
        ):
            return run
    return None


def next_attempt_number(
    db: Session,
    run_id: str,
    stage_number: int,
) -> int:
    current = db.scalar(
        select(func.max(ResumeTailoringStageRecord.attempt)).where(
            ResumeTailoringStageRecord.run_id == run_id,
            ResumeTailoringStageRecord.stage_number == stage_number,
        )
    )
    return int(current or 0) + 1


__all__ = [
    "ATS_FINAL_REVIEW_REQUEST_TYPE",
    "EXPERIENCE_REWRITE_REQUEST_TYPE",
    "SENIOR_RECRUITER_REQUEST_TYPE",
    "ResumeTailoringAttempt",
    "ResumeTailoringTransitionError",
    "begin_first_stage",
    "begin_next_stage",
    "bootstrap_successful_stage",
    "complete_stage_attempt",
    "fail_stage_attempt",
    "tailoring_input_fingerprint",
    "validate_previous_stage_output",
    "validate_stage_schema",
]
