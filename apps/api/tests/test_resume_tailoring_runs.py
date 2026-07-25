from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.resume import (
    ResumeTailoringRunRecord,
    ResumeTailoringStageRecord,
)
from app.services.ai_backend import AIResult, AIUsage
from app.services.resume_tailoring_runs import (
    ATS_FINAL_REVIEW_REQUEST_TYPE,
    EXPERIENCE_REWRITE_REQUEST_TYPE,
    SENIOR_RECRUITER_REQUEST_TYPE,
    ResumeTailoringTransitionError,
    begin_first_stage,
    begin_next_stage,
    complete_stage_attempt,
    fail_stage_attempt,
    tailoring_input_fingerprint,
)
from tests.test_ats_final_review import (
    experience_rewrite_payload,
    final_review_payload,
    recruiter_analysis_payload,
)


@pytest.fixture
def db() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )
    with testing_session() as session:
        yield session
    engine.dispose()


def ai_result(stage_number: int) -> AIResult:
    return AIResult(
        text="",
        structured_data={},
        model=f"model-stage-{stage_number}",
        backend="openai_api",
        usage=AIUsage(
            input_tokens=stage_number * 100,
            output_tokens=stage_number * 50,
            total_tokens=stage_number * 150,
            source="provider",
        ),
        latency_ms=stage_number * 111,
        session_id=f"response-stage-{stage_number}",
    )


def fingerprint(stage_number: int) -> str:
    return tailoring_input_fingerprint(
        f"request-{stage_number}",
        {"stage": stage_number, "input": "exact"},
    )


def test_durable_run_records_all_three_validated_stage_attempts(
    db: Session,
) -> None:
    master_resume_id = "master-resume"
    stage_one_output = recruiter_analysis_payload()
    stage_two_output = experience_rewrite_payload(master_resume_id)
    stage_three_output = final_review_payload(master_resume_id)

    stage_one = begin_first_stage(
        db,
        resume_master_id=master_resume_id,
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )
    complete_stage_attempt(
        db,
        attempt=stage_one,
        structured_output=stage_one_output,
        result=ai_result(1),
        output_record_id="analysis-output",
    )
    stage_two = begin_next_stage(
        db,
        previous_output_record_id="analysis-output",
        previous_output=stage_one_output,
        stage_number=2,
        input_fingerprint=fingerprint(2),
        model="configured-model",
        backend="openai_api",
    )
    complete_stage_attempt(
        db,
        attempt=stage_two,
        structured_output=stage_two_output,
        result=ai_result(2),
        output_record_id="rewrite-output",
    )
    stage_three = begin_next_stage(
        db,
        previous_output_record_id="rewrite-output",
        previous_output=stage_two_output,
        stage_number=3,
        input_fingerprint=fingerprint(3),
        model="configured-model",
        backend="openai_api",
    )
    complete_stage_attempt(
        db,
        attempt=stage_three,
        structured_output=stage_three_output,
        result=ai_result(3),
        output_record_id="review-output",
    )

    run = db.get(ResumeTailoringRunRecord, stage_one.run_id)
    stages = db.scalars(
        select(ResumeTailoringStageRecord)
        .where(ResumeTailoringStageRecord.run_id == stage_one.run_id)
        .order_by(ResumeTailoringStageRecord.stage_number)
    ).all()

    assert run is not None
    assert run.status == "succeeded"
    assert run.current_stage == 3
    assert run.error == ""
    assert run.completed_at is not None
    assert [stage.request_type for stage in stages] == [
        SENIOR_RECRUITER_REQUEST_TYPE,
        EXPERIENCE_REWRITE_REQUEST_TYPE,
        ATS_FINAL_REVIEW_REQUEST_TYPE,
    ]
    assert [stage.attempt for stage in stages] == [1, 1, 1]
    assert all(len(stage.input_fingerprint) == 64 for stage in stages)
    assert [stage.structured_output for stage in stages] == [
        stage_one_output,
        stage_two_output,
        stage_three_output,
    ]
    assert [stage.model for stage in stages] == [
        "model-stage-1",
        "model-stage-2",
        "model-stage-3",
    ]
    assert all(stage.backend == "openai_api" for stage in stages)
    assert [stage.latency_ms for stage in stages] == [111, 222, 333]
    assert [stage.total_tokens for stage in stages] == [150, 300, 450]
    assert all(stage.status == "succeeded" for stage in stages)
    assert all(stage.error == "" for stage in stages)
    stages[0].model = "tampered-model"
    with pytest.raises(
        ValueError,
        match="Completed resume tailoring stages are immutable",
    ):
        db.commit()


def test_next_stage_revalidates_durable_previous_output(
    db: Session,
) -> None:
    output = recruiter_analysis_payload()
    first = begin_first_stage(
        db,
        resume_master_id="master-resume",
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )
    complete_stage_attempt(
        db,
        attempt=first,
        structured_output=output,
        result=ai_result(1),
        output_record_id="analysis-output",
    )
    db.execute(
        update(ResumeTailoringStageRecord)
        .where(ResumeTailoringStageRecord.id == first.stage_id)
        .values(structured_output={"missingKeywords": [], "redFlags": []})
    )
    db.commit()

    with pytest.raises(
        ResumeTailoringTransitionError,
        match="failed schema validation",
    ):
        begin_next_stage(
            db,
            previous_output_record_id="analysis-output",
            previous_output=output,
            stage_number=2,
            input_fingerprint=fingerprint(2),
            model="configured-model",
            backend="openai_api",
        )

    assert db.scalars(
        select(ResumeTailoringStageRecord).where(
            ResumeTailoringStageRecord.stage_number == 2
        )
    ).all() == []


def test_next_stage_rejects_mismatched_persisted_output(
    db: Session,
) -> None:
    output = recruiter_analysis_payload()
    first = begin_first_stage(
        db,
        resume_master_id="master-resume",
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )
    complete_stage_attempt(
        db,
        attempt=first,
        structured_output=output,
        result=ai_result(1),
        output_record_id="analysis-output",
    )
    different = recruiter_analysis_payload()
    different["redFlags"][0]["flag"] = "Different valid red flag"

    with pytest.raises(
        ResumeTailoringTransitionError,
        match="does not match its durable artifact",
    ):
        begin_next_stage(
            db,
            previous_output_record_id="analysis-output",
            previous_output=different,
            stage_number=2,
            input_fingerprint=fingerprint(2),
            model="configured-model",
            backend="openai_api",
        )


def test_failed_stage_is_durable_and_same_input_retries_with_next_attempt(
    db: Session,
) -> None:
    first = begin_first_stage(
        db,
        resume_master_id="master-resume",
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )
    fail_stage_attempt(
        db,
        attempt=first,
        error="Provider timeout",
    )
    retry = begin_first_stage(
        db,
        resume_master_id="master-resume",
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )

    assert retry.run_id == first.run_id
    assert retry.attempt == 2
    stages = db.scalars(
        select(ResumeTailoringStageRecord)
        .where(ResumeTailoringStageRecord.run_id == first.run_id)
        .order_by(ResumeTailoringStageRecord.attempt)
    ).all()
    assert [(stage.attempt, stage.status, stage.error) for stage in stages] == [
        (1, "failed", "Provider timeout"),
        (2, "running", ""),
    ]


def test_next_stage_requires_a_successful_previous_attempt(
    db: Session,
) -> None:
    begin_first_stage(
        db,
        resume_master_id="master-resume",
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )

    with pytest.raises(
        ResumeTailoringTransitionError,
        match="no successful validated attempt",
    ):
        begin_next_stage(
            db,
            previous_output_record_id="missing-output",
            previous_output=recruiter_analysis_payload(),
            stage_number=2,
            input_fingerprint=fingerprint(2),
            model="configured-model",
            backend="openai_api",
        )


def test_failed_second_stage_retries_in_the_same_run(
    db: Session,
) -> None:
    output = recruiter_analysis_payload()
    first = begin_first_stage(
        db,
        resume_master_id="master-resume",
        resume_master_version_id="master-version",
        target_job_id="job-platform",
        input_fingerprint=fingerprint(1),
        model="configured-model",
        backend="openai_api",
    )
    complete_stage_attempt(
        db,
        attempt=first,
        structured_output=output,
        result=ai_result(1),
        output_record_id="analysis-output",
    )
    second = begin_next_stage(
        db,
        previous_output_record_id="analysis-output",
        previous_output=output,
        stage_number=2,
        input_fingerprint=fingerprint(2),
        model="configured-model",
        backend="openai_api",
    )
    fail_stage_attempt(db, attempt=second, error="Invalid provider JSON")
    retry = begin_next_stage(
        db,
        previous_output_record_id="analysis-output",
        previous_output=output,
        stage_number=2,
        input_fingerprint=fingerprint(2),
        model="configured-model",
        backend="openai_api",
    )

    assert retry.run_id == first.run_id
    assert retry.attempt == 2
    failed = db.get(ResumeTailoringStageRecord, second.stage_id)
    assert failed is not None
    assert failed.model == "configured-model"
    assert failed.backend == "openai_api"
    assert failed.status == "failed"
    assert failed.error == "Invalid provider JSON"
    assert failed.latency_ms >= 0
    assert failed.input_tokens == 0
    assert failed.output_tokens == 0
