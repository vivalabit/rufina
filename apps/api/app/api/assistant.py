import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.identity import (
    RequestIdentity,
    bind_request_identity,
    get_bound_owner_id,
    get_request_identity,
)
from app.core.settings import Settings, get_settings
from app.models.applications import (
    StoredApplicationEventRecord,
    StoredApplicationRecord,
)
from app.models.assistant import (
    AppliedAssistantActionRecord,
    AssistantActionApplyRequest,
    AssistantActionApplyResponse,
    AssistantApplicationContext,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantJobContext,
    AssistantSourceDocument,
    AssistantStreamRequest,
)
from app.models.conversations import ConversationRecord, MessageRecord, utc_now
from app.models.documents import (
    DocumentAttachmentRecord,
    DocumentRecord,
    DocumentVersionRecord,
)
from app.models.jobs import StoredJobRecord
from app.models.profile import ProfilePayload
from app.services.ai_backend import ai_backend_provider_name
from app.services.ai_match import build_profile_input_hash
from app.services.ai_privacy import record_ai_activity
from app.services.assistant import (
    AIAssistantRun,
    AssistantAIFacade,
    AssistantError,
    AssistantTimeoutError,
    SourceDocumentPreflightError,
    compact_conversation_history,
    create_assistant_ai_facade,
    encode_message_actions,
    extract_assistant_action_previews,
    preflight_source_documents,
)
from app.services.job_match_store import hydrate_job_data
from app.services.profile_files import enrich_profile_with_files
from app.services.profile_versions import (
    StaleProfileRevisionError,
    create_profile_record,
    get_profile_record,
    update_profile_data,
)

router = APIRouter(dependencies=[Depends(bind_request_identity)])

StreamStatus = Literal["generating", "complete", "error", "stopped"]
STREAM_RETENTION_SECONDS = 600


@dataclass
class AssistantStreamState:
    request_id: str
    fingerprint: str
    owner_id: str
    status: StreamStatus = "generating"
    text: str = ""
    error: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.monotonic)
    updated: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None


@dataclass(frozen=True)
class AuthoritativeAssistantInputs:
    profile: ProfilePayload
    job: AssistantJobContext | None
    application: AssistantApplicationContext | None
    source_documents: tuple[AssistantSourceDocument, ...] = ()


assistant_streams: dict[str, AssistantStreamState] = {}


async def generate_assistant_with_facade(
    *,
    facade: AssistantAIFacade,
    thread_id: str,
    message: str,
    context_kind: str,
    profile: ProfilePayload,
    job: AssistantJobContext | None,
    application: AssistantApplicationContext | None,
    history: dict[str, object] | None = None,
    source_documents: list[AssistantSourceDocument] | None = None,
    session_scope: str = "",
) -> AIAssistantRun:
    return await facade.generate(
        thread_id=thread_id,
        message=message,
        context_kind=context_kind,
        profile=profile,
        job=job,
        application=application,
        history=history,
        source_documents=source_documents,
        session_scope=session_scope,
    )


@router.get("/config")
def get_assistant_config(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "providerName": ai_backend_provider_name(settings.ai_backend_mode),
        "backend": settings.ai_backend_mode,
    }


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    request: AssistantChatRequest,
    _activity=Depends(record_ai_activity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AssistantChatResponse:
    if not settings.openclaw_assistant_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily disabled. Check the server configuration.",
        )
    validate_assistant_message_length(request.message, settings)
    await preflight_assistant_source_documents(request)

    inputs = load_authoritative_assistant_inputs(db, request)
    history = load_compact_conversation_history(db, request.thread_id, settings)

    try:
        run = await generate_assistant_with_facade(
            facade=create_assistant_ai_facade(settings),
            thread_id=request.thread_id,
            message=request.message,
            context_kind=request.context_kind,
            profile=inputs.profile,
            job=inputs.job,
            application=inputs.application,
            history=history,
            source_documents=list(inputs.source_documents),
            session_scope=uuid4().hex,
        )
        message, session_id, metrics, backend_name = unpack_assistant_run(
            run, fallback_backend=settings.ai_backend_mode
        )
    except AssistantTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except AssistantError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    visible_message, actions = extract_assistant_action_previews(
        message,
        request_id=request.thread_id,
        context_kind=request.context_kind,
        context_id=request.context_id,
        profile=inputs.profile,
        job=inputs.job,
        application=inputs.application,
    )
    return AssistantChatResponse(
        message=visible_message,
        source=backend_name,
        metadata={
            "sessionId": session_id,
            "contextKind": request.context_kind,
            "contextId": request.context_id,
            "providerName": ai_backend_provider_name(backend_name),
            "backend": backend_name,
            "metrics": metrics,
            "actions": [action.model_dump(by_alias=True, mode="json") for action in actions],
        },
    )


@router.post("/chat/stream")
async def stream_chat_with_assistant(
    request: AssistantStreamRequest,
    _activity=Depends(record_ai_activity),
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    if not settings.openclaw_assistant_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily disabled. Check the server configuration.",
        )
    validate_assistant_message_length(request.message, settings)
    await preflight_assistant_source_documents(request)

    prune_assistant_streams()
    fingerprint = stream_request_fingerprint(request)
    stream = assistant_streams.get(request.request_id)
    if stream and stream.owner_id != identity.owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assistant stream was not found",
        )
    if stream and stream.fingerprint != fingerprint:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The requestId is already used by another assistant request",
        )

    if not stream and request.offset:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Assistant stream is no longer available for recovery",
        )

    if not stream:
        history = load_compact_conversation_history(db, request.thread_id, settings)
        inputs = load_authoritative_assistant_inputs(db, request)

        stream = AssistantStreamState(
            request_id=request.request_id,
            fingerprint=fingerprint,
            owner_id=identity.owner_id,
        )
        try:
            _, assistant_message_id = prepare_stream_history(db, request)
            history_bind = db.get_bind()
        except HTTPException:
            raise
        except SQLAlchemyError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Conversations database is unavailable",
            ) from exc
        assistant_streams[request.request_id] = stream
        stream.task = asyncio.create_task(
            generate_assistant_stream(
                stream=stream,
                request=request,
                profile=inputs.profile,
                job=inputs.job,
                application=inputs.application,
                source_documents=list(inputs.source_documents),
                facade=create_assistant_ai_facade(settings),
                settings=settings,
                history=history,
                history_bind=history_bind,
                assistant_message_id=assistant_message_id,
            )
        )

    start_offset = min(request.offset, len(stream.text))
    return StreamingResponse(
        iterate_assistant_stream(stream, start_offset),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/chat/stream/{request_id}", status_code=status.HTTP_202_ACCEPTED)
async def stop_chat_stream(
    request_id: str,
    identity: RequestIdentity = Depends(get_request_identity),
) -> dict[str, str]:
    stream = assistant_streams.get(request_id)
    if not stream or stream.owner_id != identity.owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assistant stream was not found",
        )

    if stream.task and not stream.task.done():
        stream.task.cancel()
    if stream.status == "generating":
        update_stream_status(stream, "stopped")
    return {"status": stream.status}


def discard_owner_assistant_streams(owner_id: str) -> int:
    request_ids = [
        request_id
        for request_id, stream in assistant_streams.items()
        if stream.owner_id == owner_id
    ]
    for request_id in request_ids:
        stream = assistant_streams.pop(request_id)
        if stream.task and not stream.task.done():
            stream.task.cancel()
        if stream.status == "generating":
            update_stream_status(stream, "stopped")
    return len(request_ids)


@router.post("/actions/apply", response_model=AssistantActionApplyResponse)
def apply_assistant_action(
    request: AssistantActionApplyRequest,
    db: Session = Depends(get_db),
) -> AssistantActionApplyResponse:
    action = request.action
    try:
        existing = db.get(AppliedAssistantActionRecord, action.id)
        if existing:
            return AssistantActionApplyResponse.model_validate(existing.result)

        response = execute_assistant_action(db, action)
        db.add(
            AppliedAssistantActionRecord(
                id=action.id,
                action_type=action.type,
                result=response.model_dump(by_alias=True, mode="json"),
            )
        )
        db.commit()
        return response
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Assistant action database is unavailable",
        ) from exc


async def generate_assistant_stream(
    *,
    stream: AssistantStreamState,
    request: AssistantStreamRequest,
    profile: ProfilePayload,
    job: AssistantJobContext | None,
    application: AssistantApplicationContext | None,
    source_documents: list[AssistantSourceDocument],
    facade: AssistantAIFacade,
    settings: Settings,
    history: dict[str, object],
    history_bind: Engine | Connection,
    assistant_message_id: str,
) -> None:
    try:
        run = await generate_assistant_with_facade(
            facade=facade,
            thread_id=request.thread_id,
            message=request.message,
            context_kind=request.context_kind,
            profile=profile,
            job=job,
            application=application,
            history=history,
            source_documents=source_documents,
            session_scope=request.request_id,
        )
        message, session_id, metrics, backend_name = unpack_assistant_run(
            run, fallback_backend=settings.ai_backend_mode
        )
        # Deliberately sanitize the complete response before exposing simulated chunks.
        # This prevents TASKO_ACTIONS_JSON from leaking into resumable SSE deltas.
        visible_message, actions = extract_assistant_action_previews(
            message,
            request_id=request.request_id,
            context_kind=request.context_kind,
            context_id=request.context_id,
            profile=profile,
            job=job,
            application=application,
        )
        stream.metadata = {
            "sessionId": session_id,
            "sessionKey": session_id,
            "contextKind": request.context_kind,
            "contextId": request.context_id,
            "providerName": ai_backend_provider_name(backend_name),
            "backend": backend_name,
            "metrics": metrics,
            "actions": [action.model_dump(by_alias=True, mode="json") for action in actions],
        }
        for chunk in split_stream_text(visible_message):
            stream.text += chunk
            touch_stream(stream)
            await asyncio.sleep(0.035)
        persist_stream_history(
            history_bind,
            conversation_id=request.thread_id,
            assistant_message_id=assistant_message_id,
            text=encode_message_actions(stream.text, actions),
            message_status="complete",
            source=backend_name,
            provider_session_id=session_id,
        )
        update_stream_status(stream, "complete")
    except asyncio.CancelledError:
        persist_stream_history_safely(
            history_bind,
            conversation_id=request.thread_id,
            assistant_message_id=assistant_message_id,
            text=stream.text,
            message_status="stopped",
            source=settings.ai_backend_mode if stream.text else None,
        )
        update_stream_status(stream, "stopped")
    except AssistantTimeoutError as exc:
        stream.error = str(exc)
        persist_stream_history_safely(
            history_bind,
            conversation_id=request.thread_id,
            assistant_message_id=assistant_message_id,
            text=stream.text,
            message_status="error",
        )
        update_stream_status(stream, "error")
    except AssistantError as exc:
        stream.error = str(exc)
        persist_stream_history_safely(
            history_bind,
            conversation_id=request.thread_id,
            assistant_message_id=assistant_message_id,
            text=stream.text,
            message_status="error",
        )
        update_stream_status(stream, "error")
    except Exception:
        stream.error = "Assistant generation failed"
        persist_stream_history_safely(
            history_bind,
            conversation_id=request.thread_id,
            assistant_message_id=assistant_message_id,
            text=stream.text,
            message_status="error",
        )
        update_stream_status(stream, "error")


async def iterate_assistant_stream(stream: AssistantStreamState, offset: int):
    cursor = offset
    yield format_sse_event(
        "connected",
        {"requestId": stream.request_id, "offset": cursor},
        event_id=cursor,
    )

    while True:
        stream.updated.clear()
        if len(stream.text) > cursor:
            delta = stream.text[cursor:]
            cursor = len(stream.text)
            yield format_sse_event(
                "delta",
                {"text": delta, "offset": cursor},
                event_id=cursor,
            )

        if stream.status == "complete":
            yield format_sse_event(
                "done",
                {"offset": cursor, "metadata": stream.metadata},
                event_id=cursor,
            )
            return
        if stream.status == "error":
            yield format_sse_event(
                "error",
                {"message": stream.error or "Assistant generation failed", "offset": cursor},
                event_id=cursor,
            )
            return
        if stream.status == "stopped":
            yield format_sse_event("stopped", {"offset": cursor}, event_id=cursor)
            return

        try:
            await asyncio.wait_for(stream.updated.wait(), timeout=10)
        except TimeoutError:
            yield ": keep-alive\n\n"


def split_stream_text(text: str, target_chars: int = 32) -> list[str]:
    parts = re.findall(r"\S+\s*|\s+", text)
    chunks: list[str] = []
    current = ""
    for part in parts:
        current += part
        if len(current) >= target_chars or "\n" in part:
            chunks.append(current)
            current = ""
    if current:
        chunks.append(current)
    return chunks or [text]


def format_sse_event(event: str, payload: dict[str, object], *, event_id: int) -> str:
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"id: {event_id}\nevent: {event}\ndata: {data}\n\n"


def stream_request_fingerprint(request: AssistantStreamRequest) -> str:
    excluded = {"offset", "job", "application"}
    payload = request.model_dump(by_alias=True, exclude=excluded)
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def touch_stream(stream: AssistantStreamState) -> None:
    stream.updated_at = time.monotonic()
    stream.updated.set()


def update_stream_status(stream: AssistantStreamState, status_value: StreamStatus) -> None:
    stream.status = status_value
    touch_stream(stream)


def prune_assistant_streams() -> None:
    cutoff = time.monotonic() - STREAM_RETENTION_SECONDS
    expired = [
        request_id
        for request_id, stream in assistant_streams.items()
        if stream.status != "generating" and stream.updated_at < cutoff
    ]
    for request_id in expired:
        assistant_streams.pop(request_id, None)


def prepare_stream_history(
    db: Session,
    request: AssistantStreamRequest,
) -> tuple[str, str]:
    now = utc_now()
    conversation = db.get(ConversationRecord, request.thread_id)
    if not conversation:
        conversation = ConversationRecord(
            id=request.thread_id,
            title=request.conversation_title or create_conversation_title(request.message),
            context_kind=request.context_kind,
            context_id=request.context_id,
            created_at=now,
            updated_at=now,
        )
        db.add(conversation)
        db.flush()
    else:
        conversation.context_kind = request.context_kind
        conversation.context_id = request.context_id
        conversation.archived = False
        conversation.updated_at = now

    user_message_id = request.user_message_id or stream_message_id(request.request_id, "user")
    assistant_message_id = request.assistant_message_id or stream_message_id(
        request.request_id,
        "assistant",
    )
    current_sequence = db.scalar(
        select(func.max(MessageRecord.sequence)).where(
            MessageRecord.conversation_id == request.thread_id
        )
    )
    next_sequence = (current_sequence if current_sequence is not None else -1) + 1

    ensure_stream_message_id_available(db, user_message_id, request.thread_id)
    ensure_stream_message_id_available(db, assistant_message_id, request.thread_id)
    if not db.get(MessageRecord, user_message_id):
        db.add(
            MessageRecord(
                id=user_message_id,
                conversation_id=request.thread_id,
                sequence=next_sequence,
                role="user",
                content=request.message,
                status="complete",
                created_at=now,
            )
        )
        next_sequence += 1
    if not db.get(MessageRecord, assistant_message_id):
        db.add(
            MessageRecord(
                id=assistant_message_id,
                conversation_id=request.thread_id,
                sequence=next_sequence,
                role="assistant",
                content="",
                status="generating",
                created_at=now,
            )
        )
    db.commit()
    return user_message_id, assistant_message_id


def ensure_stream_message_id_available(
    db: Session,
    message_id: str,
    conversation_id: str,
) -> None:
    message = db.get(MessageRecord, message_id)
    if message and message.conversation_id != conversation_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Message id already belongs to another conversation",
        )


def persist_stream_history(
    bind: Engine | Connection,
    *,
    conversation_id: str,
    assistant_message_id: str,
    text: str,
    message_status: str,
    source: str | None = None,
    provider_session_id: str | None = None,
) -> None:
    with Session(bind=bind) as db:
        conversation = db.get(ConversationRecord, conversation_id)
        message = db.get(MessageRecord, assistant_message_id)
        if not conversation or not message:
            raise RuntimeError("Assistant conversation disappeared while generating")
        if message_status == "stopped" and not text:
            db.delete(message)
        else:
            message.content = text
            message.status = message_status
            message.source = source
        if provider_session_id:
            conversation.provider_session_id = provider_session_id
        conversation.updated_at = utc_now()
        db.commit()


def persist_stream_history_safely(
    bind: Engine | Connection,
    *,
    conversation_id: str,
    assistant_message_id: str,
    text: str,
    message_status: str,
    source: str | None = None,
    provider_session_id: str | None = None,
) -> None:
    try:
        persist_stream_history(
            bind,
            conversation_id=conversation_id,
            assistant_message_id=assistant_message_id,
            text=text,
            message_status=message_status,
            source=source,
            provider_session_id=provider_session_id,
        )
    except Exception:
        pass


def stream_message_id(request_id: str, role: str) -> str:
    digest = hashlib.sha256(f"{request_id}:{role}".encode()).hexdigest()[:32]
    return f"assistant-{role}-{digest}"


def create_conversation_title(message: str) -> str:
    normalized = " ".join(message.split())
    return f"{normalized[:42].rstrip()}…" if len(normalized) > 42 else normalized


def validate_assistant_message_length(
    message: str,
    settings: Settings,
) -> None:
    limit = settings.openclaw_assistant_max_user_message_chars
    if len(message) > limit:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Message is too long ({len(message):,} characters). The limit is {limit:,}.",
        )


async def preflight_assistant_source_documents(request: AssistantChatRequest) -> None:
    try:
        await asyncio.to_thread(preflight_source_documents, request.source_documents)
    except SourceDocumentPreflightError as exc:
        raise HTTPException(
            status_code=(
                status.HTTP_413_CONTENT_TOO_LARGE
                if exc.limit_exceeded
                else status.HTTP_422_UNPROCESSABLE_CONTENT
            ),
            detail=exc.as_detail(),
        ) from exc


def load_compact_conversation_history(
    db: Session,
    conversation_id: str,
    settings: Settings,
) -> dict[str, object]:
    try:
        records = (
            db.query(MessageRecord)
            .filter(
                MessageRecord.conversation_id == conversation_id,
                MessageRecord.status.in_(("complete", "stopped")),
            )
            .order_by(MessageRecord.sequence)
            .all()
        )
    except SQLAlchemyError:
        return {}
    return compact_conversation_history(
        [{"role": record.role, "content": record.content} for record in records],
        max_messages=settings.openclaw_assistant_max_history_messages,
        max_chars=settings.openclaw_assistant_max_history_chars,
    )


def unpack_assistant_run(
    run: AIAssistantRun | tuple[str, str],
    *,
    fallback_backend: str = "openclaw_codex",
) -> tuple[str, str, dict[str, object], str]:
    message, session_key = run
    metrics = run.metrics.as_dict() if isinstance(run, AIAssistantRun) else {}
    backend = run.backend if isinstance(run, AIAssistantRun) else fallback_backend
    return message, session_key, metrics, backend


def load_profile(db: Session) -> ProfilePayload:
    try:
        record = get_profile_record(db)
        profile = ProfilePayload.model_validate(record.data) if record else ProfilePayload()
        return enrich_profile_with_files(db, profile)
    except (SQLAlchemyError, ValidationError):
        return ProfilePayload()


def load_authoritative_assistant_inputs(
    db: Session,
    request: AssistantChatRequest,
) -> AuthoritativeAssistantInputs:
    profile = load_profile(db)
    if request.context_kind == "job":
        job = load_server_job_context(db, request.context_id, profile)
        return AuthoritativeAssistantInputs(
            profile=profile,
            job=job,
            application=None,
            source_documents=tuple(request.source_documents),
        )
    if request.context_kind == "application":
        application = load_server_application_context(db, request.context_id, profile)
        return AuthoritativeAssistantInputs(
            profile=profile,
            job=application.job,
            application=application,
            source_documents=tuple(request.source_documents),
        )
    return AuthoritativeAssistantInputs(
        profile=profile,
        job=None,
        application=None,
        source_documents=tuple(request.source_documents),
    )


def load_server_job_context(
    db: Session,
    job_id: str,
    profile: ProfilePayload,
) -> AssistantJobContext | None:
    if not job_id:
        return None

    try:
        record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
        if not record or not isinstance(record.data, dict):
            return None
        job_data = hydrate_job_data(
            db,
            job_id=job_id,
            job_data={**record.data, "id": job_id},
            profile_hash=build_profile_input_hash(profile),
        )
        return AssistantJobContext.model_validate(job_data)
    except (SQLAlchemyError, ValidationError):
        return None


def load_server_application_context(
    db: Session,
    application_id: str,
    profile: ProfilePayload,
) -> AssistantApplicationContext:
    try:
        record = db.get(StoredApplicationRecord, application_id) if application_id else None
        if not record or not isinstance(record.data, dict):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Application not found"
            )
        raw_job = record.data.get("job")
        job_id = str(raw_job.get("id") or "").strip() if isinstance(raw_job, dict) else ""
        job = load_server_job_context(db, job_id, profile)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored application vacancy is unavailable",
            )
        application_data = dict(record.data)
        application_data["id"] = application_id
        application_data["job"] = job.model_dump(by_alias=True)
        return AssistantApplicationContext.model_validate(application_data)
    except HTTPException:
        raise
    except (SQLAlchemyError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative application context is unavailable",
        ) from exc


PROFILE_ACTION_FIELDS = {
    "name",
    "current_role",
    "desired_role",
    "location",
    "work_format",
    "headline",
    "linkedin",
    "github",
    "portfolio",
    "personal_site",
    "experience",
    "skills",
    "education",
    "job_preferences",
    "dealbreakers",
    "additional_notes",
}


def execute_assistant_action(db: Session, action) -> AssistantActionApplyResponse:
    payload = action.payload

    if action.type in {
        "add_application_note",
        "update_application_next_step",
        "create_interview_event",
    }:
        application_id = payload_string(payload, "applicationId", max_length=160)
        if action.context_kind != "application" or action.context_id != application_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The application context changed; request a new preview",
            )
        application = require_stored_application(db, application_id)
        application_data = dict(application.data)
        application_data.pop("documents", None)
        if application_data != application.data:
            application.data = application_data

        if action.type == "add_application_note":
            note = payload_string(payload, "note", max_length=4_000)
            current_notes = str(application_data.get("notes", "")).strip()
            application_data["notes"] = "\n".join(value for value in (current_notes, note) if value)
            application.data = application_data
            return action_response(
                action,
                message="Application note added",
                resource_kind="application",
                resource=application_data,
            )

        if action.type == "update_application_next_step":
            next_step = payload_string(payload, "nextStep", max_length=500)
            expected = payload_string(
                payload,
                "expectedValue",
                max_length=500,
                allow_empty=True,
            )
            current = str(application_data.get("nextStep", ""))
            require_unchanged(current, expected)
            application_data["nextStep"] = next_step
            application.data = application_data
            return action_response(
                action,
                message="Application next step updated",
                resource_kind="application",
                resource=application_data,
            )

        starts_at = payload_string(payload, "startsAt", max_length=80)
        try:
            parsed_start = datetime.fromisoformat(starts_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Interview start time is invalid",
            ) from exc
        if parsed_start.tzinfo is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Interview start time must include a timezone",
            )
        duration = payload.get("durationMinutes", 45)
        if not isinstance(duration, int) or isinstance(duration, bool) or not 5 <= duration <= 480:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Interview duration is invalid",
            )
        event_id = f"assistant-event-{action.id.removeprefix('assistant-action-')}"
        event_data = {
            "id": event_id,
            "applicationId": application_id,
            "type": "interview",
            "status": "scheduled",
            "title": payload_string(payload, "title", max_length=240),
            "startsAt": parsed_start.isoformat(),
            "durationMinutes": duration,
            "timezone": payload_string(payload, "timezone", max_length=120),
            "location": payload_string(
                payload,
                "location",
                max_length=500,
                allow_empty=True,
            ),
            "notes": payload_string(
                payload,
                "notes",
                max_length=4_000,
                allow_empty=True,
            ),
        }
        db.add(
            StoredApplicationEventRecord(
                id=event_id,
                application_id=application_id,
                data=event_data,
            )
        )
        return action_response(
            action,
            message="Interview event created",
            resource_kind="event",
            resource=event_data,
        )

    if action.type == "save_document":
        document_type = payload_string(payload, "documentType", max_length=32)
        if document_type != "cover_letter":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document type is invalid",
            )
        application_id = payload_string(
            payload,
            "applicationId",
            max_length=160,
            allow_empty=True,
        )
        job_id = payload_string(payload, "jobId", max_length=160, allow_empty=True)
        if action.context_kind == "application" and action.context_id != application_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The application context changed; request a new preview",
            )
        if action.context_kind == "job" and action.context_id != job_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The vacancy context changed; request a new preview",
            )
        if application_id:
            require_stored_application(db, application_id)
        now = utc_now()
        document_id = str(uuid4())
        document = DocumentRecord(
            id=document_id,
            type=document_type,
            title=payload_string(payload, "title", max_length=240),
            job_id=job_id or None,
            current_version=1,
            created_at=now,
            updated_at=now,
        )
        document.versions.append(
            DocumentVersionRecord(
                id=str(uuid4()),
                document_id=document_id,
                version=1,
                content=payload_string(payload, "content", max_length=200_000),
                created_at=now,
            )
        )
        if application_id:
            document.attachments.append(
                DocumentAttachmentRecord(
                    id=str(uuid4()),
                    document_id=document_id,
                    application_id=application_id,
                    created_at=now,
                )
            )
        db.add(document)
        db.flush()
        resource = {
            "id": document.id,
            "type": document.type,
            "title": document.title,
            "jobId": document.job_id,
            "applicationIds": [application_id] if application_id else [],
            "currentVersion": 1,
            "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(),
            "versions": [
                {
                    "id": document.versions[0].id,
                    "version": 1,
                    "content": document.versions[0].content,
                    "createdAt": now.isoformat(),
                }
            ],
        }
        return action_response(
            action,
            message="Document saved",
            resource_kind="document",
            resource=resource,
        )

    if action.type == "update_profile_field":
        field_name = payload_string(payload, "field", max_length=80)
        if field_name not in PROFILE_ACTION_FIELDS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Profile field cannot be changed by the assistant",
            )
        value = payload_string(payload, "value", max_length=12_000, allow_empty=True)
        expected = payload_string(
            payload,
            "expectedValue",
            max_length=12_000,
            allow_empty=True,
        )
        profile_record = get_profile_record(db)
        profile = (
            ProfilePayload.model_validate(profile_record.data)
            if profile_record
            else ProfilePayload()
        )
        current = str(getattr(profile, field_name))
        require_unchanged(current, expected)
        updated_data = profile.model_dump()
        updated_data[field_name] = value
        try:
            updated_profile = ProfilePayload.model_validate(updated_data)
        except ValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Profile field value is invalid",
            ) from exc
        if profile_record:
            try:
                update_profile_data(
                    db,
                    profile_record,
                    data=updated_profile.model_dump(),
                    reason="assistant_action",
                )
            except StaleProfileRevisionError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Profile changed before the assistant action was applied",
                ) from exc
        else:
            db.add(create_profile_record(updated_profile.model_dump()))
        return action_response(
            action,
            message=f"Profile field {field_name.replace('_', ' ')} updated",
            resource_kind="profile",
            resource=updated_profile.model_dump(),
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Assistant action type is not supported",
    )


def require_stored_application(db: Session, application_id: str) -> StoredApplicationRecord:
    record = db.get(StoredApplicationRecord, application_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Application not found",
        )
    return record


def payload_string(
    payload: dict[str, object],
    key: str,
    *,
    max_length: int,
    allow_empty: bool = False,
) -> str:
    value = payload.get(key)
    if (
        not isinstance(value, str)
        or len(value) > max_length
        or (not allow_empty and not value.strip())
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Assistant action field {key} is invalid",
        )
    return value.strip()


def require_unchanged(current: str, expected: str) -> None:
    if current != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The data changed after this preview was created; request a new preview",
        )


def action_response(
    action,
    *,
    message: str,
    resource_kind: str,
    resource: dict[str, object],
) -> AssistantActionApplyResponse:
    return AssistantActionApplyResponse(
        actionId=action.id,
        type=action.type,
        message=message,
        resourceKind=resource_kind,
        resource=resource,
    )
