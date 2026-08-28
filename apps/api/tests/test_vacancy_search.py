import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.linkedin import BrightDataRequestError
from app.services.vacancy_search import VacancySearchRunner


class SnapshotParser:
    parser_id = "linkedin"

    def __init__(self) -> None:
        self.snapshot_calls = 0

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        return ParserSearchResponse(
            parser=self.parser_id,
            status="queued",
            search_url="https://linkedin.example/search",
            snapshot_id="snapshot-1",
        )

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        results_limit: int,
        deduplicate: bool,
    ) -> ParserSearchResponse:
        self.snapshot_calls += 1
        if self.snapshot_calls == 1:
            return ParserSearchResponse(
                parser=self.parser_id,
                status="running",
                search_url="",
                snapshot_id=snapshot_id,
            )
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url="",
            snapshot_id=snapshot_id,
            jobs=[
                ParsedJob(
                    source="linkedin",
                    title="Platform Engineer",
                    company="Acme",
                    location="Zurich",
                    url="https://linkedin.example/jobs/1",
                )
            ],
        )


class CompletedParser:
    def __init__(self, parser_id: str, jobs: list[ParsedJob]) -> None:
        self.parser_id = parser_id
        self.jobs = jobs

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=f"https://{self.parser_id}.example/search",
            jobs=self.jobs,
        )


class RecordingParser(CompletedParser):
    def __init__(self, parser_id: str) -> None:
        super().__init__(parser_id, [])
        self.requests: list[LinkedInSearchRequest] = []

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        self.requests.append(request)
        return super().search(request)


class FailingIndeedParser:
    parser_id = "indeed"

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        raise BrightDataRequestError("Indeed upstream failed")


class RunningSnapshotParser(SnapshotParser):
    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        results_limit: int,
        deduplicate: bool,
    ) -> ParserSearchResponse:
        self.snapshot_calls += 1
        return ParserSearchResponse(
            parser=self.parser_id,
            status="running",
            search_url="",
            snapshot_id=snapshot_id,
        )


def test_runner_polls_bright_data_snapshot_until_completion() -> None:
    parser = SnapshotParser()
    runner = VacancySearchRunner(
        {"linkedin": parser},
        snapshot_poll_interval_seconds=0.01,
        snapshot_poll_timeout_seconds=1,
        sleep=lambda _: None,
    )

    result = runner.search_source(
        "linkedin",
        LinkedInSearchRequest(results_limit=10),
        wait_for_snapshot=True,
    )

    assert result.status == "completed"
    assert result.search_url == "https://linkedin.example/search"
    assert result.jobs[0].title == "Platform Engineer"
    assert parser.snapshot_calls == 2


def test_runner_returns_latest_snapshot_status_after_polling_timeout() -> None:
    parser = RunningSnapshotParser()
    current_time = [0.0]

    def advance(seconds: float) -> None:
        current_time[0] += seconds

    runner = VacancySearchRunner(
        {"linkedin": parser},
        snapshot_poll_interval_seconds=0.5,
        snapshot_poll_timeout_seconds=1,
        clock=lambda: current_time[0],
        sleep=advance,
    )

    result = runner.search_source(
        "linkedin",
        LinkedInSearchRequest(results_limit=10),
        wait_for_snapshot=True,
    )

    assert result.status == "running"
    assert result.snapshot_id == "snapshot-1"
    assert result.search_url == "https://linkedin.example/search"
    assert parser.snapshot_calls == 3


def test_runner_reports_pending_snapshot_without_claiming_zero_results() -> None:
    parser = RunningSnapshotParser()
    current_time = [0.0]

    def advance(seconds: float) -> None:
        current_time[0] += seconds

    runner = VacancySearchRunner(
        {"linkedin": parser},
        snapshot_poll_interval_seconds=0.5,
        snapshot_poll_timeout_seconds=1,
        clock=lambda: current_time[0],
        sleep=advance,
    )

    result = runner.run(
        sources=["linkedin"],
        request=LinkedInSearchRequest(results_limit=10),
    )

    assert result.jobs == []
    assert result.source_errors == {
        "linkedin": (
            "linkedin snapshot snapshot-1 is still running after 1s; "
            "no results were downloaded yet"
        )
    }


def test_runner_merges_deduplicates_and_preserves_partial_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    linkedin_job = ParsedJob(
        source="linkedin",
        title="Platform Engineer",
        company="Acme",
        location="Zurich",
        url="https://linkedin.example/jobs/1?tracking=abc",
    )
    duplicate_from_jobs_ch = ParsedJob(
        source="jobs_ch",
        title=" platform engineer ",
        company="ACME",
        location="Zurich",
        url="https://jobs.example/vacancies/99",
    )
    unique_jobs_ch_job = ParsedJob(
        source="jobs_ch",
        title="Backend Engineer",
        company="Example",
        location="Bern",
        url="https://jobs.example/vacancies/100",
    )
    runner = VacancySearchRunner(
        {
            "linkedin": CompletedParser("linkedin", [linkedin_job]),
            "indeed": FailingIndeedParser(),
            "jobs_ch": CompletedParser(
                "jobs_ch",
                [duplicate_from_jobs_ch, unique_jobs_ch_job],
            ),
        }
    )
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    result = runner.run(
        sources=["linkedin", "indeed", "jobs_ch", "linkedin"],
        request=LinkedInSearchRequest(results_limit=10, deduplicate=True),
    )

    assert [job.title for job in result.jobs] == [
        "Platform Engineer",
        "Backend Engineer",
    ]
    assert set(result.source_results) == {"linkedin", "jobs_ch"}
    assert result.source_errors == {"indeed": "Indeed upstream failed"}
    events = [
        json.loads(record.message)
        for record in caplog.records
        if '"event":"vacancy_parser.' in record.message
    ]
    assert [event["event"] for event in events] == [
        "vacancy_parser.finished",
        "vacancy_parser.failed",
        "vacancy_parser.finished",
    ]
    assert [(event["source"], event["vacanciesParsed"]) for event in events] == [
        ("linkedin", 1),
        ("indeed", 0),
        ("jobs_ch", 2),
    ]


def test_runner_filters_old_jobs_after_parser_results_are_collected() -> None:
    fresh_date = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    old_date = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    fresh_job = ParsedJob(
        source="jobs_ch",
        title="Fresh job",
        company="Acme",
        posted_at=fresh_date,
        url="https://jobs.example/vacancies/fresh",
    )
    old_job = ParsedJob(
        source="jobs_ch",
        title="Old job returned by unstable parser",
        company="Acme",
        posted_at=old_date,
        url="https://jobs.example/vacancies/old",
    )
    relisted_old_job = ParsedJob(
        source="jobs_ch",
        title="Relisted old job",
        company="Acme",
        posted_at=fresh_date,
        url="https://jobs.example/vacancies/relisted",
        raw={"initialPublicationDate": old_date},
    )
    parser = CompletedParser(
        "jobs_ch",
        [fresh_job, old_job, relisted_old_job],
    )
    runner = VacancySearchRunner({"jobs_ch": parser})

    result = runner.run(
        sources=["jobs_ch"],
        request=LinkedInSearchRequest(date_posted="Past 24 hours"),
        wait_for_snapshots=False,
    )

    assert [job.title for job in result.jobs] == ["Fresh job"]
    assert len(result.source_results["jobs_ch"].jobs) == 3


def test_runner_applies_one_common_config_to_every_source() -> None:
    linkedin = RecordingParser("linkedin")
    indeed = RecordingParser("indeed")
    runner = VacancySearchRunner({"linkedin": linkedin, "indeed": indeed})

    runner.run(
        sources=["linkedin", "indeed"],
        request=LinkedInSearchRequest(
            keywords="platform",
            location="Zurich",
            results_limit=25,
        ),
        wait_for_snapshots=False,
    )

    assert linkedin.requests[0].keywords == "platform"
    assert indeed.requests[0].keywords == "platform"
    assert linkedin.requests[0].location == "Zurich"
    assert indeed.requests[0].location == "Zurich"
    assert linkedin.requests[0].results_limit == 25
    assert indeed.requests[0].results_limit == 25


def test_runner_neutralizes_query_filters_for_direct_company_catalogs() -> None:
    sbb = RecordingParser("sbb")
    runner = VacancySearchRunner({"sbb": sbb})

    runner.run(
        sources=["sbb"],
        request=LinkedInSearchRequest(
            keywords="software engineer",
            location="Zurich",
            remote="Remote only",
            experience_level="Entry level",
            job_type="Full-time",
            date_posted="Past 24 hours",
            country="Switzerland",
            results_limit=25,
        ),
        wait_for_snapshots=False,
    )

    assert (
        sbb.requests[0].model_dump()
        == LinkedInSearchRequest(
            results_limit=25,
        ).model_dump()
    )


def test_runner_preserves_full_direct_company_catalog_before_screening() -> None:
    old_date = (datetime.now(UTC) - timedelta(days=90)).isoformat()
    old_job = ParsedJob(
        source="sbb",
        title="Long-running vacancy",
        company="SBB CFF FFS",
        posted_at=old_date,
        url="https://jobs.sbb.ch/vacancies/old",
    )
    runner = VacancySearchRunner({"sbb": CompletedParser("sbb", [old_job])})

    result = runner.run(
        sources=["sbb"],
        request=LinkedInSearchRequest(date_posted="Past 24 hours"),
        wait_for_snapshots=False,
    )

    assert result.jobs == [old_job]
