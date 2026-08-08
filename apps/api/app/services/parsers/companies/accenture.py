from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from math import ceil
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ACCENTURE_JOBS_BASE_URL = "https://www.accenture.com/ch-en/careers/jobsearch"
ACCENTURE_JOBS_API_URL = "https://www.accenture.com/api/accenture/elastic/findjobs"
ACCENTURE_RESULTS_PER_PAGE = 100
ACCENTURE_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de;q=0.8,fr;q=0.7,it;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class AccentureParseError(DirectCompanyRequestError):
    pass


class AccentureJobsParser:
    """Collect the complete Swiss Accenture catalog from its public search API."""

    parser_id = "accenture"

    def __init__(
        self,
        *,
        base_url: str = ACCENTURE_JOBS_BASE_URL,
        api_url: str = ACCENTURE_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        page_size: int = ACCENTURE_RESULTS_PER_PAGE,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.page_size = max(1, page_size)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ACCENTURE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
        except AccentureParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Accenture vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Accenture vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_accenture_jobs(jobs)
        page_label = "page" if pages_fetched == 1 else "pages"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Accenture vacancies across "
                f"{pages_fetched} API {page_label} ({total} listed)"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records: list[dict[str, Any]] = []
        expected_total: int | None = None
        required_pages = 1

        for page_number in range(1, self.max_pages + 1):
            offset = (page_number - 1) * self.page_size
            response = client.post(
                self.api_url,
                data=listing_form(offset=offset, page_size=self.page_size),
            )
            response.raise_for_status()
            page_total, page_records = parse_listing_payload(response.json())

            if expected_total is None:
                expected_total = page_total
                required_pages = max(1, ceil(expected_total / self.page_size))
                if required_pages > self.max_pages:
                    raise AccentureParseError(
                        f"Accenture exposes {required_pages} pages, above the "
                        f"configured limit of {self.max_pages}"
                    )
            elif page_total != expected_total:
                raise AccentureParseError(
                    "Accenture changed its vacancy total during pagination"
                )

            if page_number <= required_pages and expected_total and not page_records:
                raise AccentureParseError(
                    f"Accenture page {page_number} was unexpectedly empty"
                )

            for record in page_records:
                normalized = dict(record)
                normalized["listing_page"] = page_number
                normalized["total_available"] = expected_total
                records.append(normalized)

            if page_number >= required_pages:
                break

        if expected_total is None:
            raise AccentureParseError("Accenture jobs response was not collected")
        if len(records) != expected_total:
            raise AccentureParseError(
                f"Accenture returned {len(records)} vacancies of {expected_total}"
            )
        return records, required_pages, expected_total

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        job_id = extract_job_id(record)
        public_url = build_public_url(self.base_url, job_id)
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company="Accenture",
            location=extract_location(record),
            url=public_url,
            apply_url=optional_text(record.get("internalReferURL")) or public_url,
            posted_at=(
                optional_text(record.get("updateDate"))
                or optional_text(record.get("postedDateText"))
            ),
            employment_type=(
                optional_text(record.get("employeeType"))
                or optional_text(record.get("jobScheduleDescription"))
            ),
            seniority=(
                optional_text(record.get("careerLevel"))
                or optional_text(record.get("jobTypeDescription"))
            ),
            description=extract_description(record),
            raw=dict(record),
        )


def listing_form(*, offset: int, page_size: int) -> dict[str, str]:
    return {
        "startIndex": str(offset),
        "maxResultSize": str(page_size),
        "jobKeyword": "",
        "jobCountry": "Switzerland",
        "jobLanguage": "en",
        "countrySite": "ch-en",
        "sortBy": "2",
        "searchType": "vectorSearch",
        "enableQueryBoost": "true",
        "minScore": "0.6",
        "getFeedbackJudgmentEnabled": "true",
        "useCleanEmbedding": "true",
        "score": "true",
        "totalHits": "true",
        "debugQuery": "false",
        "jobFilters": "[]",
    }


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise AccentureParseError("Accenture jobs response must be an object")
    total_hits = payload.get("totalHits")
    if not isinstance(total_hits, dict):
        raise AccentureParseError("Accenture jobs response has invalid totalHits")
    total = total_hits.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise AccentureParseError("Accenture jobs response has an invalid total")
    if str(total_hits.get("overMaxHits", "false")).casefold() == "true":
        raise AccentureParseError("Accenture jobs response exceeds its result limit")

    data = payload.get("data")
    if not isinstance(data, list):
        raise AccentureParseError("Accenture jobs response has invalid data")

    records: list[dict[str, Any]] = []
    for item in data:
        if (
            not isinstance(item, dict)
            or not extract_job_id(item)
            or not optional_text(item.get("title"))
        ):
            raise AccentureParseError(
                "Accenture jobs response contains an incomplete vacancy"
            )
        records.append(item)
    return total, records


def extract_job_id(record: dict[str, Any]) -> str | None:
    return (
        optional_text(record.get("guid"))
        or optional_text(record.get("requisitionId"))
    )


def build_public_url(base_url: str, job_id: str | None) -> str:
    if not job_id:
        return base_url
    parts = urlsplit(base_url)
    return f"{parts.scheme}://{parts.netloc}/ch-en/careers/jobdetails?id={job_id}"


def extract_location(record: dict[str, Any]) -> str | None:
    value = record.get("location")
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        locations = list(
            dict.fromkeys(text for item in value if (text := optional_text(item)))
        )
        if locations:
            return ", ".join(locations)
    return optional_text(value) or optional_text(record.get("feedCity"))


def extract_description(record: dict[str, Any]) -> str | None:
    description = optional_multiline_text(record.get("jobDescriptionClean"))
    if not description:
        description = html_to_text(record.get("jobDescription"))
    qualifications = optional_multiline_text(record.get("qualificationClean"))
    if not qualifications:
        qualifications = html_to_text(record.get("qualification"))

    parts: list[str] = []
    if description:
        parts.append(description)
    if qualifications and qualifications not in parts:
        parts.append(f"Qualifications\n{qualifications}")
    if not parts:
        overview = optional_multiline_text(record.get("jobOverview"))
        if overview:
            parts.append(overview)
    return "\n\n".join(parts) or None


def deduplicate_accenture_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
