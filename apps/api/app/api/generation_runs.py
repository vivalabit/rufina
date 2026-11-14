import asyncio
import hashlib
import json
from collections import OrderedDict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, get_db
from app.core.identity import bind_request_identity, current_owner_id, get_bound_owner_id
from app.core.settings import Settings, get_settings
from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationRunArtifactRecord,
    GenerationRunCancelRequest,
    GenerationRunEventRecord,
    GenerationRunPayload,
    GenerationRunRenderRequest,
    GenerationRunStartRequest,
    GenerationRunTemplatePayload,
)
from app.models.resume import FinalResume
from app.services.document_rendering import (
    DocumentRenderError,
    list_document_templates,
    normalize_document_template_id,
    render_resume_to_fit,
    resolve_document_template,
)
from app.services.document_thumbnail import (
    PdfThumbnailRenderError,
    render_pdf_first_page_thumbnail,
)
from app.services.generation_input import GenerationInputError
from app.services.generation_snapshot import run_request
from app.services.generation_store import (
    GenerationStoreError,
    create_generation_run,
    generation_run_payload,
    get_generation_run,
    get_latest_generation_run,
    request_run_cancellation,
)
from app.services.generation_workflow import (
    GenerationWorkflow,
    GenerationWorkflowError,
    resume_page_limit,
    stored_content,
)
from app.services.resume_pdf_renderer import ResumePdfRenderError

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
    "/{application_id}/generation/runs",
    response_model=list[GenerationRunPayload],
    response_model_by_alias=True,
)
def list_application_generation_runs(
    application_id: str,
    db: Session = Depends(get_db),
) -> list[GenerationRunPayload]:
    runs = db.scalars(
        select(ApplicationGenerationRunRecord)
        .where(ApplicationGenerationRunRecord.application_id == application_id)
        .order_by(
            ApplicationGenerationRunRecord.created_at.desc(),
            ApplicationGenerationRunRecord.id.desc(),
        )
    ).all()
    return [generation_run_payload(db, run) for run in runs]


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
    "/{application_id}/generation/runs/{run_id}/render",
    response_model=GenerationRunPayload,
    response_model_by_alias=True,
)
def render_generation_run_in_template(
    application_id: str,
    run_id: str,
    request: GenerationRunRenderRequest,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> GenerationRunPayload:
    """Render a finished run's documents in another template. No model is called."""
    try:
        run = get_generation_run(db, application_id=application_id, run_id=run_id)
        if run.revision != request.revision:
            raise GenerationStoreError("Generation run revision is stale", code="stale_run")
        GenerationWorkflow(settings=settings).render_in_template(
            db, run, template_id=request.template_id
        )
        response.headers["ETag"] = f'"{run.revision}"'
        return generation_run_payload(db, run)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc
    except GenerationWorkflowError as exc:
        raise _workflow_http_error(exc) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation run storage is temporarily unavailable",
        ) from exc


@router.get(
    "/{application_id}/generation/runs/{run_id}/templates",
    response_model=list[GenerationRunTemplatePayload],
    response_model_by_alias=True,
)
def list_generation_run_templates(
    application_id: str,
    run_id: str,
    db: Session = Depends(get_db),
) -> list[GenerationRunTemplatePayload]:
    """Gallery templates for a run, with the one its current files use."""
    try:
        run = get_generation_run(db, application_id=application_id, run_id=run_id)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc
    render = run.result.get("render")
    current = normalize_document_template_id(
        render.get("templateId") if isinstance(render, dict) else None
    )
    return [
        GenerationRunTemplatePayload(
            id=template.id,
            name=template.name,
            description=template.description,
            columns=template.columns,
            atsSafe=template.ats_safe,
            isDefault=template.is_default,
            selected=template.id == current,
            thumbnailUrl=(
                f"/applications/{application_id}/generation/runs/{run_id}"
                f"/templates/{template.id}/thumbnail"
            ),
        )
        for template in list_document_templates()
    ]


# First pages of a run's resume per template. Rendering takes about a second,
# and the gallery asks for every template at once.
_THUMBNAIL_CACHE: OrderedDict[str, bytes] = OrderedDict()
_THUMBNAIL_CACHE_SIZE = 64
_THUMBNAIL_LOCK = Lock()


@router.get("/{application_id}/generation/runs/{run_id}/templates/{template_id}/thumbnail")
def thumbnail_generation_run_template(
    application_id: str,
    run_id: str,
    template_id: str,
    db: Session = Depends(get_db),
) -> Response:
    """PNG of the run's own resume in the given template, for the template picker."""
    try:
        run = get_generation_run(db, application_id=application_id, run_id=run_id)
        content = stored_content(run)
        request = run_request(run.input_snapshot)
        page_limit = resume_page_limit(request)
    except GenerationStoreError as exc:
        raise _store_http_error(exc) from exc
    except (GenerationWorkflowError, GenerationInputError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    if not content.get("resume"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "resume_missing", "message": "This run has no resume to preview"},
        )
    try:
        template = resolve_document_template(template_id, db=db)
        key = hashlib.sha256(
            json.dumps(
                [get_bound_owner_id(), template.id, template.design_sha256, content],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        with _THUMBNAIL_LOCK:
            thumbnail = _THUMBNAIL_CACHE.get(key)
        if thumbnail is None:
            rendered = render_resume_to_fit(
                FinalResume.model_validate(content["resume"]),
                template=template,
                max_pages=page_limit,
                drop_order=content.get("dropOrder") or (),
            )
            thumbnail = render_pdf_first_page_thumbnail(rendered.document.pdf)
            with _THUMBNAIL_LOCK:
                _THUMBNAIL_CACHE[key] = thumbnail
                while len(_THUMBNAIL_CACHE) > _THUMBNAIL_CACHE_SIZE:
                    _THUMBNAIL_CACHE.popitem(last=False)
    except DocumentRenderError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
                if exc.code == "document_template_unsupported"
                else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail={"code": exc.code, "message": str(exc)},
        ) from exc
    except (ResumePdfRenderError, PdfThumbnailRenderError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "preview_unavailable", "message": str(exc)},
        ) from exc
    return Response(
        content=thumbnail,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300", "ETag": f'"{key}"'},
    )


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
            "Content-Disposition": (
                f'{"inline" if artifact.content_type == "application/pdf" else "attachment"}; '
                f'filename="{artifact.file_name}"'
            ),
            "ETag": f'"{artifact.content_sha256}"',
        },
    )


def _workflow_http_error(exc: GenerationWorkflowError) -> HTTPException:
    return HTTPException(
        status_code={
            "run_not_completed": status.HTTP_409_CONFLICT,
            "content_missing": status.HTTP_409_CONFLICT,
            "invalid_snapshot": status.HTTP_409_CONFLICT,
            "document_template_unsupported": status.HTTP_404_NOT_FOUND,
        }.get(exc.code, status.HTTP_503_SERVICE_UNAVAILABLE),
        detail={"code": exc.code, "message": str(exc)},
    )


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
