import re
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse

LINKEDIN_JOBS_DATASET_ID = "gd_lpfll7v5hcqtkxl6l"

REMOTE_FILTERS = {
    "Remote only": "2",
    "Hybrid": "3",
    "On-site": "1",
}

EXPERIENCE_LEVELS = {
    "Entry level": "2",
    "Associate": "3",
    "Mid-Senior level": "4",
    "Director": "5",
}

JOB_TYPES = {
    "Full-time": "F",
    "Part-time": "P",
    "Contract": "C",
    "Internship": "I",
}

DATE_POSTED = {
    "Past 24 hours": "r86400",
    "Past week": "r604800",
    "Past month": "r2592000",
}

REMOTE_DISCOVERY_FILTERS = {
    "Remote only": "Remote",
    "Hybrid": "Hybrid",
    "On-site": "On-site",
}

COUNTRY_CODES = {
    "switzerland": "CH",
    "schweiz": "CH",
    "suisse": "CH",
    "svizzera": "CH",
}

LINKEDIN_JOB_ID_PATTERN = re.compile(r"/jobs/view/(?:[^/?#]*-)?(?P<id>\d+)(?:[/?#]|$)")


class BrightDataConfigurationError(RuntimeError):
    pass


class BrightDataRequestError(RuntimeError):
    pass


class LinkedInJobsParser:
    parser_id = "linkedin"

    def __init__(
        self,
        *,
        api_key: str | None,
        api_url: str,
        dataset_id: str = LINKEDIN_JOBS_DATASET_ID,
        timeout_seconds: float = 65.0,
    ) -> None:
        self.api_key = api_key
        self.api_url = api_url.rstrip("/")
        self.dataset_id = dataset_id
        self.timeout_seconds = timeout_seconds

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        if not self.api_key:
            raise BrightDataConfigurationError("BRIGHTDATA_API_KEY is not configured")

        search_url = self.build_search_url(request)
        payload = self.build_discovery_inputs(request)
        params = {
            "dataset_id": self.dataset_id,
            "type": "discover_new",
            "discover_by": "keyword",
            "format": "json",
            "include_errors": "true",
            "limit_per_input": min(request.limit_per_input, request.results_limit),
            "limit_multiple_results": request.results_limit,
        }

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(
                    f"{self.api_url}/trigger",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    params=params,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise BrightDataRequestError("Bright Data request failed") from exc

        if response.status_code == 401:
            raise BrightDataRequestError(
                "Bright Data API key was rejected. Replace it in Settings."
            )
        if response.status_code >= 400:
            raise BrightDataRequestError(
                f"Bright Data returned HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        if isinstance(data, dict) and data.get("snapshot_id"):
            return ParserSearchResponse(
                parser=self.parser_id,
                status="queued",
                search_url=search_url,
                snapshot_id=data["snapshot_id"],
                message=data.get("message"),
            )

        records = data if isinstance(data, list) else data.get("data", []) if isinstance(data, dict) else []
        jobs = [
            self.normalize_job(record)
            for record in records
            if isinstance(record, dict) and self.is_job_record(record)
        ]
        if request.deduplicate:
            jobs = self.deduplicate(jobs)

        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=search_url,
            jobs=jobs[: request.results_limit],
        )

    @classmethod
    def build_discovery_inputs(
        cls,
        request: LinkedInSearchRequest,
    ) -> list[dict[str, Any]]:
        query_specs: list[tuple[str, list[str], str | None, bool]] = []
        if request.linkedin_queries:
            query_specs.extend(
                (
                    query.keyword.strip(),
                    list(query.experience_levels),
                    query.job_type,
                    query.selective_search,
                )
                for query in request.linkedin_queries
            )
        else:
            query_specs.append(
                (
                    request.keywords.strip(),
                    [] if request.experience_level == "Any" else [request.experience_level],
                    request.job_type,
                    bool(request.keywords.strip()),
                )
            )

        location = request.location.strip()
        if not location and request.country != "Any":
            location = request.country.strip()
        if not location:
            location = "Worldwide"

        country_code = cls.country_code(request.country)
        inputs: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str, bool]] = set()
        for keyword, experience_levels, query_job_type, selective_search in query_specs:
            levels: list[str | None] = experience_levels or [None]
            for experience_level in levels:
                job_type = query_job_type or request.job_type
                discovery_experience_level = experience_level
                discovery_job_type = job_type
                if job_type == "Internship":
                    # Bright Data models internships as an experience level for
                    # LinkedIn discovery, not as a job type. Sending
                    # job_type="Internship" rejects the entire batch with 400.
                    discovery_experience_level = "Internship"
                    discovery_job_type = None
                identity = (
                    keyword.casefold(),
                    discovery_experience_level or "",
                    ""
                    if not discovery_job_type or discovery_job_type == "Any"
                    else discovery_job_type,
                    selective_search,
                )
                if identity in seen:
                    continue
                seen.add(identity)

                item: dict[str, Any] = {
                    "location": location,
                    "keyword": keyword,
                    "selective_search": selective_search,
                }
                if country_code:
                    item["country"] = country_code
                if request.date_posted != "Any time":
                    item["time_range"] = request.date_posted
                if discovery_job_type and discovery_job_type != "Any":
                    item["job_type"] = discovery_job_type
                if discovery_experience_level:
                    item["experience_level"] = discovery_experience_level
                if request.remote in REMOTE_DISCOVERY_FILTERS:
                    item["remote"] = REMOTE_DISCOVERY_FILTERS[request.remote]
                inputs.append(item)
        return inputs

    @staticmethod
    def country_code(country: str) -> str | None:
        normalized = country.strip()
        if not normalized or normalized == "Any":
            return None
        if len(normalized) == 2 and normalized.isalpha():
            return normalized.upper()
        return COUNTRY_CODES.get(normalized.casefold())

    def get_snapshot(
        self,
        snapshot_id: str,
        *,
        results_limit: int = 100,
        deduplicate: bool = True,
    ) -> ParserSearchResponse:
        if not self.api_key:
            raise BrightDataConfigurationError("BRIGHTDATA_API_KEY is not configured")

        progress = self.get_snapshot_progress(snapshot_id)
        status_value = str(progress.get("status", "")).lower() if isinstance(progress, dict) else ""
        if status_value in {"failed", "error"}:
            raise BrightDataRequestError(f"Bright Data snapshot {snapshot_id} failed: {status_value}")
        if status_value and status_value not in {"ready", "completed", "done", "success"}:
            return ParserSearchResponse(
                parser=self.parser_id,
                status="running" if status_value in {"running", "processing", "building"} else "queued",
                search_url="",
                snapshot_id=snapshot_id,
                message=status_value,
            )

        records = self.download_snapshot(snapshot_id)
        if records is None:
            return ParserSearchResponse(
                parser=self.parser_id,
                status="queued",
                search_url="",
                snapshot_id=snapshot_id,
                message="snapshot_not_ready",
            )

        jobs = [
            self.normalize_job(record)
            for record in records
            if isinstance(record, dict) and self.is_job_record(record)
        ]
        if deduplicate:
            jobs = self.deduplicate(jobs)

        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url="",
            jobs=jobs[:results_limit],
            snapshot_id=snapshot_id,
        )

    def get_snapshot_progress(self, snapshot_id: str) -> dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    f"{self.api_url}/progress/{snapshot_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
        except httpx.HTTPError as exc:
            raise BrightDataRequestError("Bright Data snapshot progress request failed") from exc

        if response.status_code == 404:
            return {}
        if response.status_code >= 400:
            raise BrightDataRequestError(
                f"Bright Data snapshot progress returned HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        return data if isinstance(data, dict) else {}

    def download_snapshot(self, snapshot_id: str) -> list[dict[str, Any]] | None:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.get(
                    f"{self.api_url}/snapshot/{snapshot_id}",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    params={"format": "json"},
                )
        except httpx.HTTPError as exc:
            raise BrightDataRequestError("Bright Data snapshot download request failed") from exc

        if response.status_code in {202, 204}:
            return None
        if response.status_code >= 400:
            raise BrightDataRequestError(
                f"Bright Data snapshot download returned HTTP {response.status_code}: {response.text[:500]}"
            )

        data = response.json()
        if isinstance(data, list):
            return [record for record in data if isinstance(record, dict)]
        if isinstance(data, dict):
            records = data.get("data") or data.get("results") or []
            return [record for record in records if isinstance(record, dict)] if isinstance(records, list) else []
        return []

    @staticmethod
    def build_search_url(request: LinkedInSearchRequest) -> str:
        params: dict[str, str] = {}
        if request.keywords.strip():
            params["keywords"] = request.keywords.strip()
        if request.location.strip():
            params["location"] = request.location.strip()
        elif request.country != "Any":
            params["location"] = request.country
        if request.remote in REMOTE_FILTERS:
            params["f_WT"] = REMOTE_FILTERS[request.remote]
        if request.experience_level in EXPERIENCE_LEVELS:
            params["f_E"] = EXPERIENCE_LEVELS[request.experience_level]
        if request.job_type in JOB_TYPES:
            params["f_JT"] = JOB_TYPES[request.job_type]
        if request.date_posted in DATE_POSTED:
            params["f_TPR"] = DATE_POSTED[request.date_posted]

        query = urlencode(params)
        return f"https://www.linkedin.com/jobs/search/?{query}" if query else "https://www.linkedin.com/jobs/search/"

    @staticmethod
    def normalize_job(record: dict[str, Any]) -> ParsedJob:
        url = first_present(record, "url", "job_url", "job_posting_url", "linkedin_job_url", "input_url")
        return ParsedJob(
            title=first_present(record, "job_title", "title", "name"),
            company=first_present(record, "company_name", "company", "company_title"),
            location=first_present(record, "job_location", "location", "formatted_location"),
            url=url,
            apply_url=first_present(record, "apply_link", "apply_url", "job_apply_url") or url,
            posted_at=first_present(record, "date_posted", "posted_at", "job_posted_date"),
            employment_type=first_present(record, "job_employment_type", "employment_type", "job_type"),
            seniority=first_present(record, "job_seniority_level", "seniority", "experience_level"),
            description=first_present(record, "job_summary", "description", "job_description"),
            raw=record,
        )

    @staticmethod
    def deduplicate(jobs: list[ParsedJob]) -> list[ParsedJob]:
        seen: set[str] = set()
        unique_jobs: list[ParsedJob] = []
        for job in jobs:
            posting_id = first_present(job.raw, "job_posting_id", "job_id")
            if not posting_id:
                posting_id = linkedin_job_id(job.url)
            key = (
                f"linkedin:{posting_id}"
                if posting_id
                else canonical_url(job.url)
                or f"{job.title}|{job.company}|{job.location}"
            )
            if key in seen:
                continue
            seen.add(key)
            unique_jobs.append(job)
        return unique_jobs

    @staticmethod
    def is_job_record(record: dict[str, Any]) -> bool:
        return bool(
            first_present(record, "job_posting_id", "job_id", "job_title", "title")
            or linkedin_job_id(
                first_present(
                    record,
                    "url",
                    "job_url",
                    "job_posting_url",
                    "linkedin_job_url",
                )
            )
        )


def first_present(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return str(value)
    return None


def linkedin_job_id(value: str | None) -> str | None:
    if not value:
        return None
    match = LINKEDIN_JOB_ID_PATTERN.search(value)
    return match.group("id") if match else None


def canonical_url(value: str | None) -> str:
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
