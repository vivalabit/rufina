from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.models.generation_runs import ApplicationGenerationRunRecord
from app.models.generation_workflow import (
    DraftBundle,
    FitEvaluation,
    ReviewedDraftBundle,
    ReviewerFeedback,
    VisualReview,
)
from app.models.profile import ProfilePayload
from app.models.resume import MasterResume
from app.services.ai_backend import (
    AIBackend,
    AIImageInput,
    AIRequest,
    AIResult,
    create_ai_backend,
    generate_with_retries,
)
from app.services.candidate_profile import canonical_hash, profile_resume
from app.services.generation_artifact_import import import_compiled_generation_documents
from app.services.generation_grounding import validate_grounded_bundle
from app.services.generation_latex import CompiledDocument, render_generation_bundle
from app.services.generation_resources import load_instruction
from app.services.generation_resume_templates import DEFAULT_GENERATION_RESUME_TEMPLATE_ID
from app.services.generation_snapshot import GenerationRunSnapshot, resolve_run_resume_template
from app.services.generation_store import (
    GenerationStoreError,
    append_run_message,
    persist_run_artifact,
    persist_run_check,
    transition_generation_run,
)
from app.services.generation_verification import VerifiedPdf, verify_compiled_document


class GenerationWorkflowError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class GenerationWorkflow:
    def __init__(
        self,
        *,
        settings: Any,
        backend: AIBackend | None = None,
        renderer: Callable[..., tuple[CompiledDocument, ...]] | None = None,
        verifier: Callable[..., VerifiedPdf] | None = None,
    ) -> None:
        self.settings = settings
        self.backend_override = backend
        self.renderer = renderer or render_generation_bundle
        self._renderer_accepts_template = _accepts_template_selection(self.renderer)
        self.verifier = verifier or verify_compiled_document

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

    def continue_approved_run(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
    ) -> ReviewedDraftBundle:
        self._require_state(run, "queued")
        if run.stage != "draft":
            raise GenerationWorkflowError(
                "Generation run is not queued for drafting",
                code="invalid_run_stage",
            )
        return self._draft_and_review(db, run)

    def resume_pdf_checks(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
    ) -> DraftBundle:
        self._require_state(run, "queued")
        if run.stage != "pdf_checks":
            raise GenerationWorkflowError(
                "Generation run is not queued for PDF checks",
                code="invalid_run_stage",
            )
        snapshot = _run_snapshot(run)
        try:
            draft = DraftBundle.model_validate(run.result.get("draft"))
            review = ReviewerFeedback.model_validate(run.result.get("review"))
            master_resume = _snapshot_resume(snapshot)
        except ValidationError as exc:
            raise GenerationWorkflowError(
                "Persisted reviewed draft is not recoverable",
                code="invalid_recovery_state",
            ) from exc
        try:
            return self._render_verify_finalize(
                db,
                run,
                draft=draft,
                review=review,
                master_resume=master_resume,
                target_job_id=snapshot.request.vacancy.id,
            )
        except Exception as exc:
            self._fail(db, run, exc)
            raise

    def _draft_and_review(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
    ) -> ReviewedDraftBundle:
        snapshot = _run_snapshot(run)
        master_resume = _snapshot_resume(snapshot)
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
            final_draft = self._render_verify_finalize(
                db,
                run,
                draft=final_draft,
                review=review,
                master_resume=master_resume,
                target_job_id=target_job_id,
            )
            return ReviewedDraftBundle(draft=final_draft, review=review)
        except Exception as exc:
            self._fail(db, run, exc)
            raise

    def _render_verify_finalize(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        *,
        draft: DraftBundle,
        review: ReviewerFeedback,
        master_resume: MasterResume,
        target_job_id: str,
    ) -> DraftBundle:
        snapshot = _run_snapshot(run)
        fit = FitEvaluation.model_validate(run.result.get("fit"))
        resume_template_id = (
            resolve_run_resume_template(snapshot).template_id
            if "tailored_resume" in snapshot.request.document_types
            else DEFAULT_GENERATION_RESUME_TEMPLATE_ID
        )
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
                "draft": draft.model_dump(mode="json", by_alias=True),
            },
        )
        current_draft = draft
        for attempt in range(1, 4):
            if self._renderer_accepts_template:
                compiled = self.renderer(current_draft, resume_template_id=resume_template_id)
            elif resume_template_id == DEFAULT_GENERATION_RESUME_TEMPLATE_ID:
                # Existing integrations may inject a single-argument renderer
                # for the original Banking template.
                compiled = self.renderer(current_draft)
            else:
                raise GenerationWorkflowError(
                    "The configured renderer does not support resume template selection",
                    code="resume_template_unsupported",
                )
            verified_documents: list[tuple[CompiledDocument, VerifiedPdf]] = []
            image_inputs: list[AIImageInput] = []
            image_index: list[dict[str, Any]] = []
            for document in compiled:
                prefix = "resume" if document.document_type == "tailored_resume" else "cover_letter"
                persist_run_artifact(
                    db,
                    run=run,
                    document_type=document.document_type,
                    artifact_type=f"{prefix}_tex_attempt",
                    file_name=f"{prefix}-attempt-{attempt}.tex",
                    content_type="application/x-tex",
                    content=document.tex_source.encode(),
                    metadata={"attempt": attempt, "engine": document.engine},
                )
                pdf_artifact = persist_run_artifact(
                    db,
                    run=run,
                    document_type=document.document_type,
                    artifact_type=f"{prefix}_pdf_attempt",
                    file_name=f"{prefix}-attempt-{attempt}.pdf",
                    content_type="application/pdf",
                    content=document.pdf,
                    metadata={"attempt": attempt, "engine": document.engine},
                )
                verified = self.verifier(
                    document,
                    bundle=current_draft,
                    keywords=fit.keywords,
                    max_pages=_max_pages(snapshot, document.document_type),
                )
                verified_documents.append((document, verified))
                persist_run_artifact(
                    db,
                    run=run,
                    document_type=document.document_type,
                    artifact_type=f"{prefix}_verification_report",
                    file_name=f"{prefix}-verification-{attempt}.json",
                    content_type="application/json",
                    content=_json_bytes(verified.report),
                    metadata={"attempt": attempt, "pdfArtifactId": pdf_artifact.id},
                )
                for check in verified.report.checks:
                    persist_run_check(
                        db,
                        run=run,
                        artifact=pdf_artifact,
                        check_type=check.name,
                        status=check.status,
                        data={"message": check.message, **check.details},
                    )
                for page_number, image in enumerate(verified.page_images, start=1):
                    page_artifact = persist_run_artifact(
                        db,
                        run=run,
                        document_type=document.document_type,
                        artifact_type=f"{prefix}_page_{page_number}_png",
                        file_name=f"{prefix}-attempt-{attempt}-page-{page_number}.png",
                        content_type="image/png",
                        content=image,
                        metadata={"attempt": attempt, "page": page_number},
                    )
                    image_inputs.append(AIImageInput(content=image))
                    image_index.append(
                        {
                            "image": len(image_inputs),
                            "artifactId": page_artifact.id,
                            "documentType": document.document_type,
                            "page": page_number,
                        }
                    )

            visual = (
                self._request_model(
                    db,
                    run,
                    actor="reviewer",
                    session_suffix="reviewer",
                    instruction_name="verify",
                    context={
                        "attempt": attempt,
                        "pageImages": image_index,
                        "verificationReports": [
                            verified.report.model_dump(mode="json", by_alias=True)
                            for _, verified in verified_documents
                        ],
                        "draft": current_draft.model_dump(mode="json", by_alias=True),
                    },
                    response_model=VisualReview,
                    image_inputs=tuple(image_inputs),
                )
                if image_inputs
                else VisualReview(
                    approved=False,
                    summary="No rendered page images were available for visual review.",
                    findings=(),
                )
            )
            persist_run_artifact(
                db,
                run=run,
                artifact_type="visual_review_json",
                file_name=f"visual-review-{attempt}.json",
                content_type="application/json",
                content=_json_bytes(visual),
                metadata={"attempt": attempt},
            )
            deterministic_passed = all(verified.report.passed for _, verified in verified_documents)
            if deterministic_passed and visual.approved:
                documents = import_compiled_generation_documents(
                    db,
                    run=run,
                    bundle=current_draft,
                    compiled=compiled,
                )
                transition_generation_run(
                    db,
                    run=run,
                    status="completed",
                    stage="final_review",
                    event_kind="run.completed",
                    event_data={"attempts": attempt, "documentCount": len(documents)},
                    result={
                        **run.result,
                        "review": review.model_dump(mode="json", by_alias=True),
                        "draft": current_draft.model_dump(mode="json", by_alias=True),
                        "visualReview": visual.model_dump(mode="json", by_alias=True),
                        "documents": [
                            {
                                "id": document.id,
                                "type": document.type,
                                "version": document.current_version,
                                "downloadUrl": f"/documents/{document.id}/download",
                                "pdfUrl": f"/documents/{document.id}/pdf",
                            }
                            for document in documents
                        ],
                    },
                )
                return current_draft
            if attempt == 3:
                raise GenerationWorkflowError(
                    _verification_failure_message(verified_documents, visual),
                    code="pdf_verification_failed",
                    retryable=True,
                )
            current_draft = self._request_model(
                db,
                run,
                actor="author",
                session_suffix="author",
                instruction_name="draft",
                context={
                    "task": "Repair the complete DraftBundle using the PDF and visual findings.",
                    "previousDraft": current_draft.model_dump(mode="json", by_alias=True),
                    "verificationReports": [
                        verified.report.model_dump(mode="json", by_alias=True)
                        for _, verified in verified_documents
                    ],
                    "visualReview": visual.model_dump(mode="json", by_alias=True),
                },
                response_model=DraftBundle,
            )
            _require_requested_documents(current_draft, run.document_types)
            validate_grounded_bundle(
                current_draft,
                master_resume=master_resume,
                target_job_id=target_job_id,
            )
            persist_run_artifact(
                db,
                run=run,
                artifact_type="repair_bundle_json",
                file_name=f"repair-bundle-{attempt}.json",
                content_type="application/json",
                content=_json_bytes(current_draft),
                metadata={"attempt": attempt},
            )
            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="pdf_checks",
                event_kind="repair.completed",
                event_data={"attempt": attempt},
            )
        raise AssertionError("unreachable")

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
        image_inputs: tuple[AIImageInput, ...] = (),
    ) -> T:
        snapshot = _run_snapshot(run)
        source_context = {
            "candidateProfileVersion": snapshot.request.master_profile_version.model_dump(mode="json", by_alias=True),
            "masterResume": _snapshot_resume(snapshot).model_dump(mode="json", by_alias=True),
            "vacancy": snapshot.request.vacancy.model_dump(mode="json", by_alias=True),
            "documentTypes": list(snapshot.request.document_types),
            "formattingParameters": snapshot.request.formatting_parameters,
            "userPreferences": snapshot.request.user_preferences,
            "language": snapshot.request.language,
        }
        prompt = _build_prompt(instruction_name, {**context, **source_context}, response_model)
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
                image_inputs=image_inputs,
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
        retryable = bool(getattr(exc, "retryable", False))
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


def _accepts_template_selection(renderer: Callable[..., object]) -> bool:
    try:
        parameters = inspect.signature(renderer).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or (
            parameter.name == "resume_template_id"
            and parameter.kind != inspect.Parameter.POSITIONAL_ONLY
        )
        for parameter in parameters
    )


def _brief_diagnostic(value: str, limit: int = 300) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else f"{compact[: limit - 1]}…"


def _verification_failure_message(
    verified_documents: list[tuple[CompiledDocument, VerifiedPdf]],
    visual: VisualReview,
) -> str:
    deterministic_reasons = [
        (
            f"{'CV' if document.document_type == 'tailored_resume' else 'cover letter'}: "
            f"{_brief_diagnostic(check.message)}"
        )
        for document, verified in verified_documents
        for check in verified.report.checks
        if check.status == "failed"
    ][:3]
    visual_reasons: list[str] = []
    if not visual.approved:
        visual_reasons.append(f"visual review: {_brief_diagnostic(visual.summary)}")
        visual_reasons.extend(
            f"visual review: {_brief_diagnostic(finding.message)}"
            for finding in visual.findings
            if finding.severity == "blocking"
        )
        visual_reasons = visual_reasons[:3]

    reasons = [*deterministic_reasons, *visual_reasons]
    concise_reasons: list[str] = []
    for reason in reasons:
        if reason and reason not in concise_reasons:
            concise_reasons.append(reason)
    detail = "; ".join(concise_reasons)
    base = "PDF verification did not pass after three attempts"
    return f"{base}: {detail}" if detail else base


def _snapshot_resume(snapshot: GenerationRunSnapshot) -> MasterResume:
    source = snapshot.request.master_profile_version
    if canonical_hash(source.data) != source.content_sha256:
        raise GenerationWorkflowError("Profile snapshot failed its integrity check", code="invalid_snapshot")
    # Historical runs contain the original MasterResume payload and hash. Never
    # reload or rewrite them using today's candidate profile.
    if source.data.get("schemaVersion") == "1.0" and "basics" in source.data:
        return MasterResume.model_validate(source.data)
    return profile_resume(ProfilePayload.model_validate(source.data), source.id)


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
        "candidateProfileVersion contains the complete frozen candidate source. "
        "masterResume is its document projection. Current profile fields take precedence over "
        "archived sources, audit entries and migration conflicts; those are provenance, not new claims. "
        "Use this same candidate version for drafting, reviewing and every repair.\n\n"
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


def _max_pages(snapshot: GenerationRunSnapshot, document_type: str) -> int:
    raw = snapshot.request.formatting_parameters.get(document_type)
    configured = raw.get("maxPages") if isinstance(raw, dict) else None
    if isinstance(configured, int) and not isinstance(configured, bool) and 1 <= configured <= 10:
        return configured
    return 2 if document_type == "tailored_resume" else 1


__all__ = ["GenerationWorkflow", "GenerationWorkflowError"]
