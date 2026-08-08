import json
import logging
from collections.abc import Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import job_search as job_search_api
from app.api import jobs as jobs_api
from app.core.database import Base, get_db
from app.core.settings import Settings, get_settings
from app.main import app
from app.models.job_screening import JobScreeningDecisionRecord
from app.models.jobs import DiscoveredVacancyRecord, StoredJobRecord
from app.models.parsers import ParsedJob, ParserSearchResponse
from app.models.privacy import AiPrivacySettingsRecord
from app.services import job_search_execution
from app.services.job_search_execution import AI_CONSENT_WARNING, parsed_job_id
from app.services.vacancy_search import VacancySearchRunResult


@dataclass
class ApiContext:
    client: TestClient
    sessions: sessionmaker[Session]
    settings: Settings


@pytest.fixture
def api_context() -> Generator[ApiContext, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    settings = Settings(
        app_env="local",
        database_url="sqlite://",
        ai_consent_version="job-search-test-v1",
    )
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        yield ApiContext(
            client=TestClient(app),
            sessions=sessions,
            settings=settings,
        )
    finally:
        app.dependency_overrides.clear()


class FakeRunner:
    def __init__(self, result: VacancySearchRunResult) -> None:
        self.result = result
        self.requests = []

    def run(self, **kwargs) -> VacancySearchRunResult:
        self.requests.append(kwargs)
        return self.result


class FakeScreeningFacade:
    def __init__(self, decisions_by_title: dict[str, str]) -> None:
        self.decisions_by_title = decisions_by_title
        self.calls: list[list[dict[str, object]]] = []

    def screen(self, _config, jobs):
        self.calls.append(jobs)
        return [
            {
                "id": job["id"],
                "decision": self.decisions_by_title[job["title"]],
                "reasonCode": {
                    "keep": "target_role_match",
                    "reject": "excluded_role",
                    "uncertain": "insufficient_data",
                }[self.decisions_by_title[job["title"]]],
                "matchedRuleIds": [],
                "reason": f"Screened {job['title']}",
            }
            for job in jobs
        ]


def test_manual_run_uses_source_specific_queries_from_preset(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"X-Rufina-Owner-Id": "preset-run-owner"}
    runner = FakeRunner(
        VacancySearchRunResult(jobs=[], source_results={}, source_errors={})
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    profile = api_context.client.post(
        "/job-search/configs",
        headers=headers,
        json={
            "name": "Entry IT",
            "filters": {
                "schemaVersion": 2,
                "search": {"keywords": "common direct-company query"},
                "screening": {"enabled": True},
            },
        },
    ).json()
    source_config_ids: dict[str, str] = {}
    for source, keywords in (
        ("linkedin", "linkedin api query"),
        ("indeed", "indeed api query"),
        ("jobs_ch", "jobs.ch web query"),
    ):
        source_config = api_context.client.post(
            "/job-search/source-configs",
            headers=headers,
            json={
                "name": source,
                "configId": profile["id"],
                "source": source,
                "filters": {"keywords": keywords, "resultsLimit": 10},
            },
        )
        assert source_config.status_code == 201
        source_config_ids[source] = source_config.json()["id"]
    preset = api_context.client.post(
        "/job-search/presets",
        headers=headers,
        json={
            "name": "All Entry IT sources",
            "configId": profile["id"],
            "sources": ["linkedin", "indeed", "jobs_ch", "sbb"],
            "sourceConfigIds": source_config_ids,
        },
    )
    assert preset.status_code == 201

    response = api_context.client.post(
        "/job-search/run",
        headers=headers,
        json={
            "presetId": preset.json()["id"],
            "aiAnalysisEnabled": False,
        },
    )

    assert response.status_code == 200
    request = runner.requests[0]
    assert request["request"].keywords == "common direct-company query"
    assert {
        source: source_request.keywords
        for source, source_request in request["source_requests"].items()
    } == {
        "linkedin": "linkedin api query",
        "indeed": "indeed api query",
        "jobs_ch": "jobs.ch web query",
    }
    snapshot = response.json()["configSnapshot"]
    assert set(snapshot["sourceConfigs"]) == {"linkedin", "indeed", "jobs_ch"}
    assert snapshot["sourceConfigs"]["indeed"]["id"] == source_config_ids["indeed"]


def test_manual_run_uses_explicit_direct_company_source_with_common_config(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[],
            source_results={},
            source_errors={},
        )
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    response = api_context.client.post(
        "/job-search/run",
        headers={"X-Rufina-Owner-Id": "direct-company-owner"},
        json={
            "config": {
                "name": "SBB direct search",
                "filters": {
                    "schemaVersion": 2,
                    "search": {
                        "keywords": "lokführer",
                    },
                    "screening": {"enabled": True},
                },
            },
            "sources": ["linkedin", "sbb"],
            "aiAnalysisEnabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["sources"] == ["linkedin", "sbb"]
    assert runner.requests[0]["sources"] == ["linkedin", "sbb"]
    assert runner.requests[0]["request"].keywords == "lokführer"
    event = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event":"job_search.finished"' in record.message
    )
    assert event == {
        "event": "job_search.finished",
        "message": "Job search finished",
        "sources": ["LinkedIn", "SBB CFF FFS"],
        "sourceIds": ["linkedin", "sbb"],
        "newVacancies": 0,
        "jobsFound": 0,
        "status": "completed",
        "runId": response.json()["id"],
    }
    persisted_event = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event":"job_search.results_persisted"' in record.message
    )
    assert persisted_event == {
        "event": "job_search.results_persisted",
        "message": "Job search finished; new vacancies persisted",
        "sources": ["LinkedIn", "SBB CFF FFS"],
        "sourceIds": ["linkedin", "sbb"],
        "newVacancies": 0,
        "jobsFound": 0,
        "status": "completed",
        "runId": response.json()["id"],
    }


def test_experience_level_rejects_senior_jobs_from_every_source_before_ai(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = ["linkedin", "indeed", "jobs_ch", "swisscom", "die_post"]
    jobs = [
        ParsedJob(
            source=source,
            title=f"Senior Software Engineer {source}",
            company="Rufina Test AG",
            location="Zurich",
            url=f"https://example.test/{source}/senior-engineer",
            description="Build reliable backend services",
        )
        for source in sources
    ]
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=jobs,
            source_results={
                source: completed_response(
                    source,
                    [job for job in jobs if job.source == source],
                )
                for source in sources
            },
            source_errors={},
        )
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        Mock(side_effect=AssertionError("explicit senior jobs must not reach AI")),
    )

    response = api_context.client.post(
        "/job-search/run",
        headers={"X-Rufina-Owner-Id": "all-source-seniority-owner"},
        json={
            "config": {
                "name": "Entry-level search",
                "filters": {
                    "schemaVersion": 2,
                    "search": {"experienceLevel": "Entry level"},
                    "screening": {"enabled": False},
                },
            },
            "sources": sources,
            "aiAnalysisEnabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["jobsScreened"] == len(sources)
    assert response.json()["jobsRejected"] == len(sources)
    assert response.json()["jobsAdded"] == 0
    assert response.json()["jobsScreeningAiCalls"] == 0
    assert response.json()["configSnapshot"]["filters"]["screening"] == {
        "enabled": True,
        "targetRoles": [],
        "excludedRoles": [],
        "allowedSeniority": ["intern", "entry", "junior"],
        "excludedSeniority": [],
        "hardRules": [],
    }


def test_manual_run_accepts_inline_config_without_creating_schedule(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    headers = {"X-Rufina-Owner-Id": "manual-owner"}
    job = parsed_job(
        title="Manual Backend Engineer",
        url="https://www.linkedin.com/jobs/view/manual-1",
    )
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"linkedin": completed_response("linkedin", [job])},
            source_errors={},
        )
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    screening = FakeScreeningFacade({job.title: "keep"})
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: screening,
    )
    grant_ai_consent(api_context, owner_id="manual-owner")
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    response = api_context.client.post(
        "/job-search/run",
        headers=headers,
        json={
            "config": {
                "name": "Unsaved manual search",
                "filters": {
                    "keywords": "Backend Engineer",
                    "resultsLimit": 15,
                    "deduplicate": True,
                },
            },
            "sources": ["linkedin"],
            "aiAnalysisEnabled": False,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduleId"] is None
    assert payload["runType"] == "manual"
    assert payload["jobsFound"] == 1
    assert payload["jobsAlreadyKnown"] == 0
    assert payload["jobsScreened"] == 1
    assert payload["jobsPassed"] == 1
    assert payload["jobsRejected"] == 0
    assert payload["jobsUncertain"] == 0
    assert payload["jobsAdded"] == 1
    assert payload["jobsAnalyzed"] == 0
    assert payload["screeningErrors"] == 0
    assert payload["configSnapshot"]["filters"]["screening"][
        "enabled"
    ] is True
    assert payload["configSnapshot"]["filters"]["screening"][
        "targetRoles"
    ] == ["Backend Engineer"]
    assert len(screening.calls) == 1
    assert payload["configSnapshot"]["name"] == "Unsaved manual search"
    assert runner.requests[0]["wait_for_snapshots"] is True
    assert runner.requests[0]["request"].results_limit == 15
    assert api_context.client.get("/job-search/schedules", headers=headers).json() == []
    assert [record.data["title"] for record in stored_jobs(
        api_context.sessions,
        owner_id="manual-owner",
    )] == ["Manual Backend Engineer"]
    progress_event = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event":"job_screening.progress"' in record.message
    )
    assert progress_event["processed"] == 1
    assert progress_event["total"] == 1
    assert progress_event["matchedConfig"] == 1
    assert progress_event["rejected"] == 0


def test_manual_parser_run_persists_and_analyzes_only_accepted_vacancies(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "manual-parser-screening-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    accepted = parsed_job(
        title="Product Manager",
        url="https://www.linkedin.com/jobs/view/manual-accepted",
    )
    rejected = parsed_job(
        title="Cashier",
        url="https://www.linkedin.com/jobs/view/manual-rejected",
    )
    jobs = [accepted, rejected]
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=jobs,
            source_results={"linkedin": completed_response("linkedin", jobs)},
            source_errors={},
        )
    )
    screening = FakeScreeningFacade(
        {
            accepted.title: "keep",
            rejected.title: "reject",
        }
    )
    analyzed: list[list[str]] = []

    def capture_analysis(_db, *, jobs, **_kwargs):
        analyzed.append([job["title"] for job in jobs])
        return None

    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: screening,
    )
    monkeypatch.setattr(
        job_search_execution,
        "match_new_jobs_if_allowed",
        capture_analysis,
    )
    grant_ai_consent(api_context, owner_id=owner_id)

    response = api_context.client.post(
        "/job-search/run",
        headers=headers,
        json={
            "config": {
                "name": "Manual Product search",
                "filters": {
                    "keywords": "Product Manager",
                    "location": "Zurich",
                },
            },
            "sources": ["linkedin"],
            "aiAnalysisEnabled": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["jobsScreened"] == 2
    assert response.json()["jobsPassed"] == 1
    assert response.json()["jobsRejected"] == 1
    assert response.json()["jobsAdded"] == 1
    assert response.json()["jobsAnalyzed"] == 1
    assert analyzed == [["Product Manager"]]
    assert [
        item["data"]["title"]
        for item in api_context.client.get("/jobs", headers=headers).json()
    ] == ["Product Manager"]
    assert {entry["title"] for entry in api_context.client.get(
        "/job-search/screening-audit",
        headers=headers,
    ).json()} == {"Product Manager", "Cashier"}
    rejected_id = parsed_job_id(rejected, index=1)
    rejected_payload = {
        "jobs": [
            {
                "id": rejected_id,
                "data": {
                    "id": rejected_id,
                    **imported_stored_job(
                        "Cashier",
                        source="linkedin",
                    ),
                },
            }
        ]
    }
    assert api_context.client.post(
        "/jobs/ai-match",
        headers=headers,
        json=rejected_payload,
    ).json() == []
    async_match = api_context.client.post(
        "/jobs/ai-match/run",
        headers=headers,
        json=rejected_payload,
    )
    assert async_match.status_code == 202
    assert async_match.json()["status"] == "completed"


def test_manual_screening_persists_and_matches_only_keep_and_reuses_cache(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "screening-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    keep = parsed_job(
        title="Target Software Engineer",
        url="https://www.linkedin.com/jobs/view/screening-keep",
    )
    reject = parsed_job(
        title="Rejected Sales Manager",
        url="https://www.linkedin.com/jobs/view/screening-reject",
    )
    uncertain = parsed_job(
        title="Unclear Specialist",
        url="https://www.linkedin.com/jobs/view/screening-uncertain",
    )
    jobs = [keep, reject, uncertain]
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=jobs,
            source_results={"linkedin": completed_response("linkedin", jobs)},
            source_errors={},
        )
    )
    facade = FakeScreeningFacade(
        {
            keep.title: "keep",
            reject.title: "reject",
            uncertain.title: "uncertain",
        }
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: facade,
    )
    matched_batches: list[list[dict[str, object]]] = []

    def capture_new_jobs(_db, *, jobs, **_kwargs):
        matched_batches.append(jobs)
        return None

    monkeypatch.setattr(
        job_search_execution,
        "match_new_jobs_if_allowed",
        capture_new_jobs,
    )
    grant_ai_consent(api_context, owner_id=owner_id)
    config_id, schedule_id = create_search(
        api_context.client,
        headers,
        filters=screening_filters(),
    )

    first = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    second = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["jobsFound"] == 3
    assert first.json()["jobsAlreadyKnown"] == 0
    assert first.json()["jobsDiscoveredNew"] == 3
    assert first.json()["jobsDiscoveredUpdated"] == 0
    assert first.json()["jobsAlreadyObserved"] == 0
    assert first.json()["jobsScreeningAiCalls"] == 1
    assert first.json()["jobsScreened"] == 3
    assert first.json()["jobsPassed"] == 1
    assert first.json()["jobsRejected"] == 1
    assert first.json()["jobsUncertain"] == 1
    assert first.json()["jobsAdded"] == 1
    assert first.json()["jobsAnalyzed"] == 1
    assert first.json()["screeningErrors"] == 0
    assert first.json()["warning"] is None
    assert [job["title"] for job in matched_batches[0]] == [keep.title]
    records = stored_jobs(
        api_context.sessions,
        owner_id=owner_id,
    )
    assert [record.data["title"] for record in records] == [keep.title]
    stored_keep = records[0]
    assert stored_keep.search_config_id == config_id
    assert stored_keep.search_config_version
    assert len(stored_keep.screening_config_hash or "") == 64
    assert stored_keep.screening_config_snapshot == {
        "enabled": True,
        "targetRoles": ["Software Engineer"],
        "excludedRoles": [],
        "allowedSeniority": [],
        "excludedSeniority": [],
        "hardRules": [],
    }
    assert stored_keep.data["searchConfigId"] == config_id
    assert (
        stored_keep.data["searchConfigVersion"]
        == stored_keep.search_config_version
    )
    assert (
        stored_keep.data["screeningConfigHash"]
        == stored_keep.screening_config_hash
    )
    assert (
        stored_keep.data["screeningConfigSnapshot"]
        == stored_keep.screening_config_snapshot
    )
    jobs_response = api_context.client.get("/jobs", headers=headers)
    assert jobs_response.status_code == 200
    visible_keep = jobs_response.json()[0]["data"]
    assert visible_keep["searchConfigId"] == config_id
    assert visible_keep["searchConfigVersion"] == stored_keep.search_config_version
    assert visible_keep["screeningConfigHash"] == stored_keep.screening_config_hash
    assert (
        visible_keep["screeningConfigSnapshot"]
        == stored_keep.screening_config_snapshot
    )
    assert len(facade.calls) == 1
    assert {job["title"] for job in facade.calls[0]} == {
        keep.title,
        reject.title,
        uncertain.title,
    }
    assert set(facade.calls[0][0]) == {
        "id",
        "title",
        "company",
        "location",
        "description",
        "employmentType",
        "seniority",
        "source",
        "postedAt",
        "salaryMin",
        "salaryMax",
        "salaryCurrency",
    }

    assert second.status_code == 200
    assert second.json()["jobsAlreadyKnown"] == 1
    assert second.json()["jobsDiscoveredNew"] == 0
    assert second.json()["jobsDiscoveredUpdated"] == 0
    assert second.json()["jobsAlreadyObserved"] == 3
    assert second.json()["jobsScreeningAiCalls"] == 0
    assert second.json()["jobsScreened"] == 2
    assert second.json()["jobsPassed"] == 0
    assert second.json()["jobsRejected"] == 1
    assert second.json()["jobsUncertain"] == 1
    assert second.json()["jobsAdded"] == 0
    assert second.json()["jobsAnalyzed"] == 0
    assert len(facade.calls) == 1
    assert matched_batches[1] == []

    with api_context.sessions() as db:
        inventory = list(
            db.scalars(
                select(DiscoveredVacancyRecord).where(
                    DiscoveredVacancyRecord.owner_id == owner_id
                )
            ).all()
        )
        decisions = list(
            db.scalars(
                select(JobScreeningDecisionRecord)
                .where(JobScreeningDecisionRecord.owner_id == owner_id)
            ).all()
        )
    assert len(inventory) == 3
    assert {record.id for record in inventory} == {
        parsed_job_id(job, index=index) for index, job in enumerate(jobs)
    }
    assert all(record.availability == "active" for record in inventory)
    assert len(decisions) == 3
    assert {decision.decision for decision in decisions} == {
        "keep",
        "reject",
        "uncertain",
    }


def test_screening_audit_is_owner_scoped_rechecks_and_allows_without_full_match(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "audit-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    other_headers = {"X-Rufina-Owner-Id": "other-owner"}
    cashier = parsed_job(
        title="Cashier",
        url="https://www.linkedin.com/jobs/view/audit-cashier",
    )
    salesperson = parsed_job(
        title="Salesperson",
        url="https://www.linkedin.com/jobs/view/audit-salesperson",
    )
    jobs = [cashier, salesperson]
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=jobs,
            source_results={"linkedin": completed_response("linkedin", jobs)},
            source_errors={},
        )
    )

    class MutableScreeningFacade:
        def __init__(self) -> None:
            self.allowed_titles: set[str] = set()
            self.calls: list[list[str]] = []

        def screen(self, _config, compact_jobs):
            self.calls.append([job["title"] for job in compact_jobs])
            return [
                {
                    "id": job["id"],
                    "decision": (
                        "keep"
                        if job["title"] in self.allowed_titles
                        else "reject"
                    ),
                    "reasonCode": (
                        "target_role_match"
                        if job["title"] in self.allowed_titles
                        else "excluded_role"
                    ),
                    "matchedRuleIds": (
                        []
                        if job["title"] in self.allowed_titles
                        else ["rule-1"]
                    ),
                    "reason": (
                        "Product responsibility now matches the config"
                        if job["title"] in self.allowed_titles
                        else f"{job['title']} is explicitly excluded"
                    ),
                }
                for job in compact_jobs
            ]

    facade = MutableScreeningFacade()
    expensive_match = Mock(
        side_effect=AssertionError("audit action reached full AI Match")
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: facade,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_vacancy_matching_ai_facade",
        expensive_match,
    )
    grant_ai_consent(api_context, owner_id=owner_id)
    filters = screening_filters()
    filters["screening"]["hardRules"] = [
        {
            "id": "rule-1",
            "field": "title",
            "operator": "contains",
            "value": "Cashier",
        }
    ]
    _, schedule_id = create_search(
        api_context.client,
        headers,
        filters=filters,
    )

    run = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert run.status_code == 200
    assert run.json()["jobsRejected"] == 2
    assert api_context.client.get("/jobs", headers=headers).json() == []
    assert expensive_match.call_count == 0

    audit = api_context.client.get(
        "/job-search/screening-audit",
        headers=headers,
    )
    assert audit.status_code == 200
    entries = audit.json()
    assert {entry["title"] for entry in entries} == {
        "Cashier",
        "Salesperson",
    }
    cashier_entry = next(
        entry for entry in entries if entry["title"] == "Cashier"
    )
    salesperson_entry = next(
        entry for entry in entries if entry["title"] == "Salesperson"
    )
    assert cashier_entry["reason"] == "Cashier is explicitly excluded"
    assert cashier_entry["matchedRuleIds"] == ["rule-1"]
    assert cashier_entry["configId"]
    assert cashier_entry["model"] == api_context.settings.job_screening_model
    assert cashier_entry["checkedAt"]
    assert cashier_entry["canRecheck"] is True
    assert cashier_entry["canAllowManually"] is True
    assert api_context.client.get(
        "/job-search/screening-audit",
        headers=other_headers,
    ).json() == []
    assert api_context.client.post(
        f"/job-search/screening-audit/{cashier_entry['id']}/recheck",
        headers=other_headers,
    ).status_code == 404

    facade.allowed_titles.add("Cashier")
    rechecked = api_context.client.post(
        f"/job-search/screening-audit/{cashier_entry['id']}/recheck",
        headers=headers,
    )
    assert rechecked.status_code == 200
    assert rechecked.json()["decision"] == "keep"
    assert len(facade.calls) == 2

    allowed = api_context.client.post(
        f"/job-search/screening-audit/{salesperson_entry['id']}/allow",
        headers=headers,
    )
    assert allowed.status_code == 200
    assert allowed.json()["manuallyAllowedAt"]
    assert allowed.json()["canAllowManually"] is False
    assert {
        item["data"]["title"]
        for item in api_context.client.get("/jobs", headers=headers).json()
    } == {"Cashier", "Salesperson"}
    assert expensive_match.call_count == 0


def test_inventory_rescreens_rejected_vacancy_when_cache_identity_changes(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "inventory-rescreen-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    job = parsed_job(
        title="Rejected Platform Engineer",
        url="https://www.linkedin.com/jobs/view/inventory-rescreen",
    )
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"linkedin": completed_response("linkedin", [job])},
            source_errors={},
        )
    )
    facade = FakeScreeningFacade({job.title: "reject"})
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: facade,
    )
    grant_ai_consent(api_context, owner_id=owner_id)
    config_id, schedule_id = create_search(
        api_context.client,
        headers,
        filters=screening_filters(),
    )

    first = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    unchanged = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert first.json()["jobsScreeningAiCalls"] == 1
    assert unchanged.json()["jobsScreeningAiCalls"] == 0
    assert len(facade.calls) == 1

    changed_job = job.model_copy(
        update={"description": "Materially changed vacancy description"}
    )
    runner.result = VacancySearchRunResult(
        jobs=[changed_job],
        source_results={
            "linkedin": completed_response("linkedin", [changed_job])
        },
        source_errors={},
    )
    changed = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert changed.json()["jobsDiscoveredUpdated"] == 1
    assert changed.json()["jobsScreeningAiCalls"] == 1

    changed_filters = screening_filters()
    changed_filters["screening"]["targetRoles"] = ["Platform Engineer"]
    config_update = api_context.client.patch(
        f"/job-search/configs/{config_id}",
        headers=headers,
        json={"filters": changed_filters},
    )
    assert config_update.status_code == 200
    changed_config = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert changed_config.json()["jobsScreeningAiCalls"] == 1

    monkeypatch.setattr(
        api_context.settings,
        "job_screening_model",
        "inventory-test-model-v2",
    )
    changed_model = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert changed_model.json()["jobsScreeningAiCalls"] == 1

    monkeypatch.setattr(
        job_search_execution,
        "JOB_SCREENING_PROMPT_VERSION",
        "job-screening-prompt-inventory-test-v2",
    )
    changed_prompt = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert changed_prompt.json()["jobsScreeningAiCalls"] == 1
    assert len(facade.calls) == 5
    assert api_context.client.get("/jobs", headers=headers).json() == []

    with api_context.sessions() as db:
        decisions = list(
            db.scalars(
                select(JobScreeningDecisionRecord).where(
                    JobScreeningDecisionRecord.owner_id == owner_id
                )
            ).all()
        )
        inventory = list(
            db.scalars(
                select(DiscoveredVacancyRecord).where(
                    DiscoveredVacancyRecord.owner_id == owner_id
                )
            ).all()
        )
    assert len(decisions) == 5
    assert len({decision.vacancy_hash for decision in decisions}) == 2
    assert len({decision.config_hash for decision in decisions}) == 2
    assert len({decision.model for decision in decisions}) == 2
    assert len({decision.prompt_version for decision in decisions}) == 2
    assert len(inventory) == 1
    assert inventory[0].data["description"] == changed_job.description


def test_final_screening_matrix_only_persists_and_analyzes_entry_product_manager(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "screening-matrix-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    jobs = [
        parsed_job(
            title="Cashier",
            url="https://www.linkedin.com/jobs/view/matrix-cashier",
        ),
        parsed_job(
            title="Salesperson",
            url="https://www.linkedin.com/jobs/view/matrix-salesperson",
        ),
        ParsedJob(
            source="linkedin",
            title="Senior Product Manager",
            company="Senior AG",
            seniority="senior",
            description="Lead the product organization",
            url="https://www.linkedin.com/jobs/view/matrix-senior-pm",
        ),
        ParsedJob(
            source="linkedin",
            title="Product Manager",
            company="Product AG",
            seniority="entry",
            description="Own product discovery and delivery",
            url="https://www.linkedin.com/jobs/view/matrix-entry-pm",
        ),
    ]
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=jobs,
            source_results={"linkedin": completed_response("linkedin", jobs)},
            source_errors={},
        )
    )

    class MatrixScreeningFacade:
        def screen(self, _config, compact_jobs):
            decisions = []
            for job in compact_jobs:
                if job["title"] == "Product Manager":
                    decision = "keep"
                    reason_code = "target_role_match"
                elif job["title"] == "Senior Product Manager":
                    decision = "reject"
                    reason_code = "seniority_not_allowed"
                else:
                    decision = "reject"
                    reason_code = "excluded_role"
                decisions.append(
                    {
                        "id": job["id"],
                        "decision": decision,
                        "reasonCode": reason_code,
                        "matchedRuleIds": [],
                        "reason": f"Matrix decision for {job['title']}",
                    }
                )
            return decisions

    analyzed_batches: list[list[str]] = []

    def capture_analysis(_db, *, jobs, **_kwargs):
        analyzed_batches.append([job["title"] for job in jobs])
        return None

    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: MatrixScreeningFacade(),
    )
    monkeypatch.setattr(
        job_search_execution,
        "match_new_jobs_if_allowed",
        capture_analysis,
    )
    grant_ai_consent(api_context, owner_id=owner_id)
    filters = screening_filters()
    filters["search"]["keywords"] = "Product Manager"
    filters["screening"] = {
        "enabled": True,
        "targetRoles": ["Product Manager"],
        "excludedRoles": ["Cashier", "Salesperson"],
        "allowedSeniority": ["entry"],
        "excludedSeniority": ["senior"],
        "hardRules": [],
    }
    _, schedule_id = create_search(
        api_context.client,
        headers,
        filters=filters,
    )

    response = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["jobsPassed"] == 1
    assert response.json()["jobsRejected"] == 3
    assert response.json()["jobsAdded"] == 1
    assert response.json()["jobsAnalyzed"] == 1
    assert analyzed_batches == [["Product Manager"]]
    visible_titles = [
        item["data"]["title"]
        for item in api_context.client.get("/jobs", headers=headers).json()
    ]
    assert visible_titles == ["Product Manager"]
    assert "Cashier" not in visible_titles
    assert "Salesperson" not in visible_titles
    assert "Senior Product Manager" not in visible_titles


def test_screening_without_consent_is_uncertain_and_never_calls_models(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "screening-no-consent-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    job = parsed_job(
        title="Product Manager",
        url="https://www.linkedin.com/jobs/view/no-consent-pm",
    )
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"linkedin": completed_response("linkedin", [job])},
            source_errors={},
        )
    )
    cheap_model = Mock(
        side_effect=AssertionError("screening model called without consent")
    )
    expensive_model = Mock(
        side_effect=AssertionError("full match called without consent")
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        cheap_model,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_vacancy_matching_ai_facade",
        expensive_model,
    )
    _, schedule_id = create_search(
        api_context.client,
        headers,
        filters=screening_filters(),
    )

    response = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["jobsUncertain"] == 1
    assert response.json()["screeningErrors"] == 1
    assert response.json()["jobsAdded"] == 0
    assert response.json()["jobsAnalyzed"] == 0
    assert "consent is missing" in response.json()["warning"]
    assert api_context.client.get("/jobs", headers=headers).json() == []
    assert cheap_model.call_count == 0
    assert expensive_model.call_count == 0
    audit = api_context.client.get(
        "/job-search/screening-audit",
        headers=headers,
    ).json()
    assert len(audit) == 1
    assert audit[0]["decision"] == "uncertain"
    assert audit[0]["reasonCode"] == "screening_error"
    with api_context.sessions() as db:
        inventory = list(
            db.scalars(
                select(DiscoveredVacancyRecord).where(
                    DiscoveredVacancyRecord.owner_id == owner_id
                )
            ).all()
        )
    assert len(inventory) == 1
    assert inventory[0].data["title"] == job.title

    retry_facade = FakeScreeningFacade({job.title: "reject"})
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: retry_facade,
    )
    grant_ai_consent(api_context, owner_id=owner_id)
    retry = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    assert retry.status_code == 200
    assert retry.json()["jobsScreeningAiCalls"] == 1
    assert retry.json()["jobsRejected"] == 1
    assert len(retry_facade.calls) == 1
    assert api_context.client.get("/jobs", headers=headers).json() == []


def test_manual_screening_error_is_partial_and_fail_closed(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "screening-error-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    job = parsed_job(
        title="Unchecked Engineer",
        url="https://www.linkedin.com/jobs/view/screening-error",
    )
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"linkedin": completed_response("linkedin", [job])},
            source_errors={},
        )
    )

    class FailingScreeningFacade:
        def screen(self, _config, _jobs):
            raise RuntimeError("screening backend unavailable")

    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: FailingScreeningFacade(),
    )
    matched_batches: list[list[dict[str, object]]] = []

    def capture_new_jobs(_db, *, jobs, **_kwargs):
        matched_batches.append(jobs)
        return None

    monkeypatch.setattr(
        job_search_execution,
        "match_new_jobs_if_allowed",
        capture_new_jobs,
    )
    grant_ai_consent(api_context, owner_id=owner_id)
    _, schedule_id = create_search(
        api_context.client,
        headers,
        filters=screening_filters(),
    )

    response = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["jobsScreened"] == 1
    assert payload["jobsPassed"] == 0
    assert payload["jobsRejected"] == 0
    assert payload["jobsUncertain"] == 1
    assert payload["jobsAdded"] == 0
    assert payload["jobsAnalyzed"] == 0
    assert payload["screeningErrors"] == 1
    assert "unverified vacancies were skipped" in payload["warning"]
    assert stored_jobs(api_context.sessions, owner_id=owner_id) == []
    assert matched_batches == [[]]
    with api_context.sessions() as db:
        decision = db.scalar(
            select(JobScreeningDecisionRecord).where(
                JobScreeningDecisionRecord.owner_id == owner_id
            )
        )
    assert decision is not None
    assert decision.decision == "uncertain"
    assert decision.reason_code == "screening_error"
    audit = api_context.client.get(
        "/job-search/screening-audit",
        headers=headers,
    ).json()
    assert len(audit) == 1
    assert audit[0]["decision"] == "uncertain"
    assert audit[0]["reasonCode"] == "screening_error"


def test_existing_imported_jobs_require_dry_run_and_can_be_rescreened(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "rescreen-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    config_response = api_context.client.post(
        "/job-search/configs",
        headers=headers,
        json={
            "name": "Software roles",
            "filters": screening_filters(),
        },
    )
    assert config_response.status_code == 201
    config_id = config_response.json()["id"]
    grant_ai_consent(api_context, owner_id=owner_id)

    with api_context.sessions() as db:
        db.add_all(
            [
                StoredJobRecord(
                    owner_id=owner_id,
                    id="linkedin-software",
                    data=imported_stored_job(
                        "Software Engineer",
                        source="linkedin",
                    ),
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="indeed-sales",
                    data=imported_stored_job(
                        "Sales Manager",
                        source="indeed",
                    ),
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="jobs_ch-unclear",
                    data=imported_stored_job(
                        "Unclear Specialist",
                        source="jobs_ch",
                    ),
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="linkedin-old-software",
                    data=imported_stored_job(
                        "Old Software Engineer",
                        source="linkedin",
                    ),
                    status="screened_out",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="manual-job-1",
                    data={
                        "id": "manual-job-1",
                        "title": "Manual Sales Manager",
                        "company": "Manual AG",
                        "logo": "manual",
                    },
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="linkedin-dismissed",
                    data=imported_stored_job(
                        "Dismissed Software Engineer",
                        source="linkedin",
                    ),
                    status="dismissed",
                ),
            ]
        )
        db.commit()

    class ConfigAwareScreeningFacade:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def screen(self, screening_config, jobs):
            self.calls.append([job["id"] for job in jobs])
            sales_allowed = "Sales Manager" in screening_config.target_roles
            decisions = []
            for job in jobs:
                title = job["title"]
                if title == "Unclear Specialist":
                    decision = "uncertain"
                    reason_code = "insufficient_data"
                elif title == "Sales Manager" and not sales_allowed:
                    decision = "reject"
                    reason_code = "excluded_role"
                else:
                    decision = "keep"
                    reason_code = "target_role_match"
                decisions.append(
                    {
                        "id": job["id"],
                        "decision": decision,
                        "reasonCode": reason_code,
                        "matchedRuleIds": [],
                        "reason": f"Screened {title}",
                    }
                )
            return decisions

    facade = ConfigAwareScreeningFacade()
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: facade,
    )

    skipped_dry_run = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={"dryRun": True},
    )
    assert skipped_dry_run.status_code == 200
    skipped_preview = skipped_dry_run.json()
    assert skipped_preview["eligibleJobs"] == 4
    assert skipped_preview["jobsScreened"] == 0
    assert skipped_preview["jobsSkipped"] == 4
    assert skipped_preview["jobsUsingFallback"] == 0
    assert skipped_preview["skippedReasons"] == {
        "missing_source_config": 4,
    }
    assert skipped_preview["configGroups"] == []
    assert "no fallback was selected" in skipped_preview["warning"]
    assert facade.calls == []

    dry_run = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": True,
            "useSelectedConfigAsFallback": True,
        },
    )

    assert dry_run.status_code == 200
    preview = dry_run.json()
    assert preview["dryRun"] is True
    assert preview["applied"] is False
    assert preview["eligibleJobs"] == 4
    assert preview["jobsScreened"] == 4
    assert preview["jobsPassed"] == 2
    assert preview["jobsRejected"] == 1
    assert preview["jobsUncertain"] == 1
    assert preview["jobsSkipped"] == 0
    assert preview["jobsUsingFallback"] == 4
    assert preview["skippedReasons"] == {}
    assert preview["configGroups"] == [
        {
            "configId": config_id,
            "configHash": preview["configHash"],
            "usedAsFallback": True,
            "fallbackJobs": 4,
            "jobs": 4,
            "jobsScreened": 4,
            "jobsPassed": 2,
            "jobsRejected": 1,
            "jobsUncertain": 1,
            "screeningErrors": 0,
        }
    ]
    assert preview["jobsToHide"] == 2
    assert preview["jobsToRestore"] == 1
    assert preview["jobsHidden"] == 0
    assert preview["jobsRestored"] == 0
    assert len(preview["confirmationToken"]) == 64
    assert stored_job_statuses(api_context, owner_id=owner_id) == {
        "indeed-sales": "active",
        "jobs_ch-unclear": "active",
        "linkedin-dismissed": "dismissed",
        "linkedin-old-software": "screened_out",
        "linkedin-software": "active",
        "manual-job-1": "active",
    }

    unconfirmed = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": False,
            "useSelectedConfigAsFallback": True,
        },
    )
    assert unconfirmed.status_code == 409

    applied = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": False,
            "confirm": True,
            "useSelectedConfigAsFallback": True,
            "confirmationToken": preview["confirmationToken"],
        },
    )

    assert applied.status_code == 200
    assert applied.json()["jobsHidden"] == 2
    assert applied.json()["jobsRestored"] == 1
    assert len(facade.calls) == 1
    statuses = stored_job_statuses(api_context, owner_id=owner_id)
    assert statuses["indeed-sales"] == "screened_out"
    assert statuses["jobs_ch-unclear"] == "screened_out"
    assert statuses["linkedin-old-software"] == "active"
    assert statuses["manual-job-1"] == "active"
    assert statuses["linkedin-dismissed"] == "dismissed"
    records_by_id = {
        record.id: record
        for record in stored_jobs(
            api_context.sessions,
            owner_id=owner_id,
        )
    }
    for job_id in (
        "indeed-sales",
        "jobs_ch-unclear",
        "linkedin-old-software",
        "linkedin-software",
    ):
        record = records_by_id[job_id]
        assert record.search_config_id == config_id
        assert record.search_config_version
        assert len(record.screening_config_hash or "") == 64
        assert record.screening_config_snapshot
        assert record.data["searchConfigId"] == config_id
    assert records_by_id["manual-job-1"].search_config_id is None
    assert "searchConfigId" not in records_by_id["manual-job-1"].data
    visible_ids = {
        item["id"]
        for item in api_context.client.get("/jobs", headers=headers).json()
    }
    assert visible_ids == {
        "linkedin-software",
        "linkedin-old-software",
        "manual-job-1",
    }
    stale_client_upsert = api_context.client.put(
        "/jobs",
        headers=headers,
        json={
            "jobs": [
                {
                    "id": "indeed-sales",
                    "data": imported_stored_job(
                        "Sales Manager",
                        source="indeed",
                    ),
                }
            ]
        },
    )
    assert stale_client_upsert.status_code == 200
    assert "indeed-sales" not in {
        item["id"] for item in stale_client_upsert.json()
    }
    assert stored_job_statuses(
        api_context,
        owner_id=owner_id,
    )["indeed-sales"] == "screened_out"

    full_match = Mock(
        side_effect=AssertionError("hidden job reached full AI Match")
    )
    monkeypatch.setattr(
        jobs_api,
        "create_vacancy_matching_ai_facade",
        full_match,
    )
    hidden_match = api_context.client.post(
        "/jobs/ai-match",
        headers=headers,
        json={
            "jobs": [
                {
                    "id": "indeed-sales",
                    "data": imported_stored_job(
                        "Sales Manager",
                        source="indeed",
                    ),
                }
            ]
        },
    )
    assert hidden_match.status_code == 200
    assert hidden_match.json() == []
    hidden_async_match = api_context.client.post(
        "/jobs/ai-match/run",
        headers=headers,
        json={
            "jobs": [
                {
                    "id": "jobs_ch-unclear",
                    "data": imported_stored_job(
                        "Unclear Specialist",
                        source="jobs_ch",
                    ),
                }
            ]
        },
    )
    assert hidden_async_match.status_code == 202
    assert hidden_async_match.json()["status"] == "completed"
    assert full_match.call_count == 0

    changed_filters = screening_filters()
    changed_filters["screening"]["targetRoles"] = [
        "Software Engineer",
        "Sales Manager",
    ]
    changed = api_context.client.patch(
        f"/job-search/configs/{config_id}",
        headers=headers,
        json={"filters": changed_filters},
    )
    assert changed.status_code == 200

    changed_preview = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": True,
            "useSelectedConfigAsFallback": True,
        },
    )
    assert changed_preview.status_code == 200
    assert changed_preview.json()["jobsToHide"] == 0
    assert changed_preview.json()["jobsToRestore"] == 1
    assert len(facade.calls) == 2
    stale_confirmation = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": False,
            "confirm": True,
            "useSelectedConfigAsFallback": True,
            "confirmationToken": preview["confirmationToken"],
        },
    )
    assert stale_confirmation.status_code == 409
    changed_apply = api_context.client.post(
        f"/job-search/configs/{config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": False,
            "confirm": True,
            "useSelectedConfigAsFallback": True,
            "confirmationToken": changed_preview.json()["confirmationToken"],
        },
    )
    assert changed_apply.status_code == 200
    assert changed_apply.json()["jobsRestored"] == 1
    assert stored_job_statuses(
        api_context,
        owner_id=owner_id,
    )["indeed-sales"] == "active"


def test_rescreen_groups_jobs_by_original_config_and_uses_explicit_fallback(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id = "grouped-rescreen-owner"
    headers = {"X-Rufina-Owner-Id": owner_id}
    software_config_id, _ = create_search(
        api_context.client,
        headers,
        filters=screening_filters(),
    )
    sales_filters = screening_filters()
    sales_filters["screening"]["targetRoles"] = ["Sales Manager"]
    sales_config_id, _ = create_search(
        api_context.client,
        headers,
        filters=sales_filters,
    )
    grant_ai_consent(api_context, owner_id=owner_id)

    with api_context.sessions() as db:
        db.add_all(
            [
                StoredJobRecord(
                    owner_id=owner_id,
                    id="linkedin-grouped-software",
                    data=imported_stored_job(
                        "Software Engineer",
                        source="linkedin",
                    ),
                    search_config_id=software_config_id,
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="indeed-grouped-sales",
                    data=imported_stored_job(
                        "Sales Manager",
                        source="indeed",
                    ),
                    search_config_id=sales_config_id,
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="linkedin-grouped-legacy",
                    data=imported_stored_job(
                        "Legacy Software Engineer",
                        source="linkedin",
                    ),
                    status="active",
                ),
                StoredJobRecord(
                    owner_id=owner_id,
                    id="jobs_ch-grouped-missing-config",
                    data=imported_stored_job(
                        "Cashier",
                        source="jobs_ch",
                    ),
                    search_config_id="deleted-config",
                    status="active",
                ),
            ]
        )
        db.commit()

    class GroupAwareScreeningFacade:
        def __init__(self) -> None:
            self.calls: list[tuple[tuple[str, ...], list[str]]] = []

        def screen(self, screening_config, jobs):
            roles = tuple(screening_config.target_roles)
            self.calls.append((roles, [job["id"] for job in jobs]))
            return [
                {
                    "id": job["id"],
                    "decision": (
                        "keep"
                        if any(role in job["title"] for role in roles)
                        else "reject"
                    ),
                    "reasonCode": (
                        "target_role_match"
                        if any(role in job["title"] for role in roles)
                        else "target_role_mismatch"
                    ),
                    "matchedRuleIds": [],
                    "reason": f"Screened with {', '.join(roles)}",
                }
                for job in jobs
            ]

    facade = GroupAwareScreeningFacade()
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _settings: facade,
    )

    without_fallback = api_context.client.post(
        f"/job-search/configs/{software_config_id}/rescreen",
        headers=headers,
        json={"dryRun": True},
    )
    assert without_fallback.status_code == 200
    assert without_fallback.json()["eligibleJobs"] == 4
    assert without_fallback.json()["jobsScreened"] == 2
    assert without_fallback.json()["jobsPassed"] == 2
    assert without_fallback.json()["jobsSkipped"] == 2
    assert without_fallback.json()["jobsUsingFallback"] == 0
    assert without_fallback.json()["skippedReasons"] == {
        "missing_source_config": 1,
        "source_config_not_found": 1,
    }
    calls_by_roles = {
        roles: ids
        for roles, ids in facade.calls
    }
    assert calls_by_roles == {
        ("Software Engineer",): ["linkedin-grouped-software"],
        ("Sales Manager",): ["indeed-grouped-sales"],
    }

    with_fallback = api_context.client.post(
        f"/job-search/configs/{software_config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": True,
            "useSelectedConfigAsFallback": True,
        },
    )
    assert with_fallback.status_code == 200
    fallback_preview = with_fallback.json()
    assert fallback_preview["jobsScreened"] == 4
    assert fallback_preview["jobsPassed"] == 3
    assert fallback_preview["jobsRejected"] == 1
    assert fallback_preview["jobsSkipped"] == 0
    assert fallback_preview["jobsUsingFallback"] == 2
    groups = {
        group["configId"]: group
        for group in fallback_preview["configGroups"]
    }
    assert groups[software_config_id]["jobs"] == 3
    assert groups[software_config_id]["usedAsFallback"] is True
    assert groups[software_config_id]["fallbackJobs"] == 2
    assert groups[sales_config_id]["jobs"] == 1
    assert groups[sales_config_id]["usedAsFallback"] is False
    assert groups[sales_config_id]["fallbackJobs"] == 0

    applied = api_context.client.post(
        f"/job-search/configs/{software_config_id}/rescreen",
        headers=headers,
        json={
            "dryRun": False,
            "confirm": True,
            "useSelectedConfigAsFallback": True,
            "confirmationToken": fallback_preview["confirmationToken"],
        },
    )
    assert applied.status_code == 200
    records = {
        record.id: record
        for record in stored_jobs(
            api_context.sessions,
            owner_id=owner_id,
        )
    }
    assert records["linkedin-grouped-software"].search_config_id == (
        software_config_id
    )
    assert records["indeed-grouped-sales"].search_config_id == sales_config_id
    assert records["linkedin-grouped-legacy"].search_config_id == (
        software_config_id
    )
    assert records["jobs_ch-grouped-missing-config"].search_config_id == (
        software_config_id
    )
    assert records["jobs_ch-grouped-missing-config"].status == "screened_out"


def test_run_now_persists_jobs_snapshot_and_no_consent_warning(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_a = {"X-Rufina-Owner-Id": "owner-a"}
    owner_b = {"X-Rufina-Owner-Id": "owner-b"}
    job = parsed_job(
        title="Platform Engineer",
        url="https://www.linkedin.com/jobs/view/123?trackingId=ignored",
    )
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"linkedin": completed_response("linkedin", [job])},
            source_errors={},
        )
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    config_id, schedule_id = create_search(
        api_context.client,
        owner_a,
        filters={
            "keywords": "Platform Engineer",
            "location": "Zurich",
            "resultsLimit": 25,
        },
    )

    response = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=owner_a,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduleId"] == schedule_id
    assert payload["runType"] == "manual"
    assert payload["status"] == "completed"
    assert payload["jobsFound"] == 1
    assert payload["jobsAlreadyKnown"] == 0
    assert payload["jobsAdded"] == 1
    assert payload["jobsAnalyzed"] == 0
    assert payload["screeningErrors"] == 0
    assert payload["warning"] == AI_CONSENT_WARNING
    assert payload["configSnapshot"]["id"] == config_id
    normalized_config = payload["configSnapshot"]["filters"]
    assert normalized_config["schemaVersion"] == 2
    assert normalized_config["search"]["keywords"] == "Platform Engineer"
    assert normalized_config["search"]["location"] == "Zurich"
    assert normalized_config["search"]["resultsLimit"] == 25
    assert normalized_config["screening"] == {
        "enabled": False,
        "targetRoles": [],
        "excludedRoles": [],
        "allowedSeniority": [],
        "excludedSeniority": [],
        "hardRules": [],
    }
    assert runner.requests[0]["wait_for_snapshots"] is True
    assert runner.requests[0]["request"].results_limit == 25

    runs = api_context.client.get("/job-search/runs", headers=owner_a)
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()] == [payload["id"]]
    assert (
        api_context.client.get(
            "/job-search/runs",
            headers=owner_b,
        ).json()
        == []
    )

    records = stored_jobs(api_context.sessions, owner_id="owner-a")
    assert len(records) == 1
    assert records[0].status == "active"
    assert records[0].data["title"] == "Platform Engineer"
    assert "aiMatch" not in records[0].data


def test_manual_run_accepts_v2_config_and_only_sends_search_to_parser(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"X-Rufina-Owner-Id": "v2-owner"}
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[],
            source_results={"linkedin": completed_response("linkedin", [])},
            source_errors={},
        )
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    versioned_config = {
        "schemaVersion": 2,
        "search": {
            "keywords": "Product Manager",
            "location": "Zurich",
            "resultsLimit": 100,
        },
        "screening": {
            "enabled": True,
            "targetRoles": ["Product Manager"],
            "excludedRoles": [],
            "allowedSeniority": ["entry", "junior", "associate"],
            "excludedSeniority": ["senior", "lead", "director"],
            "hardRules": [],
        },
    }

    response = api_context.client.post(
        "/job-search/run",
        headers=headers,
        json={
            "config": {
                "name": "Versioned search",
                "filters": versioned_config,
            },
            "sources": ["linkedin"],
            "aiAnalysisEnabled": False,
        },
    )

    assert response.status_code == 200
    parser_request = runner.requests[0]["request"]
    assert parser_request.keywords == "Product Manager"
    assert parser_request.location == "Zurich"
    assert parser_request.results_limit == 100
    assert "screening" not in parser_request.model_dump()
    snapshot = response.json()["configSnapshot"]["filters"]
    assert snapshot["schemaVersion"] == 2
    assert snapshot["search"]["keywords"] == "Product Manager"
    assert snapshot["search"]["location"] == "Zurich"
    assert snapshot["search"]["resultsLimit"] == 100
    assert snapshot["screening"] == versioned_config["screening"]


@pytest.mark.parametrize(
    "screening",
    [
        {"enabled": "yes", "hardRules": []},
        {
            "enabled": True,
            "hardRules": [
                {
                    "field": "title",
                    "operator": "unsupported",
                    "value": "Python",
                }
            ],
        },
        {
            "enabled": True,
            "allowedSeniority": ["senior"],
            "excludedSeniority": ["senior"],
            "hardRules": [],
        },
        {
            "enabled": True,
            "allowedSeniority": ["principal"],
            "hardRules": [],
        },
    ],
)
def test_versioned_config_rejects_unknown_or_invalid_screening(
    api_context: ApiContext,
    screening: dict[str, object],
) -> None:
    response = api_context.client.post(
        "/job-search/configs",
        headers={"X-Rufina-Owner-Id": "invalid-screening-owner"},
        json={
            "name": "Invalid screening",
            "filters": {
                "schemaVersion": 2,
                "search": {"keywords": "Python"},
                "screening": screening,
            },
        },
    )

    assert response.status_code == 422


def test_versioned_config_preserves_unknown_json_fields(
    api_context: ApiContext,
) -> None:
    response = api_context.client.post(
        "/job-search/configs",
        headers={"X-Rufina-Owner-Id": "future-config-owner"},
        json={
            "name": "Forward-compatible screening",
            "filters": {
                "schemaVersion": 2,
                "futureRoot": {"mode": "preview"},
                "search": {
                    "keywords": "Python",
                    "futureSearch": ["one", "two"],
                },
                "screening": {
                    "enabled": True,
                    "targetRoles": ["Software Engineer"],
                    "excludedRoles": ["Sales Manager"],
                    "futureScreening": {"threshold": 0.8},
                    "hardRules": [
                        {
                            "field": "location",
                            "operator": "equals",
                            "value": "Zurich",
                            "futureRule": "preserve-me",
                        }
                    ],
                },
            },
        },
    )

    assert response.status_code == 201
    filters = response.json()["filters"]
    assert filters["futureRoot"] == {"mode": "preview"}
    assert filters["search"]["futureSearch"] == ["one", "two"]
    assert filters["screening"]["futureScreening"] == {"threshold": 0.8}
    assert (
        filters["screening"]["hardRules"][0]["futureRule"]
        == "preserve-me"
    )


def test_run_now_does_not_restore_existing_or_dismissed_jobs_and_matches_only_new(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"X-Rufina-Owner-Id": "dedup-owner"}
    existing = parsed_job(
        title="Existing Engineer",
        url="https://www.linkedin.com/jobs/view/existing",
    )
    dismissed = parsed_job(
        title="Dismissed Engineer",
        url="https://www.linkedin.com/jobs/view/dismissed",
    )
    new = parsed_job(
        title="New Engineer",
        url="https://www.linkedin.com/jobs/view/new",
    )
    existing_id = parsed_job_id(existing, index=0)
    dismissed_id = parsed_job_id(dismissed, index=1)
    with api_context.sessions() as db:
        db.add_all(
            [
                StoredJobRecord(
                    owner_id="dedup-owner",
                    id=existing_id,
                    data={
                        "id": existing_id,
                        "title": existing.title,
                        "company": existing.company,
                        "location": existing.location,
                        "sourceUrl": existing.url,
                    },
                    status="active",
                ),
                StoredJobRecord(
                    owner_id="dedup-owner",
                    id=dismissed_id,
                    data={"id": dismissed_id},
                    status="dismissed",
                ),
            ]
        )
        db.commit()

    result = VacancySearchRunResult(
        jobs=[existing, dismissed, new],
        source_results={"linkedin": completed_response("linkedin", [existing, dismissed, new])},
        source_errors={},
    )
    runner = FakeRunner(result)
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    matched_batches: list[list[dict[str, object]]] = []

    def capture_new_jobs(_db, *, jobs, **_kwargs):
        matched_batches.append(jobs)
        return None

    monkeypatch.setattr(
        job_search_execution,
        "match_new_jobs_if_allowed",
        capture_new_jobs,
    )
    _, schedule_id = create_search(api_context.client, headers)

    first = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )
    second = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json()["jobsFound"] == 3
    assert first.json()["jobsAlreadyKnown"] == 2
    assert first.json()["jobsAdded"] == 1
    assert first.json()["jobsAnalyzed"] == 1
    assert [job["title"] for job in matched_batches[0]] == ["New Engineer"]
    assert second.status_code == 200
    assert second.json()["jobsAlreadyKnown"] == 3
    assert second.json()["jobsAdded"] == 0
    assert second.json()["jobsAnalyzed"] == 0
    assert matched_batches[1] == []

    records = stored_jobs(api_context.sessions, owner_id="dedup-owner")
    assert len(records) == 3
    dismissed_record = next(record for record in records if record.id == dismissed_id)
    assert dismissed_record.status == "dismissed"
    assert dismissed_record.data == {"id": dismissed_id}


def test_run_now_persists_partial_source_failure(
    api_context: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = {"X-Rufina-Owner-Id": "partial-owner"}
    linkedin_job = parsed_job(
        title="Resilient Search Result",
        url="https://www.linkedin.com/jobs/view/partial-1",
    )
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[linkedin_job],
            source_results={"linkedin": completed_response("linkedin", [linkedin_job])},
            source_errors={"indeed": "Indeed snapshot failed"},
        )
    )
    monkeypatch.setattr(
        job_search_api,
        "create_vacancy_search_runner",
        lambda _settings: runner,
    )
    _, schedule_id = create_search(api_context.client, headers)

    response = api_context.client.post(
        f"/job-search/schedules/{schedule_id}/run",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "partial"
    assert response.json()["jobsFound"] == 1
    assert response.json()["jobsAdded"] == 1
    assert response.json()["sourceErrors"] == {"indeed": "Indeed snapshot failed"}
    assert len(stored_jobs(api_context.sessions, owner_id="partial-owner")) == 1


def create_search(
    client: TestClient,
    headers: dict[str, str],
    *,
    filters: dict[str, object] | None = None,
) -> tuple[str, str]:
    config_response = client.post(
        "/job-search/configs",
        headers=headers,
        json={
            "name": "Automatic Zurich search",
            "filters": filters
            or {
                "keywords": "Software Engineer",
                "location": "Zurich",
            },
        },
    )
    assert config_response.status_code == 201
    config_id = config_response.json()["id"]
    schedule_response = client.post(
        "/job-search/schedules",
        headers=headers,
        json={
            "name": "Every morning",
            "configId": config_id,
            "sources": ["linkedin", "indeed"],
            "frequency": "daily",
            "weekdays": [],
            "localTime": "08:00:00",
            "timezone": "Europe/Zurich",
            "aiAnalysisEnabled": True,
            "enabled": True,
        },
    )
    assert schedule_response.status_code == 201
    return config_id, schedule_response.json()["id"]


def screening_filters() -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "search": {
            "keywords": "Software Engineer",
            "location": "Zurich",
        },
        "screening": {
            "enabled": True,
            "targetRoles": ["Software Engineer"],
            "allowedSeniority": [],
            "excludedSeniority": [],
            "hardRules": [],
        },
    }


def imported_stored_job(
    title: str,
    *,
    source: str,
) -> dict[str, object]:
    source_label = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "jobs_ch": "jobs.ch",
    }[source]
    return {
        "title": title,
        "company": "Imported Test AG",
        "location": "Zurich",
        "type": "Full-time",
        "experience": "Mid",
        "overview": f"{title} description",
        "posted": "Today",
        "logo": source,
        "department": f"{source_label} import",
        "sourceUrl": f"https://example.test/{source}/{title}",
    }


def stored_job_statuses(
    context: ApiContext,
    *,
    owner_id: str,
) -> dict[str, str]:
    with context.sessions() as db:
        records = list(
            db.scalars(
                select(StoredJobRecord).where(
                    StoredJobRecord.owner_id == owner_id
                )
            ).all()
        )
    return {record.id: record.status for record in records}


def grant_ai_consent(context: ApiContext, *, owner_id: str) -> None:
    now = datetime.now(UTC)
    with context.sessions() as db:
        db.add(
            AiPrivacySettingsRecord(
                owner_id=owner_id,
                consent_version=context.settings.ai_consent_version,
                consent_backend=context.settings.ai_backend_mode,
                consented_at=now,
                retention_days=30,
                updated_at=now,
            )
        )
        db.commit()


def parsed_job(*, title: str, url: str) -> ParsedJob:
    return ParsedJob(
        source="linkedin",
        title=title,
        company="Rufina Test AG",
        location="Zurich",
        url=url,
        employment_type="Full-time",
        seniority="Mid-Senior level",
        description=f"{title} description",
    )


def completed_response(
    source: str,
    jobs: list[ParsedJob],
) -> ParserSearchResponse:
    return ParserSearchResponse(
        parser=source,
        status="completed",
        search_url=f"https://example.test/{source}",
        jobs=jobs,
    )


def stored_jobs(
    sessions: sessionmaker[Session],
    *,
    owner_id: str,
) -> list[StoredJobRecord]:
    with sessions() as db:
        return list(
            db.scalars(
                select(StoredJobRecord)
                .where(StoredJobRecord.owner_id == owner_id)
                .order_by(StoredJobRecord.id)
            ).all()
        )
