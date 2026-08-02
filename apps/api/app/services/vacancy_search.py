import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.core.settings import Settings
from app.core.vacancy_sources import (
    SUPPORTED_VACANCY_SOURCE_IDS,
    is_direct_company_source,
)
from app.models.parsers import (
    IndeedSearchRequest,
    JobsChSearchRequest,
    LinkedInSearchRequest,
    ParsedJob,
    ParserSearchResponse,
)
from app.services.parsers.companies import create_direct_company_parsers
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.indeed import IndeedJobsParser
from app.services.parsers.jobs_ch import JobsChParser, JobsChRequestError
from app.services.parsers.linkedin import (
    BrightDataConfigurationError,
    BrightDataRequestError,
    LinkedInJobsParser,
)

SUPPORTED_VACANCY_SOURCES = SUPPORTED_VACANCY_SOURCE_IDS
BRIGHT_DATA_SOURCES = frozenset({"linkedin", "indeed"})
SOURCE_ERRORS = (
    BrightDataConfigurationError,
    BrightDataRequestError,
    JobsChRequestError,
    DirectCompanyRequestError,
)


@dataclass(frozen=True)
class VacancySearchRunResult:
    jobs: list[ParsedJob]
    source_results: dict[str, ParserSearchResponse]
    source_errors: dict[str, str]


class VacancySearchRunner:
    def __init__(
        self,
        parsers: dict[str, Any],
        *,
        snapshot_poll_interval_seconds: float = 1.0,
        snapshot_poll_timeout_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.parsers = parsers
        self.snapshot_poll_interval_seconds = max(0.01, snapshot_poll_interval_seconds)
        self.snapshot_poll_timeout_seconds = max(0.0, snapshot_poll_timeout_seconds)
        self.clock = clock
        self.sleep = sleep

    def search_source(
        self,
        source: str,
        request: LinkedInSearchRequest,
        *,
        wait_for_snapshot: bool = False,
    ) -> ParserSearchResponse:
        parser = self.require_parser(source)
        source_request = request_for_source(source, request)
        initial = parser.search(source_request)
        if (
            wait_for_snapshot
            and source in BRIGHT_DATA_SOURCES
            and initial.snapshot_id
            and initial.status != "completed"
        ):
            return self.poll_snapshot(
                source,
                initial.snapshot_id,
                results_limit=request.results_limit,
                deduplicate=request.deduplicate,
                search_url=initial.search_url,
            )
        return initial

    def get_snapshot(
        self,
        source: str,
        snapshot_id: str,
        *,
        results_limit: int = 100,
        deduplicate: bool = True,
    ) -> ParserSearchResponse:
        if source not in BRIGHT_DATA_SOURCES:
            raise ValueError(f"{source} does not support snapshots")
        parser = self.require_parser(source)
        return parser.get_snapshot(
            snapshot_id,
            results_limit=results_limit,
            deduplicate=deduplicate,
        )

    def poll_snapshot(
        self,
        source: str,
        snapshot_id: str,
        *,
        results_limit: int,
        deduplicate: bool,
        search_url: str = "",
    ) -> ParserSearchResponse:
        deadline = self.clock() + self.snapshot_poll_timeout_seconds

        while True:
            latest = self.get_snapshot(
                source,
                snapshot_id,
                results_limit=results_limit,
                deduplicate=deduplicate,
            )
            if search_url and not latest.search_url:
                latest = latest.model_copy(update={"search_url": search_url})
            if latest.status == "completed":
                return latest

            remaining = deadline - self.clock()
            if remaining <= 0:
                return latest
            self.sleep(min(self.snapshot_poll_interval_seconds, remaining))

    def run(
        self,
        *,
        sources: Sequence[str],
        request: LinkedInSearchRequest,
        source_requests: Mapping[str, LinkedInSearchRequest] | None = None,
        wait_for_snapshots: bool = True,
    ) -> VacancySearchRunResult:
        source_results: dict[str, ParserSearchResponse] = {}
        source_errors: dict[str, str] = {}
        jobs: list[ParsedJob] = []

        for source in unique_sources(sources):
            try:
                selected_request = (
                    source_requests.get(source, request)
                    if source_requests is not None
                    else request
                )
                result = self.search_source(
                    source,
                    selected_request,
                    wait_for_snapshot=wait_for_snapshots,
                )
                source_results[source] = result
                jobs.extend(result.jobs)
                if wait_for_snapshots and result.status != "completed":
                    source_errors[source] = (
                        f"{source} snapshot polling timed out with status {result.status}"
                    )
            except SOURCE_ERRORS as exc:
                source_errors[source] = str(exc)

        return VacancySearchRunResult(
            jobs=deduplicate_jobs(jobs) if request.deduplicate else jobs,
            source_results=source_results,
            source_errors=source_errors,
        )

    def require_parser(self, source: str) -> Any:
        parser = self.parsers.get(source)
        if parser is None:
            raise ValueError(f"Unsupported vacancy source: {source}")
        return parser


def create_vacancy_search_runner(settings: Settings) -> VacancySearchRunner:
    parsers = {
        "linkedin": LinkedInJobsParser(
            api_key=settings.brightdata_api_key,
            api_url=settings.brightdata_api_url,
            dataset_id=settings.brightdata_linkedin_jobs_dataset_id,
        ),
        "indeed": IndeedJobsParser(
            api_key=settings.brightdata_api_key,
            api_url=settings.brightdata_api_url,
            dataset_id=settings.brightdata_indeed_jobs_dataset_id,
        ),
        "jobs_ch": JobsChParser(
            base_url=settings.jobs_ch_base_url,
            timeout_seconds=settings.jobs_ch_timeout_seconds,
            max_pages=settings.jobs_ch_max_pages,
            detail_workers=settings.jobs_ch_detail_workers,
        ),
    }
    parsers.update(create_direct_company_parsers(settings))
    return VacancySearchRunner(
        parsers,
        snapshot_poll_interval_seconds=settings.brightdata_snapshot_poll_interval_seconds,
        snapshot_poll_timeout_seconds=settings.brightdata_snapshot_poll_timeout_seconds,
    )


def request_for_source(
    source: str,
    request: LinkedInSearchRequest,
) -> LinkedInSearchRequest:
    request_type = {
        "linkedin": LinkedInSearchRequest,
        "indeed": IndeedSearchRequest,
        "jobs_ch": JobsChSearchRequest,
    }.get(source)
    if request_type is None and is_direct_company_source(source):
        return request
    if request_type is None:
        raise ValueError(f"Unsupported vacancy source: {source}")
    return request_type.model_validate(request.model_dump())


def unique_sources(sources: Sequence[str]) -> list[str]:
    unique = list(dict.fromkeys(sources))
    unsupported = [source for source in unique if source not in SUPPORTED_VACANCY_SOURCES]
    if unsupported:
        raise ValueError(f"Unsupported vacancy source: {unsupported[0]}")
    return unique


def deduplicate_jobs(jobs: Sequence[ParsedJob]) -> list[ParsedJob]:
    seen_urls: set[str] = set()
    seen_identities: set[str] = set()
    unique: list[ParsedJob] = []

    for job in jobs:
        url_key = canonical_job_url(job.url)
        identity_key = job_identity(job)
        if (url_key and url_key in seen_urls) or (identity_key and identity_key in seen_identities):
            continue
        if url_key:
            seen_urls.add(url_key)
        if identity_key:
            seen_identities.add(identity_key)
        unique.append(job)
    return unique


def canonical_job_url(value: str | None) -> str:
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip().casefold()
    if not parts.netloc:
        return value.strip().casefold()
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path.rstrip("/"),
            "",
            "",
        )
    )


def job_identity(job: ParsedJob) -> str:
    title = normalize_identity_part(job.title)
    company = normalize_identity_part(job.company)
    location = normalize_identity_part(job.location)
    if not title or not company:
        return ""
    return "|".join((title, company, location))


def normalize_identity_part(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()
