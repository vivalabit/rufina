from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models.generation_runs import ApplicationGenerationRunRecord
from app.models.generation_workflow import (
    DraftBundle,
    FitEvaluation,
    ReviewedDraftBundle,
    ReviewerFeedback,
)
from app.models.resume import MasterResume
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    AIResult,
    create_ai_backend,
    generate_with_retries,
)
from app.services.generation_grounding import validate_grounded_bundle
from app.services.generation_resources import load_instruction
from app.services.generation_snapshot import GenerationRunSnapshot
from app.services.generation_store import (
    GenerationStoreError,
    append_run_message,
    persist_run_artifact,
    transition_generation_run,
)


class GenerationWorkflowError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GenerationWorkflow:
    def __init__(self, *, settings: Any, backend: AIBackend | None = None) -> None:
        self.settings = settings
        self.backend_override = backend

    def evaluate_fit(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
    ) -> FitEvaluation:
        self._require_state(run, "queued")
        snapshot = _run_snapshot(run)
        transition_generation_run(
            db,
            run=run,
            status="running",
            stage="fit",
            event_kind="fit.started",
        )
        try:
            evaluation = self._request_model(
                db,
                run,
                actor="reviewer",
                session_suffix="fit",
                instruction_name="evaluate",
                context={
                    "vacancy": snapshot.request.vacancy.model_dump(mode="json", by_alias=True),
                    "masterResume": snapshot.request.master_profile_version.data,
                    "language": snapshot.request.language,
                },
                response_model=FitEvaluation,
            )
            persist_run_artifact(
                db,
                run=run,
                artifact_type="fit_evaluation_json",
                file_name="fit-evaluation.json",
                content_type="application/json",
                content=_json_bytes(evaluation),
                metadata={"stage": "fit"},
            )
            transition_generation_run(
                db,
                run=run,
                status="awaiting_approval",
                stage="fit",
                event_kind="fit.completed",
                event_data={
                    "overallScore": evaluation.overall_score,
                    "recommendation": evaluation.recommendation,
                },
                pending_question={
                    "id": "continue_after_fit",
                    "kind": "approval",
                    "prompt": "Continue with the CV and cover letter?",
                    "choices": ["continue", "stop"],
                },
                result={
                    **run.result,
                    "fit": evaluation.model_dump(mode="json", by_alias=True),
                },
            )
            return evaluation
        except Exception as exc:
            self._fail(db, run, exc)
            raise

    def respond_to_fit(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        *,
        continue_generation: bool,
    ) -> ReviewedDraftBundle | None:
        self._require_state(run, "awaiting_approval")
        if run.pending_question is None or run.pending_question.get("id") != "continue_after_fit":
            raise GenerationWorkflowError(
                "Generation run is not waiting for the fit decision",
                code="question_mismatch",
            )
        append_run_message(
            db,
            run=run,
            actor="user",
            role="user",
            content="continue" if continue_generation else "stop",
        )
        if not continue_generation:
            transition_generation_run(
                db,
                run=run,
                status="cancelled",
                stage="fit",
                event_kind="fit.declined",
            )
            return None
        return self._draft_and_review(db, run)

    def _draft_and_review(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
    ) -> ReviewedDraftBundle:
        snapshot = _run_snapshot(run)
        master_resume = MasterResume.model_validate(snapshot.request.master_profile_version.data)
        target_job_id = snapshot.request.vacancy.id
        transition_generation_run(
            db,
            run=run,
            status="running",
            stage="draft",
            event_kind="draft.started",
        )
        try:
            base_context = {
                "vacancy": snapshot.request.vacancy.model_dump(mode="json", by_alias=True),
                "masterResume": snapshot.request.master_profile_version.data,
                "documentTypes": list(snapshot.request.document_types),
                "formattingParameters": snapshot.request.formatting_parameters,
                "userPreferences": snapshot.request.user_preferences,
            }
            draft = self._request_model(
                db,
                run,
                actor="author",
                session_suffix="author",
                instruction_name="draft",
                context=base_context,
                response_model=DraftBundle,
            )
            _require_requested_documents(draft, run.document_types)
            validate_grounded_bundle(
                draft,
                master_resume=master_resume,
                target_job_id=target_job_id,
            )
            persist_run_artifact(
                db,
                run=run,
                artifact_type="draft_bundle_json",
                file_name="draft-bundle.json",
                content_type="application/json",
                content=_json_bytes(draft),
                metadata={"stage": "draft"},
            )
            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="review",
                event_kind="review.started",
            )

            review = self._request_model(
                db,
                run,
                actor="reviewer",
                session_suffix="reviewer",
                instruction_name="review",
                context={
                    **base_context,
                    "draft": draft.model_dump(mode="json", by_alias=True),
                },
                response_model=ReviewerFeedback,
                enable_web_search=True,
            )
            persist_run_artifact(
                db,
                run=run,
                artifact_type="review_feedback_json",
                file_name="review-feedback.json",
                content_type="application/json",
                content=_json_bytes(review),
                metadata={"stage": "review"},
            )
            final_draft = draft
            if review.findings:
                final_draft = self._request_model(
                    db,
                    run,
                    actor="author",
                    session_suffix="author",
                    instruction_name="draft",
                    context={
                        **base_context,
                        "previousDraft": draft.model_dump(mode="json", by_alias=True),
                        "reviewFeedback": review.model_dump(mode="json", by_alias=True),
                        "task": "Revise the prior draft. Return only the complete DraftBundle.",
                    },
                    response_model=DraftBundle,
                )
            _require_requested_documents(final_draft, run.document_types)
            validate_grounded_bundle(
                final_draft,
                master_resume=master_resume,
                target_job_id=target_job_id,
            )
            persist_run_artifact(
                db,
                run=run,
                artifact_type="reviewed_draft_bundle_json",
                file_name="reviewed-draft-bundle.json",
                content_type="application/json",
                content=_json_bytes(final_draft),
                metadata={"stage": "review"},
            )
            outcome = ReviewedDraftBundle(draft=final_draft, review=review)
            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="pdf_checks",
                event_kind="review.completed",
                event_data={
                    "approved": review.approved,
                    "findingCount": len(review.findings),
                },
                result={
                    **run.result,
                    "review": review.model_dump(mode="json", by_alias=True),
                    "draft": final_draft.model_dump(mode="json", by_alias=True),
                },
            )
            return outcome
        except Exception as exc:
            self._fail(db, run, exc)
            raise

    def _request_model[T: BaseModel](
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        *,
        actor: str,
        session_suffix: str,
        instruction_name: str,
        context: dict[str, Any],
        response_model: type[T],
        enable_web_search: bool = False,
    ) -> T:
        prompt = _build_prompt(instruction_name, context, response_model)
        append_run_message(
            db,
            run=run,
            actor=actor,
            role="user",
            content=prompt,
        )
        result = generate_with_retries(
            self._backend(run),
            AIRequest(
                prompt=prompt,
                model=run.model,
                agent_id=getattr(self.settings, "openclaw_assistant_agent_id", ""),
                thinking=run.reasoning_effort,
                timeout_seconds=int(run.settings_snapshot["timeout_seconds"]),
                session_id=f"application-generation:{run.id}:{session_suffix}",
                structured=True,
                response_model=response_model,
                enable_web_search=enable_web_search,
            ),
            max_attempts=int(run.settings_snapshot["max_attempts"]),
            retry_backoff_seconds=float(run.settings_snapshot["retry_backoff_seconds"]),
        )
        append_run_message(
            db,
            run=run,
            actor=actor,
            role="assistant",
            content=result.text,
            raw_response=result.raw_response,
            response_id=result.session_id or None,
            usage=result.usage.as_dict(),
        )
        return _validated_result(result, response_model)

    def _backend(self, run: ApplicationGenerationRunRecord) -> AIBackend:
        if self.backend_override is not None:
            return self.backend_override
        return create_ai_backend(
            mode=run.backend,
            openclaw_command=self.settings.openclaw_command,
            openai_api_key=self.settings.openai_api_key,
            openai_api_base_url=self.settings.openai_api_base_url,
            openai_api_model=run.model,
            openclaw_prompt_transport="file",
        )

    @staticmethod
    def _require_state(run: ApplicationGenerationRunRecord, expected: str) -> None:
        if run.status != expected:
            raise GenerationWorkflowError(
                f"Generation run is {run.status}, expected {expected}",
                code="invalid_run_state",
            )

    @staticmethod
    def _fail(
        db: Session,
        run: ApplicationGenerationRunRecord,
        exc: Exception,
    ) -> None:
        if run.status in {"completed", "failed", "cancelled"}:
            return
        retryable = isinstance(exc, AIBackendError) and exc.retryable
        code = getattr(exc, "code", "workflow_failed")
        try:
            transition_generation_run(
                db,
                run=run,
                status="failed",
                stage=run.stage,
                event_kind="run.failed",
                event_data={"code": code, "retryable": retryable},
                error={"code": code, "message": str(exc), "retryable": retryable},
            )
        except GenerationStoreError:
            db.rollback()


def _run_snapshot(run: ApplicationGenerationRunRecord) -> GenerationRunSnapshot:
    try:
        return GenerationRunSnapshot.model_validate(run.input_snapshot)
    except ValidationError as exc:
        raise GenerationWorkflowError(
            "Persisted generation input snapshot is invalid",
            code="invalid_snapshot",
        ) from exc


def _build_prompt(
    instruction_name: str,
    context: dict[str, Any],
    response_model: type[BaseModel],
) -> str:
    return (
        f"{load_instruction('trust_and_facts')}\n\n"
        f"{load_instruction(instruction_name)}\n\n"
        "Return JSON matching this schema exactly:\n"
        f"{json.dumps(response_model.model_json_schema(), ensure_ascii=False)}\n\n"
        "BEGIN UNTRUSTED APPLICATION DATA\n"
        f"{json.dumps(context, ensure_ascii=False, sort_keys=True)}\n"
        "END UNTRUSTED APPLICATION DATA"
    )


def _validated_result[T: BaseModel](result: AIResult, response_model: type[T]) -> T:
    try:
        return response_model.model_validate(result.structured_data)
    except ValidationError as exc:
        raise GenerationWorkflowError(
            "AI backend returned an invalid structured response",
            code="invalid_ai_response",
        ) from exc


def _require_requested_documents(bundle: DraftBundle, document_types: list[str]) -> None:
    if "tailored_resume" in document_types and bundle.resume is None:
        raise GenerationWorkflowError(
            "AI draft omitted the requested resume",
            code="missing_resume_draft",
        )
    if "cover_letter" in document_types and bundle.cover_letter is None:
        raise GenerationWorkflowError(
            "AI draft omitted the requested cover letter",
            code="missing_cover_letter_draft",
        )


def _json_bytes(value: BaseModel) -> bytes:
    return value.model_dump_json(by_alias=True).encode("utf-8")


__all__ = ["GenerationWorkflow", "GenerationWorkflowError"]
