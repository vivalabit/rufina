from fastapi import APIRouter, HTTPException, Query, status

from app.core.settings import get_settings
from app.models.parsers import (
    IndeedSearchRequest,
    JobsChSearchRequest,
    LinkedInSearchRequest,
    ParserSearchResponse,
)
from app.services.parsers.indeed import IndeedJobsParser
from app.services.parsers.jobs_ch import JobsChParser, JobsChRequestError
from app.services.parsers.linkedin import (
    BrightDataConfigurationError,
    BrightDataRequestError,
    LinkedInJobsParser,
)
from app.services.vacancy_search import VacancySearchRunner

router = APIRouter()


def _linkedin_parser() -> LinkedInJobsParser:
    settings = get_settings()
    return LinkedInJobsParser(
        api_key=settings.brightdata_api_key,
        api_url=settings.brightdata_api_url,
        dataset_id=settings.brightdata_linkedin_jobs_dataset_id,
    )


def _indeed_parser() -> IndeedJobsParser:
    settings = get_settings()
    return IndeedJobsParser(
        api_key=settings.brightdata_api_key,
        api_url=settings.brightdata_api_url,
        dataset_id=settings.brightdata_indeed_jobs_dataset_id,
    )


def _jobs_ch_parser() -> JobsChParser:
    settings = get_settings()
    return JobsChParser(
        base_url=settings.jobs_ch_base_url,
        timeout_seconds=settings.jobs_ch_timeout_seconds,
        max_pages=settings.jobs_ch_max_pages,
        detail_workers=settings.jobs_ch_detail_workers,
        deadline_seconds=settings.jobs_ch_deadline_seconds,
        max_retries=settings.jobs_ch_max_retries,
    )


def _vacancy_search_runner() -> VacancySearchRunner:
    settings = get_settings()
    return VacancySearchRunner(
        {
            "linkedin": _linkedin_parser(),
            "indeed": _indeed_parser(),
            "jobs_ch": _jobs_ch_parser(),
        },
        snapshot_poll_interval_seconds=settings.brightdata_snapshot_poll_interval_seconds,
        snapshot_poll_timeout_seconds=settings.brightdata_snapshot_poll_timeout_seconds,
    )


@router.post("/linkedin/search", response_model=ParserSearchResponse)
def search_linkedin_jobs(request: LinkedInSearchRequest) -> ParserSearchResponse:
    try:
        return _vacancy_search_runner().search_source(
            "linkedin",
            request,
            wait_for_snapshot=True,
        )
    except BrightDataConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BrightDataRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/linkedin/snapshots/{snapshot_id}", response_model=ParserSearchResponse)
def get_linkedin_snapshot(
    snapshot_id: str,
    results_limit: int = Query(default=100, ge=1, le=1000),
    deduplicate: bool = True,
) -> ParserSearchResponse:
    try:
        return _vacancy_search_runner().get_snapshot(
            "linkedin",
            snapshot_id,
            results_limit=results_limit,
            deduplicate=deduplicate,
        )
    except BrightDataConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BrightDataRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/indeed/search", response_model=ParserSearchResponse)
def search_indeed_jobs(request: IndeedSearchRequest) -> ParserSearchResponse:
    try:
        return _vacancy_search_runner().search_source(
            "indeed",
            request,
            wait_for_snapshot=True,
        )
    except BrightDataConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BrightDataRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.get("/indeed/snapshots/{snapshot_id}", response_model=ParserSearchResponse)
def get_indeed_snapshot(
    snapshot_id: str,
    results_limit: int = Query(default=100, ge=1, le=1000),
    deduplicate: bool = True,
) -> ParserSearchResponse:
    try:
        return _vacancy_search_runner().get_snapshot(
            "indeed",
            snapshot_id,
            results_limit=results_limit,
            deduplicate=deduplicate,
        )
    except BrightDataConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except BrightDataRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post("/jobs_ch/search", response_model=ParserSearchResponse)
def search_jobs_ch_jobs(request: JobsChSearchRequest) -> ParserSearchResponse:
    try:
        return _vacancy_search_runner().search_source("jobs_ch", request)
    except JobsChRequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
