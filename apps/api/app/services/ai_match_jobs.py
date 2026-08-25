from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.jobs import (
    AiMatchJobFailure,
    AiMatchJobStatus,
    StoredJobPayload,
    StoredJobRecord,
)
from app.models.profile import ProfilePayload
from app.services.ai_match import (
    AiMatchError,
    VacancyMatchingAIFacade,
    create_vacancy_matching_ai_facade,
)
from app.services.job_match_store import hydrate_job_data, persist_job_and_match

SessionFactory = Callable[[], Session]


class AiMatchJobManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._statuses: dict[str, AiMatchJobStatus] = {}

    def start(
        self,
        *,
        owner_id: str,
        profile: ProfilePayload,
        jobs: list[dict[str, Any]],
        profile_hash: str,
        candidate_snapshot: dict[str, Any],
        settings: Settings,
        session_factory: SessionFactory,
        force: bool = False,
    ) -> tuple[bool, AiMatchJobStatus]:
        # Capture backend, model and retry policy before the worker starts. Settings cache
        # changes can only affect subsequently launched jobs.
        facade = create_vacancy_matching_ai_facade(settings)
        facade = replace(facade, max_jobs=max(1, facade.max_jobs))
        with self._lock:
            owner_status = self._statuses.get(owner_id, AiMatchJobStatus())
            if owner_status.status in {"queued", "running"}:
                return False, owner_status.model_copy(deep=True)

            run_id = uuid4().hex
            self._statuses[owner_id] = AiMatchJobStatus(
                runId=run_id,
                status="queued",
                total=len(jobs),
                processed=0,
                updatedJobs=[],
            )

        thread = threading.Thread(
            target=self._run,
            kwargs={
                "run_id": run_id,
                "owner_id": owner_id,
                "profile": profile,
                "jobs": jobs,
                "profile_hash": profile_hash,
                "candidate_snapshot": candidate_snapshot,
                "facade": facade,
                "session_factory": session_factory,
                "force": force,
            },
            daemon=True,
        )
        thread.start()
        return True, self.status(owner_id)

    def status(self, owner_id: str) -> AiMatchJobStatus:
        with self._lock:
            return self._statuses.get(owner_id, AiMatchJobStatus()).model_copy(deep=True)

    def _run(
        self,
        *,
        run_id: str,
        owner_id: str,
        profile: ProfilePayload,
        jobs: list[dict[str, Any]],
        profile_hash: str,
        candidate_snapshot: dict[str, Any],
        facade: VacancyMatchingAIFacade,
        session_factory: SessionFactory,
        force: bool,
    ) -> None:
        owner_token = current_owner_id.set(owner_id)
        self._update(owner_id, run_id, status="running")

        try:
            batch_size = max(1, facade.max_jobs)
            for start in range(0, len(jobs), batch_size):
                batch = jobs[start : start + batch_size]
                self._process_batch(
                    run_id=run_id,
                    owner_id=owner_id,
                    profile=profile,
                    batch=batch,
                    profile_hash=profile_hash,
                    candidate_snapshot=candidate_snapshot,
                    facade=facade,
                    session_factory=session_factory,
                    force=force,
                )

            self._update(owner_id, run_id, status="completed")
        except Exception as exc:
            self._update(owner_id, run_id, status="failed", error=str(exc)[:240])
        finally:
            current_owner_id.reset(owner_token)

    def _process_batch(
        self,
        *,
        run_id: str,
        owner_id: str,
        profile: ProfilePayload,
        batch: list[dict[str, Any]],
        profile_hash: str,
        candidate_snapshot: dict[str, Any],
        facade: VacancyMatchingAIFacade,
        session_factory: SessionFactory,
        force: bool,
    ) -> None:
        batch = self._active_jobs_only(
            owner_id=owner_id,
            run_id=run_id,
            batch=batch,
            session_factory=session_factory,
        )
        if not batch:
            return
        try:
            matched_jobs = facade.match(
                profile,
                batch,
                force=force,
                candidate_snapshot=candidate_snapshot,
            )
        except AiMatchError as exc:
            if len(batch) > 1:
                for job in batch:
                    self._process_batch(
                        run_id=run_id,
                        owner_id=owner_id,
                        profile=profile,
                        batch=[job],
                        profile_hash=profile_hash,
                        candidate_snapshot=candidate_snapshot,
                        facade=facade,
                        session_factory=session_factory,
                        force=force,
                    )
                return

            job_id = str(batch[0].get("id") or "unknown")
            self._append_failure(owner_id, run_id, job_id, str(exc))
            return

        matched_by_id = {
            str(job.get("id") or ""): job
            for job in matched_jobs
            if str(job.get("id") or "")
        }
        for job in batch:
            job_id = str(job.get("id") or "")
            matched_job = matched_by_id.get(job_id)
            if not matched_job:
                self._append_failure(
                    owner_id,
                    run_id,
                    job_id or "unknown",
                    "AI backend did not return a result for this vacancy",
                )
                continue

            hydrated_job = self._persist_job(session_factory, matched_job, profile_hash)
            self._append_update(owner_id, run_id, hydrated_job)

    def _persist_job(
        self,
        session_factory: SessionFactory,
        job: dict[str, Any],
        profile_hash: str,
    ) -> dict[str, Any]:
        job_id = str(job.get("id") or "")
        if not job_id:
            return job

        db = session_factory()
        try:
            persist_job_and_match(db, job=job, profile_hash=profile_hash)
            db.commit()
            return hydrate_job_data(db, job_id=job_id, job_data=job, profile_hash=profile_hash)
        except SQLAlchemyError:
            db.rollback()
            raise
        finally:
            db.close()

    def _active_jobs_only(
        self,
        *,
        owner_id: str,
        run_id: str,
        batch: list[dict[str, Any]],
        session_factory: SessionFactory,
    ) -> list[dict[str, Any]]:
        db = session_factory()
        try:
            active: list[dict[str, Any]] = []
            for job in batch:
                job_id = str(job.get("id") or "")
                record = (
                    db.get(StoredJobRecord, (owner_id, job_id))
                    if job_id
                    else None
                )
                if record is not None and record.status != "active":
                    self._increment(owner_id, run_id)
                    continue
                active.append(job)
            return active
        finally:
            db.close()

    def _append_update(self, owner_id: str, run_id: str, job: dict[str, Any]) -> None:
        job_id = str(job.get("id") or "")
        if not job_id:
            self._increment(owner_id, run_id)
            return

        payload = StoredJobPayload(id=job_id, data=job)
        with self._lock:
            owner_status = self._statuses.get(owner_id)
            if owner_status is None or owner_status.run_id != run_id:
                return

            updates = [item for item in owner_status.updated_jobs if item.id != job_id]
            updates.append(payload)
            owner_status.updated_jobs = updates
            owner_status.processed = min(owner_status.total, owner_status.processed + 1)

    def _increment(self, owner_id: str, run_id: str) -> None:
        with self._lock:
            owner_status = self._statuses.get(owner_id)
            if owner_status is None or owner_status.run_id != run_id:
                return
            owner_status.processed = min(owner_status.total, owner_status.processed + 1)

    def _append_failure(
        self,
        owner_id: str,
        run_id: str,
        job_id: str,
        error: str,
    ) -> None:
        failure = AiMatchJobFailure(
            id=job_id,
            error=(error.strip() or "AI vacancy analysis failed")[:240],
        )
        with self._lock:
            owner_status = self._statuses.get(owner_id)
            if owner_status is None or owner_status.run_id != run_id:
                return

            failures = [item for item in owner_status.failed_jobs if item.id != job_id]
            failures.append(failure)
            owner_status.failed_jobs = failures
            owner_status.processed = min(owner_status.total, owner_status.processed + 1)

    def _add_total(self, owner_id: str, run_id: str, amount: int) -> None:
        with self._lock:
            owner_status = self._statuses.get(owner_id)
            if owner_status is None or owner_status.run_id != run_id:
                return
            owner_status.total += amount

    def _update(self, owner_id: str, run_id: str, **changes: Any) -> None:
        with self._lock:
            owner_status = self._statuses.get(owner_id)
            if owner_status is None or owner_status.run_id != run_id:
                return
            for key, value in changes.items():
                setattr(owner_status, key, value)


ai_match_jobs = AiMatchJobManager()
