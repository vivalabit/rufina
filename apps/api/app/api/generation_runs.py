import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.identity import bind_request_identity, current_owner_id, get_bound_owner_id
from app.core.settings import Settings, get_settings
from app.models.generation_runs import (
    GenerationRunAnswerRequest,
    GenerationRunArtifactRecord,
    GenerationRunCancelRequest,
    GenerationRunEventRecord,
    GenerationRunPayload,
    GenerationRunStartRequest,
)
from app.services.generation_input import GenerationInputError
from app.services.generation_store import (
    GenerationStoreError,
    create_generation_run,
    generation_run_payload,
    get_generation_run,
    get_latest_generation_run,
    queue_fit_decision,
    request_run_cancellation,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])


@router.post(
    "/{application_id}/generation/runs",
    response_model=GenerationRunPayload,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_generation_run(
    application_id: str,
    request: GenerationRunStartRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GenerationRunPayload:
    try:
        run = create_generation_run(
            db,
            application_id=application_id,
            request=request,
            settings=settings,
        )
        response.headers["ETag"] = f'"{run.revision}"'
        response.headers["Location"] = f"/applications/{application_id}/generation/runs/{run.id}"
        return generation_run_payload(db, run)
    except GenerationInputError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if exc.code.endswith("_not_found")
                else status.HTTP_409_CONFLICT
            ),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "run_conflict",
                "message": "Generation run conflicts with another request",
            },
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation run storage is temporarily unavailable",
        ) from exc


@router.get(
    "/{application_id}/generation/runs/current",
    response_model=GenerationRunPayload,
    response_model_by_alias=True,
)
def get_current_generation_run(
    application_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> GenerationRunPayload:
    try:
        run = get_latest_generation_run(db, application_id=application_id)
        response.headers["ETag"] = f'"{run.revision}"'
        return generation_run_payload(db, run)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc


@router.get(
    "/{application_id}/generation/runs/{run_id}",
    response_model=GenerationRunPayload,
    response_model_by_alias=True,
)
def get_application_generation_run(
    application_id: str,
    run_id: str,
    response: Response,
    db: Session = Depends(get_db),
) -> GenerationRunPayload:
    try:
        run = get_generation_run(db, application_id=application_id, run_id=run_id)
        response.headers["ETag"] = f'"{run.revision}"'
        return generation_run_payload(db, run)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc


@router.post(
    "/{application_id}/generation/runs/{run_id}/cancel",
    response_model=GenerationRunPayload,
    response_model_by_alias=True,
)
def cancel_application_generation_run(
    application_id: str,
    run_id: str,
    request: GenerationRunCancelRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> GenerationRunPayload:
    try:
        run = get_generation_run(db, application_id=application_id, run_id=run_id)
        request_run_cancellation(db, run=run, expected_revision=request.revision)
        response.headers["ETag"] = f'"{run.revision}"'
        return generation_run_payload(db, run)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc


@router.post(
    "/{application_id}/generation/runs/{run_id}/responses",
    response_model=GenerationRunPayload,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
)
def respond_to_generation_run(
    application_id: str,
    run_id: str,
    request: GenerationRunAnswerRequest,
    response: Response,
    db: Session = Depends(get_db),
) -> GenerationRunPayload:
    try:
        run = get_generation_run(db, application_id=application_id, run_id=run_id)
        queue_fit_decision(
            db,
            run=run,
            question_id=request.question_id,
            response=request.response,
            expected_revision=request.revision,
        )
        response.headers["ETag"] = f'"{run.revision}"'
        return generation_run_payload(db, run)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc


@router.get("/{application_id}/generation/runs/{run_id}/events")
def stream_generation_run_events(
    application_id: str,
    run_id: str,
    after: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    try:
        get_generation_run(db, application_id=application_id, run_id=run_id)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc
    owner_id = get_bound_owner_id()

    async def event_stream():
        cursor = after
        silent_polls = 0
        while True:
            token = current_owner_id.set(owner_id)
            try:
                with SessionLocal() as stream_db:
                    run = get_generation_run(
                        stream_db,
                        application_id=application_id,
                        run_id=run_id,
                    )
                    events = stream_db.scalars(
                        select(GenerationRunEventRecord)
                        .where(
                            GenerationRunEventRecord.run_id == run_id,
                            GenerationRunEventRecord.sequence > cursor,
                        )
                        .order_by(GenerationRunEventRecord.sequence)
                    ).all()
                    for event in events:
                        cursor = event.sequence
                        data = json.dumps(
                            {
                                "sequence": event.sequence,
                                "kind": event.kind,
                                "stage": event.stage,
                                "data": event.data,
                                "createdAt": event.created_at.isoformat(),
                            },
                            ensure_ascii=False,
                        )
                        yield f"id: {event.sequence}\nevent: {event.kind}\ndata: {data}\n\n"
                    if run.status in {"completed", "failed", "cancelled"} and not events:
                        return
            finally:
                current_owner_id.reset(token)
            silent_polls += 1
            if silent_polls % 20 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.75)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{application_id}/generation/runs/{run_id}/artifacts/{artifact_id}")
def download_generation_run_artifact(
    application_id: str,
    run_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
) -> Response:
    try:
        get_generation_run(db, application_id=application_id, run_id=run_id)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc
    artifact = db.scalar(
        select(GenerationRunArtifactRecord).where(
            GenerationRunArtifactRecord.id == artifact_id,
            GenerationRunArtifactRecord.run_id == run_id,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not found")
    return Response(
        content=artifact.content,
        media_type=artifact.content_type,
        headers={
            "Content-Disposition": f'inline; filename="{artifact.file_name}"',
            "ETag": f'"{artifact.content_sha256}"',
        },
    )


def _store_http_error(exc: GenerationStoreError) -> HTTPException:
    return HTTPException(
        status_code={
            "run_not_found": status.HTTP_404_NOT_FOUND,
            "stale_run": status.HTTP_412_PRECONDITION_FAILED,
            "run_already_active": status.HTTP_409_CONFLICT,
            "run_finished": status.HTTP_409_CONFLICT,
            "answer_not_expected": status.HTTP_409_CONFLICT,
            "question_mismatch": status.HTTP_409_CONFLICT,
        }.get(exc.code, status.HTTP_409_CONFLICT),
        detail={"code": exc.code, "message": str(exc)},
    )
