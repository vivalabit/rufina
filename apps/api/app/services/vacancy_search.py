import json
import logging
import re
import time
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
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
from app.services.parser_validation import validate_parser_result
from app.services.parsers.companies import create_direct_company_parsers
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.indeed import IndeedJobsParser
from app.services.parsers.jobs_ch import (
    JobsChParser,
    JobsChRequestError,
    is_within_date_posted_window,
)
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

logger = logging.getLogger("uvicorn.error")


@dataclass(frozen=True)
class VacancySearchRunResult:
    jobs: list[ParsedJob]
    source_results: dict[str, ParserSearchResponse]
    source_errors: dict[str, str]
    source_attempts: dict[str, int] = field(default_factory=dict)


class VacancySearchRunner:
    def __init__(
        self,
        parsers: dict[str, Any],
        *,
        snapshot_poll_interval_seconds: float = 1.0,
        snapshot_poll_timeout_seconds: float = 30.0,
        max_source_workers: int = 6,
        max_source_attempts: int = 3,
        source_retry_backoff_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.parsers = parsers
        self.snapshot_poll_interval_seconds = max(0.01, snapshot_poll_interval_seconds)
        self.snapshot_poll_timeout_seconds = max(0.0, snapshot_poll_timeout_seconds)
        self.max_source_workers = max(1, max_source_workers)
        self.max_source_attempts = max(1, max_source_attempts)
        self.source_retry_backoff_seconds = max(0.0, source_retry_backoff_seconds)
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

    def search_source_attempt(
        self, source: str, request: LinkedInSearchRequest, *,
        attempt: int, wait_for_snapshot: bool,
    ) -> ParserSearchResponse:
        if attempt > 1 and self.source_retry_backoff_seconds:
            self.sleep(min(30.0, self.source_retry_backoff_seconds * 2 ** (attempt - 2)))
        return self.search_source(source, request, wait_for_snapshot=wait_for_snapshot)

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
        ordered_sources = unique_sources(sources)
        if not ordered_sources:
            return VacancySearchRunResult(
                jobs=[],
                source_results={},
                source_errors={},
                source_attempts={},
            )
        completed_results: dict[str, ParserSearchResponse] = {}
        source_errors: dict[str, str] = {}
        source_attempts: dict[str, int] = {}
        source_durations = {source: 0.0 for source in ordered_sources}
        pending = deque((source, 1) for source in ordered_sources)
        in_flight: dict[
            Future[ParserSearchResponse],
            tuple[int, str, int, float],
        ] = {}
        submission_sequence = 0

        with ThreadPoolExecutor(
            max_workers=min(self.max_source_workers, len(ordered_sources)),
            thread_name_prefix="vacancy-source",
        ) as executor:
            while pending or in_flight:
                while pending and len(in_flight) < self.max_source_workers:
                    source, attempt = pending.popleft()
                    source_started_at = time.monotonic()
                    submission_sequence += 1
                    selected_request = (
                        source_requests.get(source, request)
                        if source_requests is not None
                        else request
                    )
                    future = executor.submit(
                        self.search_source_attempt,
                        source,
                        selected_request,
                        attempt=attempt,
                        wait_for_snapshot=wait_for_snapshots,
                    )
                    in_flight[future] = (
                        submission_sequence,
                        source,
                        attempt,
                        source_started_at,
                    )

                completed, _ = wait(
                    tuple(in_flight),
                    return_when=FIRST_COMPLETED,
                )
                for future in sorted(
                    completed,
                    key=lambda item: in_flight[item][0],
                ):
                    _, source, attempt, source_started_at = in_flight.pop(future)
                    duration_seconds = time.monotonic() - source_started_at
                    source_durations[source] += duration_seconds
                    source_attempts[source] = attempt
                    result: ParserSearchResponse | None = None
                    error = ""
                    try:
                        result = future.result()
                    except SOURCE_ERRORS as exc:
                        error = str(exc)
                    except Exception as exc:  # noqa: BLE001 - isolate one parser boundary
                        error = f"{type(exc).__name__}: {exc}".rstrip()

                    if (
                        not error
                        and result is not None
                        and wait_for_snapshots
                        and result.status != "completed"
                    ):
                        error = incomplete_source_error(
                            source,
                            result,
                            timeout_seconds=self.snapshot_poll_timeout_seconds,
                        )

                    if not error and result is not None:
                        if result.status == "completed" and is_direct_company_source(source):
                            result, validation_error = validate_parser_result(result)
                            if validation_error:
                                source_errors[source] = validation_error
                        completed_results[source] = result
                        continue

                    if attempt < self.max_source_attempts:
                        log_source_retry_scheduled(
                            source=source,
                            error=error,
                            attempt=attempt,
                            max_attempts=self.max_source_attempts,
                            duration_seconds=duration_seconds,
                        )
                        pending.append((source, attempt + 1))
                        continue

                    if result is not None:
                        completed_results[source] = result
                    source_errors[source] = error

        source_results: dict[str, ParserSearchResponse] = {}
        jobs: list[ParsedJob] = []
        for source in ordered_sources:
            result = completed_results.get(source)
            if result is not None:
                source_results[source] = result
                jobs.extend(result.jobs)
            if source in source_errors:
                log_source_failed(
                    source=source,
                    error=source_errors[source],
                    attempts=source_attempts[source],
                    duration_seconds=source_durations[source],
                    vacancies_parsed=len(result.jobs) if result is not None else 0,
                )
            elif result is not None:
                log_source_finished(
                    source=source,
                    result=result,
                    attempts=source_attempts[source],
                    duration_seconds=source_durations[source],
                )

        filtered_jobs = filter_jobs_by_date_posted(
            jobs,
            request=request,
            source_requests=source_requests,
        )
        return VacancySearchRunResult(
            jobs=(deduplicate_jobs(filtered_jobs) if request.deduplicate else filtered_jobs),
            source_results=source_results,
            source_errors=source_errors,
            source_attempts=source_attempts,
        )

    def require_parser(self, source: str) -> Any:
        parser = self.parsers.get(source)
        if parser is None:
            raise ValueError(f"Unsupported vacancy source: {source}")
        return parser


def log_source_finished(
    *,
    source: str,
    result: ParserSearchResponse,
    attempts: int,
    duration_seconds: float,
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "vacancy_parser.finished",
                "message": "Vacancy parsing finished",
                "source": source,
                "vacanciesParsed": len(result.jobs),
                "status": result.status,
                "snapshotId": result.snapshot_id,
                "attempts": attempts,
                "durationSeconds": round(duration_seconds, 3),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def log_source_failed(
    *,
    source: str,
    error: str,
    attempts: int,
    duration_seconds: float,
    vacancies_parsed: int = 0,
) -> None:
    logger.error(
        json.dumps(
            {
                "event": "vacancy_parser.failed",
                "message": "Vacancy parsing failed",
                "source": source,
                "vacanciesParsed": vacancies_parsed,
                "status": "partial" if vacancies_parsed else "failed",
                "attempts": attempts,
                "durationSeconds": round(duration_seconds, 3),
                "error": error[:500],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def log_source_retry_scheduled(
    *,
    source: str,
    error: str,
    attempt: int,
    max_attempts: int,
    duration_seconds: float,
) -> None:
    logger.warning(
        json.dumps(
            {
                "event": "vacancy_parser.retry_scheduled",
                "message": "Vacancy parser failed; retry moved to queue tail",
                "source": source,
                "attempt": attempt,
                "maxAttempts": max_attempts,
                "durationSeconds": round(duration_seconds, 3),
                "error": error[:500],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def incomplete_source_error(
    source: str,
    result: ParserSearchResponse,
    *,
    timeout_seconds: float,
) -> str:
    return (
        f"{source} snapshot {result.snapshot_id or 'unknown'} is still "
        f"{result.status} after {timeout_seconds:g}s; no results were downloaded yet"
    )


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
        max_source_workers=settings.vacancy_parser_workers,
        max_source_attempts=settings.vacancy_parser_max_attempts,
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
        # Direct-company parsers scan their complete catalog. Keep parser-level
        # query fields neutral so a shared aggregator request can never narrow
        # the company inventory before global vacancy screening runs.
        return request.model_copy(
            update={
                "keywords": "",
                "location": "",
                "remote": "Any",
                "experience_level": "Any",
                "job_type": "Any",
                "date_posted": "Any time",
                "country": "Any",
                "linkedin_queries": [],
            }
        )
    if request_type is None:
        raise ValueError(f"Unsupported vacancy source: {source}")
    return request_type.model_validate(request.model_dump())


def unique_sources(sources: Sequence[str]) -> list[str]:
    unique = list(dict.fromkeys(sources))
    unsupported = [source for source in unique if source not in SUPPORTED_VACANCY_SOURCES]
    if unsupported:
        raise ValueError(f"Unsupported vacancy source: {unsupported[0]}")
    return unique


def filter_jobs_by_date_posted(
    jobs: Sequence[ParsedJob],
    *,
    request: LinkedInSearchRequest,
    source_requests: Mapping[str, LinkedInSearchRequest] | None = None,
) -> list[ParsedJob]:
    """Enforce date windows after every parser has returned normalized jobs."""
    filtered: list[ParsedJob] = []
    for job in jobs:
        if is_direct_company_source(job.source):
            filtered.append(job)
            continue
        selected_request = (
            source_requests.get(job.source, request) if source_requests is not None else request
        )
        if selected_request.date_posted == "Any time":
            filtered.append(job)
            continue

        filter_date = job.posted_at
        if job.source == "jobs_ch":
            initial_publication_date = job.raw.get("initialPublicationDate")
            if isinstance(initial_publication_date, str) and initial_publication_date.strip():
                filter_date = initial_publication_date

        if is_within_date_posted_window(
            filter_date,
            selected_request.date_posted,
        ):
            filtered.append(job)
    return filtered


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
    return f"{title}|{company}|{location}"


def normalize_identity_part(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip().casefold()
