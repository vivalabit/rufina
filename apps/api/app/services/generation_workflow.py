"""One-click tailoring run: vacancy target, plan, checked wording, rendered documents.

A run never waits for the user. Code selects and orders profile facts, the
model rephrases the selected statements, code checks every sentence against
its source and renders the documents. Rendering a finished run in another
template reuses its content and calls no model.
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any

from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.ai_models import is_openclaw_backend
from app.models.generation import GenerationRequest
from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationRunArtifactRecord,
)
from app.models.generation_workflow import CoverLetterDraft, DraftBundle
from app.models.profile import ProfilePayload
from app.models.resume import FinalResume, MasterResume
from app.services.ai_backend import (
    AIBackend,
    AIBackendError,
    AIRequest,
    AIResult,
    create_configured_ai_backend,
    generate_with_retries,
)
from app.services.ats.job_target import (
    JobTargetExtractor,
    VacancyInput,
    job_target_cache_key,
)
from app.services.ats.models import JobTarget
from app.services.ats.profile_index import build_profile_index
from app.services.ats.tailoring import (
    ModelRequest,
    ModelResponse,
    TailoringSession,
    VacancyContext,
)
from app.services.candidate_profile import canonical_hash, profile_resume
from app.services.document_docx import build_cover_letter_docx, build_resume_docx
from app.services.document_rendering import (
    DocumentRenderError,
    RenderedDocument,
    render_cover_letter,
    render_resume_to_fit,
    resolve_document_template,
)
from app.services.generation_artifact_import import (
    DocumentImport,
    document_file_stem,
    import_rendered_documents,
)
from app.services.generation_grounding import GenerationGroundingError, validate_grounded_bundle
from app.services.generation_input import GenerationInputError
from app.services.generation_snapshot import (
    GenerationRunSnapshot,
    run_created_at,
    run_request,
)
from app.services.generation_store import (
    GenerationStoreError,
    append_run_event,
    append_run_message,
    persist_run_artifact,
    persist_run_check,
    transition_generation_run,
)
from app.services.resume_pdf_renderer import ChromiumPdfSession, ResumePdfRenderError

MAX_PARALLEL_MODEL_REQUESTS = 4
JOB_TARGET_ARTIFACT = "job_target_json"
CONTENT_ARTIFACT = "tailored_content_json"


class GenerationWorkflowError(RuntimeError):
    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class _RunCancelled(Exception):
    pass


class GenerationWorkflow:
    def __init__(
        self,
        *,
        settings: Any,
        backend: AIBackend | None = None,
        today: date | None = None,
    ) -> None:
        self.settings = settings
        self.backend_override = backend
        self.today = today

    # --- One-click run ----------------------------------------------------------

    def run(self, db: Session, run: ApplicationGenerationRunRecord) -> None:
        """Execute a queued run to its end. Any earlier partial progress is redone."""
        self._require_state(run, "queued")
        started = time.perf_counter()
        usage = {"requests": 0, "inputTokens": 0, "outputTokens": 0}
        try:
            snapshot = _run_snapshot(run)
            master = _snapshot_resume(snapshot.request)
            if not master.experiences:
                raise GenerationWorkflowError(
                    "Your profile has no work experience yet. Add at least one role with a "
                    "description, then tailor again.",
                    code="profile_incomplete",
                )
            request = snapshot.request
            vacancy = _vacancy_context(request)

            transition_generation_run(
                db, run=run, status="running", stage="sources", event_kind="vacancy.started"
            )
            target, cached = self._job_target(db, run, snapshot, vacancy)
            self._stop_if_cancelled(db, run)

            session = TailoringSession(
                master=master,
                target=target,
                vacancy=vacancy,
                document_types=tuple(request.document_types),
                language=request.language,
                user_preferences=request.user_preferences,
                resume_id=f"tailored-{run.id}",
                letter_id=f"letter-{run.id}",
                today=self.today or snapshot.created_at.date(),
            )
            plan = session.plan
            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="fit",
                event_kind="plan.completed",
                event_data={
                    "language": plan.language,
                    "vacancySkills": len(target.skills),
                    "vacancyCached": cached,
                    "statementsSelected": len(plan.statements),
                    "statementsOmitted": len(plan.excluded_statement_ids),
                    "gaps": [match.label for match in plan.gaps],
                },
            )

            first_round = session.first_round()
            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="draft",
                event_kind="wording.started",
                event_data={"requests": len(first_round)},
            )
            responses = self._run_requests(db, run, first_round, usage, fail_if_all_fail=True)
            session.apply(first_round, responses)
            self._stop_if_cancelled(db, run)

            retry_round = session.retry_round()
            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="review",
                event_kind="fact_check.completed",
                event_data={
                    "accepted": len(session.wording),
                    "rejected": len(session.rejected),
                    "retrying": bool(retry_round),
                },
            )
            if retry_round:
                session.apply(retry_round, self._run_requests(db, run, retry_round, usage))
            translation_round = session.translation_round()
            if translation_round:
                self._stop_if_cancelled(db, run)
                append_run_event(
                    db,
                    run=run,
                    kind="translation.started",
                    data={"statements": len(translation_round[0].statement_ids)},
                )
                session.apply(
                    translation_round, self._run_requests(db, run, translation_round, usage)
                )
            result = session.finish()
            bundle = DraftBundle(resume=result.resume, cover_letter=result.cover_letter)
            validate_grounded_bundle(bundle, master_resume=master, target_job_id=vacancy.job_id)
            content = {
                "resume": _dump(result.resume),
                "coverLetter": _dump(result.cover_letter),
                "dropOrder": list(result.drop_order),
            }
            persist_run_artifact(
                db,
                run=run,
                artifact_type=CONTENT_ARTIFACT,
                file_name="tailored-content.json",
                content_type="application/json",
                content=json.dumps(content, ensure_ascii=False).encode(),
                metadata={"stage": "review"},
            )
            persist_run_check(
                db,
                run=run,
                check_type="fact_check",
                status="warning" if result.report["keptOriginal"] else "passed",
                data={
                    "message": (
                        "Every rewritten statement was compared with its profile source."
                        if not result.report["keptOriginal"]
                        else "Some statements keep the profile wording after the fact check."
                    ),
                    "keptOriginal": result.report["keptOriginal"],
                },
            )
            self._stop_if_cancelled(db, run)

            transition_generation_run(
                db,
                run=run,
                status="running",
                stage="pdf_checks",
                event_kind="render.started",
                result={**run.result, "tailoring": result.report, "content": content},
            )
            rendered = self._render_and_import(
                db,
                run,
                request=request,
                master=master,
                content=content,
                template_id=snapshot.templates[0].template_id,
                letter_date=snapshot.created_at.date(),
                new_version=False,
            )
            transition_generation_run(
                db,
                run=run,
                status="completed",
                stage="final_review",
                event_kind="run.completed",
                event_data={
                    "documentCount": len(rendered["documents"]),
                    "seconds": round(time.perf_counter() - started, 1),
                },
                result={
                    **run.result,
                    **rendered,
                    "warnings": list(result.warnings),
                    "usage": {**usage, "seconds": round(time.perf_counter() - started, 1)},
                },
            )
        except _RunCancelled:
            return
        except Exception as exc:
            self._fail(db, run, exc)
            raise

    # --- Template switch ----------------------------------------------------------

    def render_in_template(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        *,
        template_id: str,
    ) -> None:
        """Render a finished run's content in another template, without a model."""
        if run.status != "completed":
            raise GenerationWorkflowError(
                "Only a completed run can be rendered in another template",
                code="run_not_completed",
            )
        content = stored_content(run)
        try:
            request = run_request(run.input_snapshot)
        except GenerationInputError as exc:
            raise GenerationWorkflowError(str(exc), code=exc.code) from exc
        master = _snapshot_resume(request)
        try:
            rendered = self._render_and_import(
                db,
                run,
                request=request,
                master=master,
                content=content,
                template_id=template_id,
                letter_date=run_created_at(run.input_snapshot).date(),
                new_version=True,
            )
            run.result = {**run.result, **rendered}
            append_run_event(
                db,
                run=run,
                kind="render.completed",
                data={"documentTemplateId": rendered["render"]["templateId"]},
            )
            db.commit()
            db.refresh(run)
        except Exception:
            db.rollback()
            raise

    def _render_and_import(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        *,
        request: GenerationRequest,
        master: MasterResume,
        content: dict[str, Any],
        template_id: str,
        letter_date: date,
        new_version: bool,
    ) -> dict[str, Any]:
        """Render the stored content and return the result keys that describe the files."""
        resume = FinalResume.model_validate(content["resume"]) if content.get("resume") else None
        letter = (
            CoverLetterDraft.model_validate(content["coverLetter"])
            if content.get("coverLetter")
            else None
        )
        vacancy = _vacancy_context(request)
        imports: list[DocumentImport] = []
        fitted = resume
        try:
            template = resolve_document_template(template_id, db=db)
            with ChromiumPdfSession() as chromium:
                if resume is not None:
                    resume_render = render_resume_to_fit(
                        resume,
                        template=template,
                        max_pages=max_pages(request, "tailored_resume", master),
                        drop_order=content.get("dropOrder") or (),
                        session=chromium,
                    )
                    fitted = resume_render.resume
                    imports.append(
                        DocumentImport(
                            rendered=resume_render.document,
                            content=_json(fitted),
                            title=f"{vacancy.title or 'Application'} — Tailored CV",
                            file_stem=document_file_stem(
                                master.basics.full_name, "tailored_resume", vacancy.company
                            ),
                            docx=build_resume_docx(fitted, template=template),
                        )
                    )
                if letter is not None:
                    imports.append(
                        DocumentImport(
                            rendered=render_cover_letter(
                                letter,
                                sender=master.basics,
                                letter_date=letter_date,
                                template=template,
                                max_pages=max_pages(request, "cover_letter", master),
                                session=chromium,
                            ),
                            content=_json(letter),
                            title=f"{vacancy.title or 'Application'} — Cover letter",
                            file_stem=document_file_stem(
                                master.basics.full_name, "cover_letter", vacancy.company
                            ),
                            docx=build_cover_letter_docx(
                                letter,
                                sender=master.basics,
                                letter_date=letter_date,
                                template=template,
                            ),
                        )
                    )
        except (DocumentRenderError, ResumePdfRenderError) as exc:
            raise GenerationWorkflowError(
                f"Document rendering failed: {exc}",
                code=getattr(exc, "code", "document_render_failed"),
                retryable=True,
            ) from exc
        if not imports:
            raise GenerationWorkflowError(
                "The run has no document content to render", code="content_missing"
            )

        documents = import_rendered_documents(
            db, run=run, job_id=vacancy.job_id, items=imports, new_version=new_version
        )
        for item in imports:
            self._persist_render_checks(
                db, run, item.rendered, max_pages(request, item.rendered.document_type, master)
            )
        resume_document = next(
            (item.rendered for item in imports if item.rendered.document_type == "tailored_resume"),
            None,
        )
        return {
            "draft": DraftBundle(resume=fitted, cover_letter=letter).model_dump(
                mode="json", by_alias=True
            ),
            "render": {
                "templateId": template.id,
                "templateVersion": template.version,
                "pages": {item.rendered.document_type: item.rendered.page_count for item in imports},
                "droppedStatementIds": (
                    list(resume_document.dropped_statement_ids) if resume_document else []
                ),
                "fitScale": resume_document.fit_scale if resume_document else 1.0,
                "atsReadable": all(item.rendered.ats_readable for item in imports),
            },
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
        }

    @staticmethod
    def _persist_render_checks(
        db: Session,
        run: ApplicationGenerationRunRecord,
        rendered: RenderedDocument,
        limit: int,
    ) -> None:
        label = "CV" if rendered.document_type == "tailored_resume" else "Cover letter"
        fits = rendered.page_count <= limit
        persist_run_check(
            db,
            run=run,
            check_type="page_limit",
            status="passed" if fits else "warning",
            data={
                "document": rendered.document_type,
                "templateId": rendered.template_id,
                "pages": rendered.page_count,
                "maxPages": limit,
                "message": (
                    f"{label} fits on {rendered.page_count} of {limit} allowed page(s)."
                    if fits
                    else f"{label} needs {rendered.page_count} pages; the limit is {limit}."
                ),
            },
        )
        if rendered.dropped_statement_ids:
            persist_run_check(
                db,
                run=run,
                check_type="page_fit",
                status="warning",
                data={
                    "document": rendered.document_type,
                    "templateId": rendered.template_id,
                    "droppedStatementIds": list(rendered.dropped_statement_ids),
                    "message": (
                        f"{len(rendered.dropped_statement_ids)} lower-priority statement(s) were "
                        "left out to keep the page limit."
                    ),
                },
            )
        persist_run_check(
            db,
            run=run,
            check_type="ats_text",
            status="passed" if rendered.ats_readable else "warning",
            data={
                "document": rendered.document_type,
                "templateId": rendered.template_id,
                "message": (
                    f"{label}: applicant tracking systems can read the complete text."
                    if rendered.ats_readable
                    else f"{label}: {rendered.text_check_error}"
                ),
            },
        )

    # --- Vacancy target -------------------------------------------------------------

    def _job_target(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        snapshot: GenerationRunSnapshot,
        vacancy: VacancyContext,
    ) -> tuple[JobTarget, bool]:
        """Parse the vacancy once per posting text, model and dictionary version."""
        parsing_model = snapshot.execution.parsing_model or run.model
        extractor = JobTargetExtractor(
            self._backend(run),
            model=parsing_model,
            agent_id=getattr(self.settings, "openclaw_assistant_agent_id", ""),
            thinking="off" if is_openclaw_backend(run.backend) else "low",
            timeout_seconds=min(int(run.settings_snapshot["timeout_seconds"]), 120),
            max_attempts=int(run.settings_snapshot["max_attempts"]),
            retry_backoff_seconds=float(run.settings_snapshot["retry_backoff_seconds"]),
            fallback_to_dictionary=True,
        )
        vacancy_input = VacancyInput(title=vacancy.title, description=vacancy.text)
        key = job_target_cache_key(
            vacancy_input, dictionary_version=extractor.dictionary.version, mode=extractor.mode
        )
        target = _cached_job_target(db, run, key)
        cached = target is not None
        if target is None:
            target = extractor.extract(vacancy_input)
        persist_run_artifact(
            db,
            run=run,
            artifact_type=JOB_TARGET_ARTIFACT,
            file_name="job-target.json",
            content_type="application/json",
            content=target.model_dump_json(by_alias=True).encode(),
            # A dictionary-only fallback is not reused: the next run asks the model again.
            metadata={"cacheKey": key if target.model else "", "cached": cached},
        )
        if not target.model:
            persist_run_check(
                db,
                run=run,
                check_type="vacancy_analysis",
                status="warning",
                data={
                    "message": (
                        "The vacancy was analyzed with the built-in skill dictionary only "
                        "because the model request failed."
                    )
                },
            )
        return target, cached

    # --- Model requests -------------------------------------------------------------

    def _run_requests(
        self,
        db: Session,
        run: ApplicationGenerationRunRecord,
        requests: Sequence[ModelRequest],
        usage: dict[str, int],
        *,
        fail_if_all_fail: bool = False,
    ) -> list[ModelResponse]:
        """Send the requests of one round, in parallel where the backend allows it."""
        if not requests:
            return []
        backend = self._backend(run)
        agent_id = getattr(self.settings, "openclaw_assistant_agent_id", "")
        timeout = int(run.settings_snapshot["timeout_seconds"])
        attempts = int(run.settings_snapshot["max_attempts"])
        backoff = float(run.settings_snapshot["retry_backoff_seconds"])

        def call(request: ModelRequest) -> AIResult | AIBackendError:
            try:
                return generate_with_retries(
                    backend,
                    AIRequest(
                        prompt=request.prompt,
                        model=run.model,
                        agent_id=agent_id,
                        thinking=run.reasoning_effort,
                        timeout_seconds=timeout,
                        session_id=f"application-generation:{run.id}:{request.label}",
                        structured=True,
                        response_model=request.response_model,
                    ),
                    max_attempts=attempts,
                    retry_backoff_seconds=backoff,
                )
            except AIBackendError as exc:
                return exc

        # One OpenClaw agent process at a time: its local state is not built for
        # concurrent sessions. Provider APIs take the requests in parallel.
        workers = 1 if is_openclaw_backend(run.backend) else MAX_PARALLEL_MODEL_REQUESTS
        with ThreadPoolExecutor(max_workers=min(workers, len(requests))) as pool:
            outcomes = list(pool.map(call, requests))

        responses: list[ModelResponse] = []
        for request, outcome in zip(requests, outcomes, strict=True):
            append_run_message(db, run=run, actor="author", role="user", content=request.prompt)
            if isinstance(outcome, AIBackendError):
                append_run_event(
                    db,
                    run=run,
                    kind="model.failed",
                    data={"request": request.label, "code": outcome.code},
                )
                responses.append(ModelResponse(error=f"{outcome.code}: {outcome}"))
                continue
            append_run_message(
                db,
                run=run,
                actor="author",
                role="assistant",
                content=outcome.text,
                raw_response=outcome.raw_response,
                response_id=outcome.session_id or None,
                usage=outcome.usage.as_dict(),
            )
            usage["requests"] += 1
            usage["inputTokens"] += outcome.usage.input_tokens
            usage["outputTokens"] += outcome.usage.output_tokens
            responses.append(
                ModelResponse(data=outcome.structured_data)
                if outcome.structured_data is not None
                else ModelResponse(error="the response was not valid JSON")
            )
        db.commit()
        failures = [outcome for outcome in outcomes if isinstance(outcome, AIBackendError)]
        if fail_if_all_fail and len(failures) == len(outcomes):
            first = failures[0]
            raise GenerationWorkflowError(
                f"The AI backend request failed: {first}",
                code=first.code,
                retryable=first.retryable,
            )
        return responses

    def _backend(self, run: ApplicationGenerationRunRecord) -> AIBackend:
        if self.backend_override is not None:
            return self.backend_override
        return create_configured_ai_backend(
            self.settings,
            mode=run.backend,
            model=run.model,
            openclaw_prompt_transport="file",
        )

    # --- State ----------------------------------------------------------------------

    @staticmethod
    def _require_state(run: ApplicationGenerationRunRecord, expected: str) -> None:
        if run.status != expected:
            raise GenerationWorkflowError(
                f"Generation run is {run.status}, expected {expected}",
                code="invalid_run_state",
            )

    @staticmethod
    def _stop_if_cancelled(db: Session, run: ApplicationGenerationRunRecord) -> None:
        db.refresh(run)
        if not run.cancel_requested:
            return
        transition_generation_run(
            db, run=run, status="cancelled", stage=run.stage, event_kind="run.cancelled"
        )
        raise _RunCancelled

    @staticmethod
    def _fail(
        db: Session,
        run: ApplicationGenerationRunRecord,
        exc: Exception,
    ) -> None:
        # A failed flush expires ORM attributes and leaves the transaction unusable.
        # Roll back before even reading run.status, then persist the failure separately.
        if not db.is_active:
            db.rollback()
        if run.status in {"completed", "failed", "cancelled"}:
            return
        retryable = bool(getattr(exc, "retryable", False))
        database_failure = isinstance(exc, SQLAlchemyError)
        code = "database_error" if database_failure else getattr(exc, "code", "workflow_failed")
        if isinstance(exc, GenerationGroundingError):
            code = "grounding_failed"
        message = (
            "Could not save generation results to the database."
            if database_failure
            else str(exc)
        )
        try:
            transition_generation_run(
                db,
                run=run,
                status="failed",
                stage=run.stage,
                event_kind="run.failed",
                event_data={"code": code, "retryable": retryable},
                error={"code": code, "message": message, "retryable": retryable},
            )
        except GenerationStoreError:
            db.rollback()


def stored_content(run: ApplicationGenerationRunRecord) -> dict[str, Any]:
    """Structured documents of a finished run, complete and before page fitting.

    Runs of the earlier pipeline stored only the final draft; that draft is
    rendered as it is.
    """
    content = run.result.get("content")
    if isinstance(content, dict) and (content.get("resume") or content.get("coverLetter")):
        return content
    draft = run.result.get("draft")
    if isinstance(draft, dict) and (draft.get("resume") or draft.get("coverLetter")):
        return {
            "resume": draft.get("resume"),
            "coverLetter": draft.get("coverLetter"),
            "dropOrder": [],
        }
    raise GenerationWorkflowError(
        "This run has no stored document content", code="content_missing"
    )


# A profile with less experience than this gets a one-page resume by default.
TWO_PAGE_RESUME_MONTHS = 96


def max_pages(
    request: GenerationRequest,
    document_type: str,
    master: MasterResume | None = None,
) -> int:
    """The requested page limit, or one page (two for a long career) when not set."""
    raw = request.formatting_parameters.get(document_type)
    configured = raw.get("maxPages") if isinstance(raw, dict) else None
    if isinstance(configured, int) and not isinstance(configured, bool) and 1 <= configured <= 10:
        return configured
    if document_type == "tailored_resume" and master is not None:
        return 2 if build_profile_index(master).total_months >= TWO_PAGE_RESUME_MONTHS else 1
    return 1


def _vacancy_context(request: GenerationRequest) -> VacancyContext:
    data = request.vacancy.data

    def text(key: str) -> str:
        value = data.get(key)
        return " ".join(value.split()) if isinstance(value, str) else ""

    return VacancyContext(
        job_id=request.vacancy.id,
        title=text("title"),
        company=text("company"),
        location=text("location"),
        text=request.vacancy.full_description,
    )


def _cached_job_target(
    db: Session,
    run: ApplicationGenerationRunRecord,
    key: str,
) -> JobTarget | None:
    """Reuse the parsed vacancy of an earlier run of the same application."""
    artifacts = db.scalars(
        select(GenerationRunArtifactRecord)
        .join(
            ApplicationGenerationRunRecord,
            ApplicationGenerationRunRecord.id == GenerationRunArtifactRecord.run_id,
        )
        .where(
            ApplicationGenerationRunRecord.application_id == run.application_id,
            GenerationRunArtifactRecord.artifact_type == JOB_TARGET_ARTIFACT,
        )
        .order_by(GenerationRunArtifactRecord.created_at.desc())
        .limit(20)
    ).all()
    for artifact in artifacts:
        if artifact.artifact_metadata.get("cacheKey") != key:
            continue
        try:
            return JobTarget.model_validate_json(artifact.content)
        except ValidationError:
            continue
    return None


def _snapshot_resume(request: GenerationRequest) -> MasterResume:
    source = request.master_profile_version
    if canonical_hash(source.data) != source.content_sha256:
        raise GenerationWorkflowError(
            "Profile snapshot failed its integrity check", code="invalid_snapshot"
        )
    try:
        # Historical runs contain the original MasterResume payload and hash. Never
        # reload or rewrite them using today's candidate profile.
        if source.data.get("schemaVersion") == "1.0" and "basics" in source.data:
            return MasterResume.model_validate(source.data)
        return profile_resume(ProfilePayload.model_validate(source.data), source.id)
    except ValidationError as exc:
        raise GenerationWorkflowError(
            "The master profile snapshot cannot be read", code="invalid_snapshot"
        ) from exc


def _run_snapshot(run: ApplicationGenerationRunRecord) -> GenerationRunSnapshot:
    try:
        return GenerationRunSnapshot.model_validate(run.input_snapshot)
    except ValidationError as exc:
        raise GenerationWorkflowError(
            "This run was created by an earlier version. Start a new run.",
            code="invalid_snapshot",
        ) from exc


def _dump(value: BaseModel | None) -> dict[str, Any] | None:
    return value.model_dump(mode="json", by_alias=True) if value is not None else None


def _json(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


__all__ = [
    "CONTENT_ARTIFACT",
    "JOB_TARGET_ARTIFACT",
    "GenerationWorkflow",
    "GenerationWorkflowError",
    "max_pages",
    "stored_content",
]
