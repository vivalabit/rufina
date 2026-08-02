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


def test_runner_merges_deduplicates_and_preserves_partial_results() -> None:
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
