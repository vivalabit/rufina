from datetime import UTC, datetime, timedelta

import pytest

from sqlalchemy import select
from test_job_search_run_api import (
    ApiContext,
    FakeRunner,
    FakeScreeningFacade,
)
from test_job_search_run_api import (
    api_context as api_context,
)

from app.api import job_search as job_search_api
from app.models.job_search import JobSearchRunRecord
from app.models.jobs import DiscoveredVacancyRecord, StoredJobRecord
from app.models.parsers import ParsedJob, ParserSearchResponse
from app.services import job_search_execution
from app.services.vacancy_search import VacancySearchRunResult
from app.services.vacancy_search import VacancySearchRunner
from test_vacancy_search import CompletedParser


def vacancy(title="Backend Engineer", source="linkedin", number="1", **kwargs):
    return ParsedJob(
        title=title,
        company="Example",
        source=source,
        url=f"https://example.test/jobs/{number}",
        posted_at=datetime.now(UTC).isoformat(),
        **kwargs,
    )


def response(source, jobs):
    return ParserSearchResponse(parser=source, status="completed", search_url="", jobs=jobs)


def run_search(context, sources, session="test-session", **filters):
    result = context.client.post(
        "/job-search/run",
        json={
            "sessionId": session,
            "config": {
                "name": "Backend Switzerland",
                "filters": {
                    "schemaVersion": 2,
                    "search": filters,
                    "screening": {"enabled": True, "targetRoles": ["Backend Engineer"]},
                },
            },
            "sources": sources,
        },
    )
    assert result.status_code == 200, result.text
    return result.json()


def test_report_tracks_source_outcomes_and_is_immutable(api_context: ApiContext, monkeypatch):
    known, added, rejected = (
        vacancy(),
        vacancy("Python Engineer", number="2"),
        vacancy("Sales Manager", number="3"),
    )
    old = vacancy(number="4").model_copy(update={"posted_at": "2001-01-01T00:00:00Z"})
    duplicate = known.model_copy(update={"source": "jobs_ch"})
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[known],
            source_results={"linkedin": response("linkedin", [known])},
            source_errors={},
        )
    )
    monkeypatch.setattr(job_search_api, "create_vacancy_search_runner", lambda _: runner)
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _: FakeScreeningFacade(
            {
                "Backend Engineer": "keep",
                "Python Engineer": "keep",
                "Sales Manager": "reject",
            }
        ),
    )
    run_search(api_context, ["linkedin"], session="previous")
    runner.result = VacancySearchRunResult(
        jobs=[known, added, rejected],
        source_results={
            "linkedin": response("linkedin", [known, added, rejected, old]),
            "jobs_ch": response("jobs_ch", [duplicate]),
        },
        source_errors={"indeed": "Provider unavailable"},
        source_attempts={"linkedin": 1, "indeed": 3},
        source_durations={"linkedin": 2.5},
    )
    result = run_search(api_context, ["linkedin", "jobs_ch", "indeed"], datePosted="Past 24 hours")
    report = api_context.client.get("/job-search/history/test-session").json()["runs"][0]["report"]
    sources = {item["source"]: item for item in report["sources"]}
    assert sources["linkedin"]["received"] == 4
    assert sources["linkedin"]["firstSeen"] == 2
    assert sources["linkedin"]["known"] == 1
    assert sources["linkedin"]["filtered"] == 2
    assert sources["linkedin"]["added"] == 1
    assert sources["linkedin"]["durationSeconds"] == 2.5
    assert sources["linkedin"]["missing"] is None
    assert sources["jobs_ch"]["duplicate"] == 1
    assert sources["indeed"]["received"] is None
    assert sources["indeed"]["status"] == "failed"
    assert sources["indeed"]["attempts"] == 3
    assert {row["outcome"] for row in report["vacancies"]} == {
        "known",
        "added",
        "filtered",
        "duplicate",
    }
    assert (
        next(row for row in report["vacancies"] if row["title"] == "Sales Manager")["reason"]
        == "Screened Sales Manager"
    )
    assert result["sessionId"] == "test-session"
    assert "report" not in api_context.client.get("/job-search/runs").json()[0]
    with api_context.sessions() as db:
        for record in db.scalars(select(StoredJobRecord)).all():
            db.delete(record)
        for record in db.scalars(select(DiscoveredVacancyRecord)).all():
            record.data = {**record.data, "title": "Changed later"}
        db.commit()
    assert (
        api_context.client.get("/job-search/history/test-session").json()["runs"][0]["report"]
        == report
    )


@pytest.mark.parametrize("decision", ["keep", "error"])
def test_missing_requires_a_complete_successful_catalog(
    api_context: ApiContext, monkeypatch, decision
):
    job = vacancy(source="sbb")
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"sbb": response("sbb", [job])},
            source_errors={},
        )
    )
    monkeypatch.setattr(job_search_api, "create_vacancy_search_runner", lambda _: runner)
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _: FakeScreeningFacade({"Backend Engineer": decision}),
    )
    run_search(api_context, ["sbb"], session="initial")
    runner.result = VacancySearchRunResult(
        jobs=[],
        source_results={"sbb": response("sbb", [])},
        source_errors={"sbb": "Partial catalog"},
    )
    run_search(api_context, ["sbb"], session="partial")
    partial = api_context.client.get("/job-search/history/partial").json()["runs"][0]["report"]
    assert partial["sources"][0]["missing"] is None
    with api_context.sessions() as db:
        assert db.scalar(select(DiscoveredVacancyRecord)).availability == "active"
    runner.result = VacancySearchRunResult(
        jobs=[], source_results={"sbb": response("sbb", [])}, source_errors={}
    )
    run_search(api_context, ["sbb"], session="complete")
    complete = api_context.client.get("/job-search/history/complete").json()["runs"][0]["report"]
    assert complete["sources"][0]["missing"] == 1
    assert complete["vacancies"][0]["outcome"] == "missing"
    assert complete["vacancies"][0]["title"] == "Backend Engineer"
    run_search(api_context, ["sbb"], session="still-missing")
    assert (
        api_context.client.get("/job-search/history/still-missing").json()["runs"][0]["report"][
            "sources"
        ][0]["missing"]
        == 0
    )


def test_history_groups_paginate_and_respect_owner_and_filters(api_context: ApiContext):
    now = datetime.now(UTC)
    with api_context.sessions() as db:
        for number, session, source, owner in [
            (1, "together", "linkedin", "local-owner"),
            (2, "together", "indeed", "local-owner"),
            (3, None, "sbb", "local-owner"),
            (4, "together", "sbb", "other-owner"),
        ]:
            db.add(
                JobSearchRunRecord(
                    id=f"run-{number}",
                    session_id=session,
                    owner_id=owner,
                    run_type="manual",
                    status="completed",
                    sources=[source],
                    config_snapshot={"name": "Backend" if number == 1 else "Other"},
                    started_at=now - timedelta(minutes=number),
                    completed_at=now,
                )
            )
        db.commit()
    page = api_context.client.get("/job-search/history?limit=1").json()
    assert [run["id"] for run in page["items"][0]["runs"]] == ["run-2", "run-1"]
    assert page["nextOffset"] == 1
    next_page = api_context.client.get("/job-search/history?limit=1&offset=1").json()
    assert next_page["items"][0]["id"] == "run-3"
    assert next_page["nextOffset"] is None
    for filters in ("source=linkedin", "query=Backend", "runType=manual&source=indeed"):
        items = api_context.client.get(f"/job-search/history?{filters}").json()["items"]
        assert len(items) == 1
        assert len(items[0]["runs"]) == 2
    detail = api_context.client.get("/job-search/history/together").json()
    assert len(detail["runs"]) == 2
    assert detail["runs"][0]["report"] is None
    assert (
        api_context.client.get(
            "/job-search/history/run-3", headers={"X-Rufina-Owner-Id": "other-owner"}
        ).status_code
        == 404
    )
    other = api_context.client.get(
        "/job-search/history/together", headers={"X-Rufina-Owner-Id": "other-owner"}
    ).json()
    assert [run["id"] for run in other["runs"]] == ["run-4"]
    with api_context.sessions() as db:
        db.get(JobSearchRunRecord, "run-2").status = "failed"
        db.commit()
    partial = api_context.client.get("/job-search/history?status=partial").json()["items"]
    assert [item["id"] for item in partial] == ["together"]
    assert len(partial[0]["runs"]) == 2
    completed = api_context.client.get("/job-search/history?status=completed").json()["items"]
    assert [item["id"] for item in completed] == ["run-3"]


def test_catalog_disappearance_preserves_cross_source_provenance(api_context, monkeypatch):
    job = vacancy()
    company_job = job.model_copy(update={"source": "sbb"})
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={
                "linkedin": response("linkedin", [job]),
                "sbb": response("sbb", [company_job]),
            },
            source_errors={},
        )
    )
    monkeypatch.setattr(job_search_api, "create_vacancy_search_runner", lambda _: runner)
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _: FakeScreeningFacade({"Backend Engineer": "keep"}),
    )
    run_search(api_context, ["linkedin", "sbb"], session="both-sources")
    runner.result = VacancySearchRunResult(
        jobs=[],
        source_results={"sbb": response("sbb", [])},
        source_errors={},
    )
    run_search(api_context, ["sbb"], session="company-missing")
    report = api_context.client.get("/job-search/history/company-missing").json()["runs"][0][
        "report"
    ]
    assert report["sources"][0]["missing"] == 1
    assert report["vacancies"][0]["source"] == "sbb"


def test_processing_failure_finishes_the_report(api_context, monkeypatch):
    job = vacancy()
    runner = FakeRunner(
        VacancySearchRunResult(
            jobs=[job],
            source_results={"linkedin": response("linkedin", [job])},
            source_errors={},
        )
    )
    monkeypatch.setattr(job_search_api, "create_vacancy_search_runner", lambda _: runner)

    def fail_processing(*args, **kwargs):
        raise RuntimeError("Unexpected worker failure")

    monkeypatch.setattr(job_search_execution, "screen_candidates_by_source", fail_processing)
    result = api_context.client.post(
        "/job-search/run",
        json={
            "sessionId": "failed-processing",
            "config": {"name": "Search", "filters": {}},
            "sources": ["linkedin"],
        },
    )
    assert result.status_code == 502
    run = api_context.client.get("/job-search/history/failed-processing").json()["runs"][0]
    assert run["status"] == "failed"
    assert run["completedAt"]
    assert run["report"]["vacancies"][0]["outcome"] == "error"
    assert run["report"]["sources"][0]["pending"] == 0


def test_ai_data_deletion_removes_copied_screening_decisions(api_context):
    with api_context.sessions() as db:
        for owner in ("local-owner", "other-owner"):
            db.add(
                JobSearchRunRecord(
                    id=owner,
                    owner_id=owner,
                    status="completed",
                    run_type="manual",
                    config_snapshot={},
                    sources=["linkedin"],
                    report_version=1,
                    report={"version": 1, "sources": [], "vacancies": [{"reason": "AI reason"}]},
                )
            )
        db.commit()
    assert api_context.client.delete("/privacy/ai-data").status_code == 204
    report = api_context.client.get("/job-search/history/local-owner").json()["runs"][0]["report"]
    assert report["vacancies"] == []
    assert report["detailsRemoved"] is True
    other = api_context.client.get(
        "/job-search/history/other-owner", headers={"X-Rufina-Owner-Id": "other-owner"}
    ).json()
    assert other["runs"][0]["report"]["vacancies"] == [{"reason": "AI reason"}]


def test_report_includes_records_rejected_by_parser_validation(api_context, monkeypatch):
    valid = vacancy(source="sbb")
    invalid = vacancy(source="sbb", number="invalid").model_copy(update={"title": ""})
    runner = VacancySearchRunner({"sbb": CompletedParser("sbb", [valid, invalid])})
    monkeypatch.setattr(job_search_api, "create_vacancy_search_runner", lambda _: runner)
    monkeypatch.setattr(
        job_search_execution,
        "create_job_screening_ai_facade",
        lambda _: FakeScreeningFacade({"Backend Engineer": "keep"}),
    )
    run_search(api_context, ["sbb"])
    report = api_context.client.get("/job-search/history/test-session").json()["runs"][0]["report"]
    assert report["sources"][0]["received"] == 2
    assert report["sources"][0]["error"] == 1
    assert report["sources"][0]["added"] == 1
    assert report["sources"][0]["missing"] is None
    assert report["sources"][0]["durationSeconds"] >= 0
    assert report["sources"][0]["attempts"] == 1
    assert report["vacancies"][1]["reasonCode"] == "invalid_record"
