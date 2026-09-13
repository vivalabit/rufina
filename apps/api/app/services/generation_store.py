from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationActor,
    GenerationRunArtifactPayload,
    GenerationRunArtifactRecord,
    GenerationRunCheckPayload,
    GenerationRunCheckRecord,
    GenerationRunEventPayload,
    GenerationRunEventRecord,
    GenerationRunMessageRecord,
    GenerationRunPayload,
    GenerationRunStage,
    GenerationRunStartRequest,
    GenerationRunStatus,
)
from app.services.generation_snapshot import build_generation_run_snapshot

ACTIVE_STATUSES = ("queued", "running", "awaiting_approval")
TERMINAL_STATUSES = ("completed", "failed", "cancelled")


class GenerationStoreError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def create_generation_run(
    db: Session,
    *,
    application_id: str,
    request: GenerationRunStartRequest,
    settings: Any,
) -> ApplicationGenerationRunRecord:
    existing = db.scalar(
        select(ApplicationGenerationRunRecord).where(
            ApplicationGenerationRunRecord.application_id == application_id,
            ApplicationGenerationRunRecord.idempotency_key == request.idempotency_key,
        )
    )
    if existing is not None:
        return existing
    active = db.scalar(
        select(ApplicationGenerationRunRecord).where(
            ApplicationGenerationRunRecord.application_id == application_id,
            ApplicationGenerationRunRecord.status.in_(ACTIVE_STATUSES),
        )
    )
    if active is not None:
        raise GenerationStoreError(
            "An application generation run is already active",
            code="run_already_active",
        )

    snapshot = build_generation_run_snapshot(
        db,
        application_id=application_id,
        start=request,
        settings=settings,
    )
    snapshot_data = snapshot.model_dump(mode="json", by_alias=True)
    run = ApplicationGenerationRunRecord(
        id=uuid4().hex,
        application_id=application_id,
        idempotency_key=request.idempotency_key,
        status="queued",
        stage="sources",
        backend=snapshot.execution.backend,
        model=snapshot.execution.model,
        reasoning_effort=snapshot.execution.reasoning_effort,
        settings_snapshot=snapshot.execution.as_dict(),
        input_snapshot=snapshot_data,
        input_fingerprint=snapshot.fingerprint,
        document_types=list(snapshot.request.document_types),
        result={},
    )
    db.add(run)
    db.flush()
    append_run_event(
        db,
        run=run,
        kind="run.created",
        data={
            "inputFingerprint": snapshot.fingerprint,
            "applicationRevision": snapshot.request.application.revision,
            "vacancyRevision": snapshot.request.vacancy.revision,
            "masterProfileVersion": snapshot.request.master_profile_version.version,
        },
    )
    db.commit()
    db.refresh(run)
    return run


def get_generation_run(
    db: Session,
    *,
    application_id: str,
    run_id: str,
) -> ApplicationGenerationRunRecord:
    run = db.scalar(
        select(ApplicationGenerationRunRecord).where(
            ApplicationGenerationRunRecord.id == run_id,
            ApplicationGenerationRunRecord.application_id == application_id,
        )
    )
    if run is None:
        raise GenerationStoreError("Generation run was not found", code="run_not_found")
    return run


def get_latest_generation_run(
    db: Session,
    *,
    application_id: str,
) -> ApplicationGenerationRunRecord:
    run = db.scalar(
        select(ApplicationGenerationRunRecord)
        .where(ApplicationGenerationRunRecord.application_id == application_id)
        .order_by(
            ApplicationGenerationRunRecord.created_at.desc(),
            ApplicationGenerationRunRecord.id.desc(),
        )
        .limit(1)
    )
    if run is None:
        raise GenerationStoreError("Generation run was not found", code="run_not_found")
    return run


def append_run_event(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    kind: str,
    data: dict[str, Any] | None = None,
    stage: GenerationRunStage | None = None,
) -> GenerationRunEventRecord:
    sequence = _next_sequence(db, GenerationRunEventRecord, run.id)
    event = GenerationRunEventRecord(
        id=uuid4().hex,
        run_id=run.id,
        sequence=sequence,
        kind=kind,
        stage=stage or run.stage,
        data=data or {},
    )
    db.add(event)
    db.flush()
    return event


def append_run_message(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    actor: GenerationActor,
    role: Literal["system", "user", "assistant"],
    content: str,
    raw_response: str = "",
    response_id: str | None = None,
    usage: dict[str, Any] | None = None,
) -> GenerationRunMessageRecord:
    message = GenerationRunMessageRecord(
        id=uuid4().hex,
        run_id=run.id,
        sequence=_next_sequence(db, GenerationRunMessageRecord, run.id),
        actor=actor,
        role=role,
        content=content,
        raw_response=raw_response,
        response_id=response_id,
        backend=run.backend,
        model=run.model,
        usage=usage or {},
    )
    db.add(message)
    db.flush()
    return message


def persist_run_artifact(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    artifact_type: str,
    file_name: str,
    content_type: str,
    content: bytes,
    document_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    document_id: str | None = None,
    document_version: int | None = None,
) -> GenerationRunArtifactRecord:
    current_version = db.scalar(
        select(func.max(GenerationRunArtifactRecord.version)).where(
            GenerationRunArtifactRecord.run_id == run.id,
            GenerationRunArtifactRecord.artifact_type == artifact_type,
        )
    )
    artifact = GenerationRunArtifactRecord(
        id=uuid4().hex,
        run_id=run.id,
        document_type=document_type,
        artifact_type=artifact_type,
        version=(current_version or 0) + 1,
        file_name=file_name,
        content_type=content_type,
        content_sha256=hashlib.sha256(content).hexdigest(),
        content=content,
        artifact_metadata=metadata or {},
        document_id=document_id,
        document_version=document_version,
    )
    db.add(artifact)
    db.flush()
    append_run_event(
        db,
        run=run,
        kind="artifact.created",
        data={
            "artifactId": artifact.id,
            "artifactType": artifact.artifact_type,
            "version": artifact.version,
            "contentSha256": artifact.content_sha256,
        },
    )
    return artifact


def persist_run_check(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    check_type: str,
    status: Literal["passed", "failed", "warning"],
    data: dict[str, Any] | None = None,
    artifact: GenerationRunArtifactRecord | None = None,
) -> GenerationRunCheckRecord:
    check = GenerationRunCheckRecord(
        id=uuid4().hex,
        run_id=run.id,
        artifact_id=artifact.id if artifact else None,
        check_type=check_type,
        status=status,
        artifact_sha256=artifact.content_sha256 if artifact else None,
        data=data or {},
    )
    db.add(check)
    return check


def transition_generation_run(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    status: GenerationRunStatus,
    stage: GenerationRunStage,
    event_kind: str,
    event_data: dict[str, Any] | None = None,
    pending_question: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    if run.status in TERMINAL_STATUSES:
        raise GenerationStoreError("Generation run is already finished", code="run_finished")
    run.status = status
    run.stage = stage
    run.pending_question = pending_question
    if result is not None:
        run.result = result
    run.error = error
    if status in TERMINAL_STATUSES:
        run.completed_at = datetime.now(UTC)
        run.lease_token = None
        run.lease_until = None
    append_run_event(db, run=run, kind=event_kind, data=event_data, stage=stage)
    try:
        db.commit()
        db.refresh(run)
    except StaleDataError as exc:
        db.rollback()
        raise GenerationStoreError(
            "Generation run changed concurrently",
            code="stale_run",
        ) from exc


def request_run_cancellation(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    expected_revision: int,
) -> None:
    if run.revision != expected_revision:
        raise GenerationStoreError("Generation run revision is stale", code="stale_run")
    if run.status in TERMINAL_STATUSES:
        return
    run.cancel_requested = True
    append_run_event(db, run=run, kind="run.cancellation_requested")
    db.commit()
    db.refresh(run)


def generation_run_payload(
    db: Session,
    run: ApplicationGenerationRunRecord,
) -> GenerationRunPayload:
    events = db.scalars(
        select(GenerationRunEventRecord)
        .where(GenerationRunEventRecord.run_id == run.id)
        .order_by(GenerationRunEventRecord.sequence)
    ).all()
    artifacts = db.scalars(
        select(GenerationRunArtifactRecord)
        .where(GenerationRunArtifactRecord.run_id == run.id)
        .order_by(GenerationRunArtifactRecord.created_at, GenerationRunArtifactRecord.id)
    ).all()
    checks = db.scalars(
        select(GenerationRunCheckRecord)
        .where(GenerationRunCheckRecord.run_id == run.id)
        .order_by(GenerationRunCheckRecord.created_at, GenerationRunCheckRecord.id)
    ).all()
    return GenerationRunPayload(
        id=run.id,
        applicationId=run.application_id,
        status=run.status,
        stage=run.stage,
        revision=run.revision,
        backend=run.backend,
        model=run.model,
        reasoningEffort=run.reasoning_effort,
        inputFingerprint=run.input_fingerprint,
        documentTypes=run.document_types,
        pendingQuestion=run.pending_question,
        result=run.result,
        error=run.error,
        cancelRequested=run.cancel_requested,
        events=[
            GenerationRunEventPayload(
                sequence=item.sequence,
                kind=item.kind,
                stage=item.stage,
                data=item.data,
                createdAt=item.created_at,
            )
            for item in events
        ],
        artifacts=[
            GenerationRunArtifactPayload(
                id=item.id,
                documentType=item.document_type,
                artifactType=item.artifact_type,
                version=item.version,
                fileName=item.file_name,
                contentType=item.content_type,
                contentSha256=item.content_sha256,
                metadata=item.artifact_metadata,
                documentId=item.document_id,
                documentVersion=item.document_version,
                createdAt=item.created_at,
            )
            for item in artifacts
        ],
        checks=[
            GenerationRunCheckPayload(
                id=item.id,
                artifactId=item.artifact_id,
                checkType=item.check_type,
                status=item.status,
                artifactSha256=item.artifact_sha256,
                data=item.data,
                createdAt=item.created_at,
            )
            for item in checks
        ],
        createdAt=run.created_at,
        updatedAt=run.updated_at,
        completedAt=run.completed_at,
    )


def _next_sequence(db: Session, model: Any, run_id: str) -> int:
    current = db.scalar(select(func.max(model.sequence)).where(model.run_id == run_id))
    return (current or 0) + 1


__all__ = [
    "ACTIVE_STATUSES",
    "GenerationStoreError",
    "append_run_event",
    "append_run_message",
    "create_generation_run",
    "generation_run_payload",
    "get_generation_run",
    "get_latest_generation_run",
    "persist_run_artifact",
    "persist_run_check",
    "request_run_cancellation",
    "transition_generation_run",
]
