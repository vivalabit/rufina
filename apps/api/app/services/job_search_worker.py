import asyncio
import hashlib
import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from threading import Lock

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.identity import current_owner_id
from app.core.settings import Settings
from app.models.job_search import (
    JobSearchConfigRecord,
    JobSearchRunRecord,
    JobSearchScheduleRecord,
    JobSourceConfigRecord,
)
from app.services.job_search_execution import (
    build_config_snapshot,
    execute_job_search,
    recalculate_next_schedule_run,
)
from app.services.vacancy_search import (
    VacancySearchRunner,
    create_vacancy_search_runner,
)

logger = logging.getLogger(__name__)

ACTIVE_RUN_STATUSES = ("queued", "running")
DEFAULT_RESERVATION_LIMIT = 20

_local_lock_guard = Lock()
_local_schedule_locks: dict[str, Lock] = {}
_local_reservation_lock = Lock()

SessionFactory = Callable[[], Session]
RunnerFactory = Callable[[Settings], VacancySearchRunner]


async def run_job_search_worker(
    interval_seconds: float,
    *,
    settings: Settings,
    session_factory: SessionFactory = SessionLocal,
    runner_factory: RunnerFactory = create_vacancy_search_runner,
    stop_event: asyncio.Event | None = None,
) -> None:
    stop = stop_event or asyncio.Event()
    while not stop.is_set():
        cycle = asyncio.create_task(
            asyncio.to_thread(
                run_job_search_cycle,
                settings=settings,
                session_factory=session_factory,
                runner_factory=runner_factory,
            )
        )
        try:
            await cycle
        except asyncio.CancelledError:
            await asyncio.shield(cycle)
            raise
        except Exception:
            logger.exception("Automatic job search worker cycle failed")

        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass


def run_job_search_cycle(
    *,
    settings: Settings,
    session_factory: SessionFactory = SessionLocal,
    runner_factory: RunnerFactory = create_vacancy_search_runner,
    now: datetime | None = None,
) -> list[str]:
    reference = now or datetime.now(UTC)
    pending_ids = incomplete_automatic_run_ids(session_factory)
    reserved_ids = reserve_due_job_searches(
        session_factory,
        now=reference,
    )
    executed: list[str] = []
    for run_id in dict.fromkeys([*pending_ids, *reserved_ids]):
        if execute_reserved_job_search(
            run_id,
            settings=settings,
            session_factory=session_factory,
            runner_factory=runner_factory,
        ):
            executed.append(run_id)
    return executed


def reserve_due_job_searches(
    session_factory: SessionFactory,
    *,
    now: datetime,
    limit: int = DEFAULT_RESERVATION_LIMIT,
) -> list[str]:
    with session_factory() as db:
        dialect = db.get_bind().dialect.name
        reservation_guard = _local_reservation_lock if dialect != "postgresql" else _NoopLock()
        with reservation_guard:
            return _reserve_due_job_searches(db, now=now, limit=limit)


def _reserve_due_job_searches(
    db: Session,
    *,
    now: datetime,
    limit: int,
) -> list[str]:
    query = (
        select(JobSearchScheduleRecord)
        .where(
            JobSearchScheduleRecord.enabled.is_(True),
            JobSearchScheduleRecord.next_run_at.is_not(None),
            JobSearchScheduleRecord.next_run_at <= now,
        )
        .order_by(
            JobSearchScheduleRecord.next_run_at,
            JobSearchScheduleRecord.id,
        )
        .limit(limit)
    )
    if db.get_bind().dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    schedules = list(db.scalars(query).all())
    reserved_ids: list[str] = []
    with ExitStack() as locks:
        for schedule in schedules:
            acquired = locks.enter_context(schedule_execution_lock(db, schedule.id))
            if not acquired:
                continue
            if has_active_schedule_run(db, schedule.id):
                recalculate_next_schedule_run(schedule, now=now)
                schedule.updated_at = now
                continue
            config = db.get(JobSearchConfigRecord, schedule.config_id)
            if config is None:
                continue

            scheduled_for = as_utc(schedule.next_run_at)
            run = JobSearchRunRecord(
                owner_id=schedule.owner_id,
                schedule_id=schedule.id,
                run_type="automatic",
                scheduled_for=scheduled_for,
                config_snapshot=build_config_snapshot(
                    config,
                    source_configs=source_configs_for_schedule(db, schedule),
                ),
                sources=list(schedule.sources),
                status="queued",
                jobs_found=0,
                jobs_added=0,
                source_errors={},
                started_at=now,
            )
            db.add(run)
            recalculate_next_schedule_run(schedule, now=now)
            schedule.updated_at = now
            db.flush()
            reserved_ids.append(run.id)
        db.commit()
    return reserved_ids


def incomplete_automatic_run_ids(
    session_factory: SessionFactory,
) -> list[str]:
    with session_factory() as db:
        return list(
            db.scalars(
                select(JobSearchRunRecord.id)
                .where(
                    JobSearchRunRecord.run_type == "automatic",
                    JobSearchRunRecord.status.in_(ACTIVE_RUN_STATUSES),
                )
                .order_by(
                    JobSearchRunRecord.scheduled_for,
                    JobSearchRunRecord.started_at,
                    JobSearchRunRecord.id,
                )
            ).all()
        )


def execute_reserved_job_search(
    run_id: str,
    *,
    settings: Settings,
    session_factory: SessionFactory,
    runner_factory: RunnerFactory,
) -> bool:
    with session_factory() as db:
        run = db.get(JobSearchRunRecord, run_id)
        if (
            run is None
            or run.run_type != "automatic"
            or run.status not in ACTIVE_RUN_STATUSES
            or run.schedule_id is None
        ):
            return False

        with schedule_execution_lock(db, run.schedule_id) as acquired:
            if not acquired:
                return False
            db.expire_all()
            run = db.get(JobSearchRunRecord, run_id)
            if run is None or run.status not in ACTIVE_RUN_STATUSES or run.schedule_id is None:
                return False
            schedule = db.get(JobSearchScheduleRecord, run.schedule_id)
            if schedule is None:
                fail_orphaned_run(db, run, "Job search schedule no longer exists")
                return False

            owner_token = current_owner_id.set(run.owner_id)
            try:
                config = db.get(JobSearchConfigRecord, schedule.config_id)
                if config is None:
                    fail_orphaned_run(db, run, "Job search config no longer exists")
                    return False
                try:
                    execute_job_search(
                        db,
                        schedule=schedule,
                        config=config,
                        runner=runner_factory(settings),
                        settings=settings,
                        run_type="automatic",
                        scheduled_for=run.scheduled_for,
                        reserved_run=run,
                        recalculate_schedule=False,
                    )
                except Exception:
                    logger.exception(
                        "Automatic job search failed: schedule_id=%s run_id=%s",
                        schedule.id,
                        run.id,
                    )
                return True
            finally:
                current_owner_id.reset(owner_token)


def fail_orphaned_run(
    db: Session,
    run: JobSearchRunRecord,
    message: str,
) -> None:
    run.status = "failed"
    run.source_errors = {"worker": message}
    run.completed_at = datetime.now(UTC)
    db.commit()


def source_configs_for_schedule(
    db: Session,
    schedule: JobSearchScheduleRecord,
) -> dict[str, JobSourceConfigRecord]:
    records: dict[str, JobSourceConfigRecord] = {}
    for source, source_config_id in schedule.source_config_ids.items():
        record = db.get(JobSourceConfigRecord, source_config_id)
        if (
            record is not None
            and record.source == source
            and record.config_id == schedule.config_id
        ):
            records[source] = record
    return records


def has_active_schedule_run(db: Session, schedule_id: str) -> bool:
    return (
        db.scalar(
            select(JobSearchRunRecord.id)
            .where(
                JobSearchRunRecord.schedule_id == schedule_id,
                JobSearchRunRecord.status.in_(ACTIVE_RUN_STATUSES),
            )
            .limit(1)
        )
        is not None
    )


@contextmanager
def schedule_execution_lock(
    db: Session,
    schedule_id: str,
) -> Iterator[bool]:
    if db.get_bind().dialect.name == "postgresql":
        lock_key = advisory_lock_key(schedule_id)
        acquired = bool(
            db.scalar(
                text("SELECT pg_try_advisory_lock(:lock_key)"),
                {"lock_key": lock_key},
            )
        )
        try:
            yield acquired
        finally:
            if acquired:
                db.execute(
                    text("SELECT pg_advisory_unlock(:lock_key)"),
                    {"lock_key": lock_key},
                )
        return

    lock = local_schedule_lock(schedule_id)
    acquired = lock.acquire(blocking=False)
    try:
        yield acquired
    finally:
        if acquired:
            lock.release()


def advisory_lock_key(schedule_id: str) -> int:
    digest = hashlib.sha256(schedule_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def local_schedule_lock(schedule_id: str) -> Lock:
    with _local_lock_guard:
        return _local_schedule_locks.setdefault(schedule_id, Lock())


def as_utc(value: datetime | None) -> datetime:
    if value is None:
        raise ValueError("Scheduled job search must have next_run_at")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class _NoopLock:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> None:
        return None
