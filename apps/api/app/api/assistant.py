import asyncio
import base64
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.core.database import get_db
from app.core.identity import (
    RequestIdentity,
    bind_request_identity,
    get_bound_owner_id,
    get_request_identity,
)
from app.core.settings import Settings, get_settings
from app.models.applications import (
    CandidateConfirmationRecord,
    StoredApplicationEventRecord,
    StoredApplicationRecord,
)
from app.models.assistant import (
    AppliedAssistantActionRecord,
    AssistantActionApplyRequest,
    AssistantActionApplyResponse,
    AssistantApplicationContext,
    AssistantCandidateConfirmation,
    AssistantChatRequest,
    AssistantChatResponse,
    AssistantJobContext,
    AssistantSourceDocument,
    AssistantStreamRequest,
)
from app.models.conversations import ConversationRecord, MessageRecord, utc_now
from app.models.documents import (
    DocumentAttachmentRecord,
    DocumentGenerationArtifactRecord,
    DocumentRecord,
    DocumentVersionRecord,
)
from app.models.jobs import StoredJobRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.ai_backend import ai_backend_provider_name
from app.services.ai_privacy import require_current_ai_consent
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
from app.services.generation_context import (
    AuthoritativeGenerationContext,
    GenerationContextError,
    clarification_questions,
    load_authoritative_generation_context,
)
from app.services.document_export import ensure_cover_letter_date_replacement
from app.services.job_match_store import (
    latest_job_match_record,
    match_record_to_ai_match,
)
from app.services.profile_versions import record_profile_version

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
    confirmations: tuple[AssistantCandidateConfirmation, ...] = ()
    generation_context: AuthoritativeGenerationContext | None = None


assistant_streams: dict[str, AssistantStreamState] = {}
GENERATION_ARTIFACT_TTL = timedelta(minutes=30)
GENERATION_MESSAGE_MAX_CHARS = 12_000


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
    candidate_confirmations: list[AssistantCandidateConfirmation] | None = None,
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
        candidate_confirmations=candidate_confirmations,
        session_scope=session_scope,
    )


def begin_generation_artifact(
    db: Session,
    *,
    context: AuthoritativeGenerationContext,
    prompt: str,
    history: dict[str, object],
    settings: Settings,
) -> DocumentGenerationArtifactRecord:
    provenance = context.provenance()
    now = utc_now()
    artifact_id = str(uuid4())
    snapshot = context.input_snapshot(prompt=prompt)
    snapshot["assistant"] = {
        "model": (
            settings.openai_api_model
            if settings.ai_backend_mode == "openai_api"
            else settings.openclaw_assistant_model
        ),
        "backend": settings.ai_backend_mode,
        "providerName": ai_backend_provider_name(settings.ai_backend_mode),
        "thinking": settings.ai_reasoning_for(settings.openclaw_assistant_thinking),
        "agentId": settings.openclaw_assistant_agent_id,
        "history": history,
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(
            snapshot,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    input_versions = {
        **provenance.input_versions,
        "generationArtifact": {
            "id": artifact_id,
            "inputSnapshotSha256": snapshot_hash,
            "model": (
                settings.openai_api_model
                if settings.ai_backend_mode == "openai_api"
                else settings.openclaw_assistant_model
            ),
            "backend": provenance.generation_backend,
            "providerName": ai_backend_provider_name(provenance.generation_backend),
        },
    }
    artifact = DocumentGenerationArtifactRecord(
        id=artifact_id,
        application_id=context.application_id,
        job_id=context.job_id,
        document_type=context.template.type,
        template_id=context.template.id,
        template_content=context.template.content,
        input_snapshot=snapshot,
        generation_fingerprint=provenance.generation_fingerprint,
        input_versions=input_versions,
        validation_evidence=context.validation_evidence(),
        status="generating",
        result_content=None,
        generation_model=None,
        generation_backend=provenance.generation_backend,
        consumed_at=None,
        expires_at=now + GENERATION_ARTIFACT_TTL,
        created_at=now,
        completed_at=None,
    )
    db.add(artifact)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation artifact could not be created",
        ) from exc
    return artifact


def complete_generation_artifact(
    db: Session,
    artifact: DocumentGenerationArtifactRecord,
    *,
    content: str,
    model: str,
    backend: str,
) -> None:
    if not content.strip():
        fail_generation_artifact(db, artifact)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an empty generated document",
        )
    if backend != artifact.generation_backend:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI generation backend did not match the requested backend",
        )
    artifact.status = "completed"
    artifact.result_content = content
    artifact.generation_model = model.strip() or "unknown"
    artifact.completed_at = utc_now()
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Generation artifact could not be completed",
        ) from exc


def fail_generation_artifact(
    db: Session,
    artifact: DocumentGenerationArtifactRecord | None,
) -> None:
    if artifact is None:
        return
    artifact.status = "failed"
    artifact.completed_at = utc_now()
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()


@router.get("/config")
def get_assistant_config(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    return {
        "providerName": ai_backend_provider_name(settings.ai_backend_mode),
        "backend": settings.ai_backend_mode,
        "consentVersion": settings.ai_consent_version,
    }


@router.post("/chat", response_model=AssistantChatResponse)
async def chat_with_assistant(
    request: AssistantChatRequest,
    _consent=Depends(require_current_ai_consent),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> AssistantChatResponse:
    if not settings.openclaw_assistant_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily disabled. Check the server configuration.",
        )
    if (
        request.generation_context is not None
        and request.generation_context.document_type == "tailored_resume"
    ):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy assistant-based DOCX resume tailoring was removed; "
                "use the three-stage resume-tailoring API"
            ),
        )
    validate_assistant_message_length(
        request.message,
        settings,
        is_document_generation=request.generation_context is not None,
    )
    if request.generation_context is None:
        await preflight_assistant_source_documents(request)

    inputs = load_authoritative_assistant_inputs(
        db,
        request,
        generation_backend=settings.ai_backend_mode,
    )
    history = load_compact_conversation_history(db, request.thread_id, settings)
    generation_artifact = None
    if inputs.generation_context is not None:
        generation_artifact = begin_generation_artifact(
            db,
            context=inputs.generation_context,
            prompt=request.message,
            history=history,
            settings=settings,
        )

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
            candidate_confirmations=list(inputs.confirmations),
            session_scope=uuid4().hex,
        )
        message, session_id, metrics, backend_name = unpack_assistant_run(
            run, fallback_backend=settings.ai_backend_mode
        )
    except AssistantTimeoutError as exc:
        fail_generation_artifact(db, generation_artifact)
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=str(exc),
        ) from exc
    except AssistantError as exc:
        fail_generation_artifact(db, generation_artifact)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    try:
        visible_message, actions = extract_assistant_action_previews(
            message,
            request_id=request.thread_id,
            context_kind=request.context_kind,
            context_id=request.context_id,
            profile=inputs.profile,
            job=inputs.job,
            application=inputs.application,
        )
        if (
            inputs.generation_context is not None
            and inputs.generation_context.template.type == "cover_letter"
        ):
            visible_message = ensure_cover_letter_date_replacement(
                template_content=inputs.generation_context.template.content,
                content=visible_message,
                generation_date=inputs.generation_context.generation_date,
                language=inputs.generation_context.language,
            )
        if generation_artifact is not None:
            complete_generation_artifact(
                db,
                generation_artifact,
                content=visible_message,
                model=str(
                    metrics.get("model")
                    or (
                        settings.openai_api_model
                        if settings.ai_backend_mode == "openai_api"
                        else settings.openclaw_assistant_model
                    )
                ),
                backend=backend_name,
            )
    except HTTPException:
        if generation_artifact is not None and generation_artifact.status != "failed":
            fail_generation_artifact(db, generation_artifact)
        raise
    except Exception:
        fail_generation_artifact(db, generation_artifact)
        raise
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
            **(
                {"generationArtifactId": generation_artifact.id}
                if generation_artifact is not None
                else {}
            ),
            "actions": [action.model_dump(by_alias=True, mode="json") for action in actions],
        },
    )


@router.post("/chat/stream")
async def stream_chat_with_assistant(
    request: AssistantStreamRequest,
    _consent=Depends(require_current_ai_consent),
    identity: RequestIdentity = Depends(get_request_identity),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    if not settings.openclaw_assistant_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The assistant is temporarily disabled. Check the server configuration.",
        )
    if request.generation_context is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Document generation must use the artifact-producing chat endpoint",
        )
    validate_assistant_message_length(request.message, settings)
    if request.generation_context is None:
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
        inputs = load_authoritative_assistant_inputs(
            db,
            request,
            generation_backend=settings.ai_backend_mode,
        )

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
                candidate_confirmations=list(inputs.confirmations),
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
    candidate_confirmations: list[AssistantCandidateConfirmation],
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
            candidate_confirmations=candidate_confirmations,
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
    excluded = {"offset", "job", "application", "candidate_confirmations"}
    if request.generation_context is not None:
        excluded.add("source_documents")
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
    *,
    is_document_generation: bool = False,
) -> None:
    limit = (
        GENERATION_MESSAGE_MAX_CHARS
        if is_document_generation
        else settings.openclaw_assistant_max_user_message_chars
    )
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
        record = db.get(ProfileRecord, "default")
        return ProfilePayload.model_validate(record.data) if record else ProfilePayload()
    except (SQLAlchemyError, ValidationError):
        return ProfilePayload()


def load_authoritative_assistant_inputs(
    db: Session,
    request: AssistantChatRequest,
    *,
    generation_backend: str | None = None,
) -> AuthoritativeAssistantInputs:
    if request.generation_context is not None:
        reference = request.generation_context
        if (
            request.context_kind != "application"
            or request.context_id != reference.application_id
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="Generation context must match the application assistant context",
            )
        try:
            context = load_authoritative_generation_context(
                db,
                application_id=reference.application_id,
                template_id=reference.template_id,
                document_type=reference.document_type,
                generation_backend=generation_backend,
            )
        except GenerationContextError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
        return assistant_inputs_from_generation_context(context)

    profile = load_profile(db)
    if request.context_kind == "job":
        job = load_server_job_context(db, request.context_id)
        return AuthoritativeAssistantInputs(
            profile=profile,
            job=job,
            application=None,
            source_documents=tuple(request.source_documents),
        )
    if request.context_kind == "application":
        application, guide = load_server_application_context(db, request.context_id)
        return AuthoritativeAssistantInputs(
            profile=profile,
            job=application.job,
            application=application,
            source_documents=tuple(request.source_documents),
            confirmations=load_saved_assistant_confirmations(
                db,
                application_id=application.id,
                application_guide=guide,
            ),
        )
    return AuthoritativeAssistantInputs(
        profile=profile,
        job=None,
        application=None,
        source_documents=tuple(request.source_documents),
    )


def assistant_inputs_from_generation_context(
    context: AuthoritativeGenerationContext,
) -> AuthoritativeAssistantInputs:
    profile = ProfilePayload.model_validate(context.profile)
    job_data = dict(context.vacancy)
    if context.template.type != "cover_letter":
        job_data["aiMatch"] = {"applicationGuide": context.application_guide}
    job = AssistantJobContext.model_validate(job_data)
    application_data = (
        {"id": context.application_id}
        if context.template.type == "cover_letter"
        else dict(context.application)
    )
    application_data["job"] = job.model_dump(by_alias=True)
    application_data["generationDate"] = context.generation_date
    application = AssistantApplicationContext.model_validate(application_data)
    confirmations = tuple(
        AssistantCandidateConfirmation(
            questionId=confirmation.question_id,
            requirement=confirmation.requirement,
            question=confirmation.question,
            answer=(
                confirmation.response.upper()
                + (f": {confirmation.example_text}" if confirmation.example_text else "")
            ),
        )
        for confirmation in context.confirmations
        if context.template.type != "cover_letter"
        or confirmation.question_id
        in {
            "cover-letter-recipient-name",
            "cover-letter-company-contact",
            "cover-letter-additional-context",
        }
    )
    encoded_template = base64.b64encode(context.template.content).decode("ascii")
    source_document = AssistantSourceDocument(
        id=context.template.id,
        title=context.template.name,
        category=(
            "Cover Letter"
            if context.template.type == "cover_letter"
            else "CV / Resume"
        ),
        fileName=context.template.file_name,
        dataUrl=f"data:{context.template.content_type};base64,{encoded_template}",
    )
    return AuthoritativeAssistantInputs(
        profile=profile,
        job=job,
        application=application,
            source_documents=(source_document,),
            confirmations=confirmations,
            generation_context=context,
        )


def load_server_job_context(
    db: Session,
    job_id: str,
) -> AssistantJobContext | None:
    if not job_id:
        return None

    try:
        record = db.get(StoredJobRecord, (get_bound_owner_id(), job_id))
        if not record or not isinstance(record.data, dict):
            return None
        job_data = dict(record.data)
        job_data["id"] = job_id
        job_data.pop("aiMatch", None)
        match_record = latest_job_match_record(db, job_id=job_id)
        if match_record:
            job_data["aiMatch"] = match_record_to_ai_match(match_record)
        return AssistantJobContext.model_validate(job_data)
    except (SQLAlchemyError, ValidationError):
        return None


def load_server_application_context(
    db: Session,
    application_id: str,
) -> tuple[AssistantApplicationContext, dict[str, object]]:
    try:
        record = db.get(StoredApplicationRecord, application_id) if application_id else None
        if not record or not isinstance(record.data, dict):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found")
        raw_job = record.data.get("job")
        job_id = str(raw_job.get("id") or "").strip() if isinstance(raw_job, dict) else ""
        job = load_server_job_context(db, job_id)
        if job is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stored application vacancy is unavailable",
            )
        application_data = dict(record.data)
        application_data["id"] = application_id
        application_data["job"] = job.model_dump(by_alias=True)
        guide = job.ai_match.application_guide if job.ai_match else None
        return (
            AssistantApplicationContext.model_validate(application_data),
            guide if isinstance(guide, dict) else {},
        )
    except HTTPException:
        raise
    except (SQLAlchemyError, ValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authoritative application context is unavailable",
        ) from exc


def load_saved_assistant_confirmations(
    db: Session,
    *,
    application_id: str,
    application_guide: dict[str, object],
) -> tuple[AssistantCandidateConfirmation, ...]:
    questions = {question.question_id: question for question in clarification_questions(application_guide)}
    try:
        records = (
            db.query(CandidateConfirmationRecord)
            .filter(CandidateConfirmationRecord.application_id == application_id)
            .all()
        )
    except SQLAlchemyError:
        return ()
    confirmations: list[AssistantCandidateConfirmation] = []
    for record in records:
        question = questions.get(record.question_id)
        if question is None or record.response not in {"yes", "no", "partial"}:
            continue
        confirmations.append(
            AssistantCandidateConfirmation(
                questionId=question.question_id,
                requirement=question.requirement,
                question=question.question,
                why=question.why,
                claimIfConfirmed=question.claim_if_confirmed,
                answer=(
                    record.response.upper()
                    + (f": {record.example_text.strip()}" if record.example_text.strip() else "")
                ),
            )
        )
    return tuple(confirmations)


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

        if action.type == "add_application_note":
            note = payload_string(payload, "note", max_length=4_000)
            application_data = dict(application.data)
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
            application_data = dict(application.data)
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
        if document_type not in {"cover_letter", "tailored_resume"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document type is invalid",
            )
        if document_type == "tailored_resume":
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail=(
                    "Legacy assistant resume saves were removed; only server-rendered "
                    "FinalResume PDF artifacts can be saved"
                ),
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
        profile_record = db.get(ProfileRecord, "default")
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
            record_profile_version(db, profile_record, reason="assistant_action")
            profile_record.data = updated_profile.model_dump()
        else:
            db.add(ProfileRecord(id="default", data=updated_profile.model_dump()))
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
