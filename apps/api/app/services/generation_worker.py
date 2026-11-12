from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Lock
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.generation_runs import ApplicationGenerationRunRecord
from app.services.generation_store import append_run_event, transition_generation_run
from app.services.generation_workflow import GenerationWorkflow

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
WorkflowFactory = Callable[[Settings], GenerationWorkflow]
LEASE_DURATION = timedelta(minutes=5)
_reservation_lock = Lock()


async def run_generation_worker(
    interval_seconds: float,
    *,
    settings: Settings,
    settings_provider: Callable[[], Settings] | None = None,
    session_factory: SessionFactory = SessionLocal,
    workflow_factory: WorkflowFactory | None = None,
    stop_event: asyncio.Event | None = None,
) -> None:
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        cycle_settings = settings_provider() if settings_provider is not None else settings
        cycle = asyncio.create_task(
            asyncio.to_thread(
                run_generation_cycle,
                settings=cycle_settings,
                session_factory=session_factory,
                workflow_factory=workflow_factory,
            )
        )
        try:
            await cycle
        except asyncio.CancelledError:
            await asyncio.shield(cycle)
            raise
        except Exception:
            logger.exception("Application generation worker cycle failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass


def run_generation_cycle(
    *,
    settings: Settings,
    session_factory: SessionFactory = SessionLocal,
    workflow_factory: WorkflowFactory | None = None,
    now: datetime | None = None,
) -> str | None:
    reference = now or datetime.now(UTC)
    recover_expired_generation_runs(session_factory, now=reference)
    reservation = reserve_generation_run(session_factory, now=reference)
    if reservation is None:
        return None
    run_id, owner_id, lease_token = reservation
    owner_token = current_owner_id.set(owner_id)
    try:
        with session_factory() as db:
            run = db.get(ApplicationGenerationRunRecord, run_id)
            if run is None or run.lease_token != lease_token:
                return None
            if run.cancel_requested:
                transition_generation_run(
                    db,
                    run=run,
                    status="cancelled",
                    stage=run.stage,
                    event_kind="run.cancelled",
                )
                return run_id
            workflow = (
                workflow_factory(settings)
                if workflow_factory is not None
                else GenerationWorkflow(settings=settings)
            )
            try:
                workflow.run(db, run)
            except Exception as exc:
                logger.exception("Application generation run failed: run_id=%s", run_id)
                # Also cover failures outside the workflow's own error handler.
                # Never release a failed run as 'running' with no lease to recover it.
                db.rollback()
                run = db.get(ApplicationGenerationRunRecord, run_id)
                if (
                    run is not None
                    and run.lease_token == lease_token
                    and run.status not in {"completed", "failed", "cancelled"}
                ):
                    transition_generation_run(
                        db,
                        run=run,
                        status="failed",
                        stage=run.stage,
                        event_kind="run.failed",
                        event_data={"code": "worker_failed", "retryable": False},
                        error={
                            "code": "worker_failed",
                            "message": str(exc),
                            "retryable": False,
                        },
                    )
            finally:
                _release_lease(db, run_id=run_id, lease_token=lease_token)
            return run_id
    finally:
        current_owner_id.reset(owner_token)


def reserve_generation_run(
    session_factory: SessionFactory,
    *,
    now: datetime,
) -> tuple[str, str, str] | None:
    with _reservation_lock, session_factory() as db:
        query = (
            select(ApplicationGenerationRunRecord)
            .where(
                ApplicationGenerationRunRecord.status == "queued",
                or_(
                    ApplicationGenerationRunRecord.lease_until.is_(None),
                    ApplicationGenerationRunRecord.lease_until < now,
                ),
            )
            .order_by(
                ApplicationGenerationRunRecord.created_at,
                ApplicationGenerationRunRecord.id,
            )
            .limit(1)
            .execution_options(skip_owner_scope=True)
        )
        if db.get_bind().dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)
        run = db.scalar(query)
        if run is None:
            return None
        lease_token = uuid4().hex
        run.lease_token = lease_token
        run.lease_until = now + LEASE_DURATION
        db.commit()
        return run.id, run.owner_id, lease_token


def recover_expired_generation_runs(
    session_factory: SessionFactory,
    *,
    now: datetime,
) -> list[str]:
    recovered: list[str] = []
    with _reservation_lock, session_factory() as db:
        runs = db.scalars(
            select(ApplicationGenerationRunRecord)
            .where(
                ApplicationGenerationRunRecord.status == "running",
                ApplicationGenerationRunRecord.lease_until.is_not(None),
                ApplicationGenerationRunRecord.lease_until < now,
            )
            .execution_options(skip_owner_scope=True)
        ).all()
        for run in runs:
            # A run is cheap enough to redo from the start after a worker crash.
            run.status = "queued"
            run.stage = "sources"
            run.lease_token = None
            run.lease_until = None
            append_run_event(
                db,
                run=run,
                kind="run.recovered",
                data={"reason": "worker_lease_expired"},
            )
            recovered.append(run.id)
        db.commit()
    return recovered


def _release_lease(db: Session, *, run_id: str, lease_token: str) -> None:
    if not db.is_active:
        db.rollback()
    run = db.get(ApplicationGenerationRunRecord, run_id)
    if run is None or run.lease_token != lease_token:
        return
    run.lease_token = None
    run.lease_until = None
    db.commit()


__all__ = [
    "recover_expired_generation_runs",
    "reserve_generation_run",
    "run_generation_cycle",
    "run_generation_worker",
]
