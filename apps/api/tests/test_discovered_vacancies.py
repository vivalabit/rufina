from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.identity import current_owner_id
from app.models.jobs import DiscoveredVacancyRecord
from app.models.parsers import ParsedJob, ParserSearchResponse
from app.services.discovered_vacancies import (
    DiscoveredVacancyUpsertResult,
    discovered_vacancy_to_parsed_job,
    mark_missing_vacancies_inactive,
    upsert_discovered_vacancies,
)
from app.services.job_search_execution import reconcile_full_catalog_inventory
from app.services.vacancy_search import VacancySearchRunResult


def test_inventory_upsert_is_owner_scoped_idempotent_and_ignores_tracking_query() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("inventory-owner")
    try:
        with Session(engine) as db:
            first = upsert_discovered_vacancies(
                db,
                jobs=[vacancy(url="https://example.test/jobs/42?tracking=first")],
                run_id="run-1",
                seen_at=datetime(2026, 8, 2, 10, 0, tzinfo=UTC),
            )
            db.commit()
            first_id = first.vacancies[0].job_id

            second = upsert_discovered_vacancies(
                db,
                jobs=[vacancy(url="https://example.test/jobs/42?tracking=second")],
                run_id="run-2",
                seen_at=datetime(2026, 8, 2, 11, 0, tzinfo=UTC),
            )
            db.commit()

            records = list(db.scalars(select(DiscoveredVacancyRecord)).all())
            assert len(records) == 1
            assert second.vacancies[0].job_id == first_id
            assert second.jobs_discovered_new == 0
            assert second.jobs_discovered_updated == 0
            assert second.jobs_already_observed == 1
            assert records[0].canonical_url == "https://example.test/jobs/42"
            assert records[0].last_seen_run_id == "run-2"
            assert discovered_vacancy_to_parsed_job(records[0]).title == ("Backend Engineer")
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


def test_changed_screening_content_updates_hash_and_full_catalog_can_be_inactivated() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("inventory-update-owner")
    try:
        with Session(engine) as db:
            original = vacancy(
                source="sbb",
                url="https://jobs.sbb.ch/vacancies/42",
                description="Original description",
            )
            first = upsert_discovered_vacancies(
                db,
                jobs=[original],
                run_id="run-1",
            )
            db.commit()
            original_hash = first.vacancies[0].vacancy_hash

            changed = original.model_copy(update={"description": "Changed screening description"})
            second = upsert_discovered_vacancies(
                db,
                jobs=[changed],
                run_id="run-2",
            )
            assert second.jobs_discovered_updated == 1
            assert second.vacancies[0].vacancy_hash != original_hash

            assert (
                mark_missing_vacancies_inactive(
                    db,
                    source="sbb",
                    seen_job_ids=set(),
                    unavailable_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
                )
                == 1
            )
            db.commit()

            record = db.scalar(select(DiscoveredVacancyRecord))
            assert record is not None
            assert record.availability == "inactive"
            assert record.unavailable_at is not None

            reactivated = upsert_discovered_vacancies(
                db,
                jobs=[changed],
                run_id="run-3",
            )
            db.commit()
            assert reactivated.jobs_already_observed == 1
            assert record.availability == "active"
            assert record.unavailable_at is None
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


def test_full_catalog_reconciliation_requires_a_successful_completed_scan() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    owner_token = current_owner_id.set("inventory-reconcile-owner")
    try:
        with Session(engine) as db:
            upsert_discovered_vacancies(
                db,
                jobs=[
                    vacancy(
                        source="sbb",
                        url="https://jobs.sbb.ch/vacancies/missing",
                    )
                ],
                run_id="run-1",
            )
            db.commit()

            reconcile_full_catalog_inventory(
                db,
                search_result=VacancySearchRunResult(
                    jobs=[],
                    source_results={
                        "sbb": ParserSearchResponse(
                            parser="sbb",
                            status="running",
                            search_url="https://jobs.sbb.ch",
                        )
                    },
                    source_errors={"sbb": "partial scan"},
                ),
                inventory_result=DiscoveredVacancyUpsertResult(),
                unavailable_at=datetime(2026, 8, 2, 12, 0, tzinfo=UTC),
            )
            record = db.scalar(select(DiscoveredVacancyRecord))
            assert record is not None
            assert record.availability == "active"

            reconcile_full_catalog_inventory(
                db,
                search_result=VacancySearchRunResult(
                    jobs=[],
                    source_results={
                        "sbb": ParserSearchResponse(
                            parser="sbb",
                            status="completed",
                            search_url="https://jobs.sbb.ch",
                        )
                    },
                    source_errors={},
                ),
                inventory_result=DiscoveredVacancyUpsertResult(),
                unavailable_at=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
            )
            db.commit()
            assert record.availability == "inactive"
    finally:
        current_owner_id.reset(owner_token)
        engine.dispose()


def vacancy(
    *,
    source: str = "linkedin",
    url: str,
    description: str = "Original description",
) -> ParsedJob:
    return ParsedJob(
        source=source,
        title="Backend Engineer",
        company="Example AG",
        location="Zurich",
        url=url,
        employment_type="Full-time",
        seniority="Mid",
        description=description,
    )
