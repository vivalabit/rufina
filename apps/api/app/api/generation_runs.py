from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import bind_request_identity
from app.core.settings import Settings, get_settings
from app.models.generation_runs import (
    GenerationRunCancelRequest,
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


def _store_http_error(exc: GenerationStoreError) -> HTTPException:
    return HTTPException(
        status_code={
            "run_not_found": status.HTTP_404_NOT_FOUND,
            "stale_run": status.HTTP_412_PRECONDITION_FAILED,
            "run_already_active": status.HTTP_409_CONFLICT,
            "run_finished": status.HTTP_409_CONFLICT,
        }.get(exc.code, status.HTTP_409_CONFLICT),
        detail={"code": exc.code, "message": str(exc)},
    )
