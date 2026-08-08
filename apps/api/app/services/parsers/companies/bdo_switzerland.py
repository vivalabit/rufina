from __future__ import annotations

import html
import re
from collections.abc import Iterable
from typing import Any

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BDO_SWITZERLAND_JOBS_BASE_URL = "https://www.bdo.ch/en-gb/careers/open-jobs"
BDO_SWITZERLAND_JOBS_API_URL = (
    "https://api.jobportal.abaservices.ch/api/extern/v1/job-portal/"
    "3505fa5b-0c08-49ef-852b-1a20eab2630e/publications"
)
BDO_SWITZERLAND_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,en;q=0.7,it;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DESCRIPTION_FIELDS = (
    "Organization",
    "Introduction",
    "Tasks",
    "Requirements",
    "Benefits",
    "Closure",
)
EMPLOYMENT_RANGE_PATTERN = re.compile(
    r"\b(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%",
    re.IGNORECASE,
)
EMPLOYMENT_PERCENT_PATTERN = re.compile(r"\b(\d{1,3})\s*%", re.IGNORECASE)


class BdoSwitzerlandParseError(DirectCompanyRequestError):
    pass


class BdoSwitzerlandJobsParser:
    """Collect the complete BDO Switzerland catalog from its public Abacus API."""

    parser_id = "bdo_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BDO_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = BDO_SWITZERLAND_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**BDO_SWITZERLAND_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records = parse_catalog_payload(response.json())
        except BdoSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "BDO Switzerland vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "BDO Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bdo_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} BDO Switzerland vacancies from the "
                "full catalog endpoint"
            ),
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        public_url = optional_text(record.get("PublicationUrlAbacusJobPortal"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("JobTitle")),
            company=optional_text(record.get("CompanyName")) or "BDO AG",
            location=extract_location(record),
            url=public_url,
            apply_url=optional_text(record.get("ApplicationUrl")) or public_url,
            posted_at=(
                optional_text(record.get("PublicationStartDate"))
                or optional_text(record.get("PositionValidFrom"))
                or optional_text(record.get("JobStart"))
            ),
            employment_type=extract_employment_type(record),
            description=extract_description(record),
            raw=dict(record),
        )


def parse_catalog_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise BdoSwitzerlandParseError(
            "BDO Switzerland jobs response must be an array"
        )

    records: list[dict[str, Any]] = []
    for item in payload:
        if (
            not isinstance(item, dict)
            or not extract_publication_id(item)
            or not optional_text(item.get("JobTitle"))
            or not optional_text(item.get("PublicationUrlAbacusJobPortal"))
        ):
            raise BdoSwitzerlandParseError(
                "BDO Switzerland jobs response contains an incomplete vacancy"
            )
        records.append(dict(item))
    return records


def extract_publication_id(record: dict[str, Any]) -> str | None:
    return optional_text(record.get("PublicationId"))


def extract_location(record: dict[str, Any]) -> str | None:
    return (
        optional_text(record.get("u_b_jobs_freiefelder_xxx__userfield1"))
        or optional_text(record.get("PositionAdditionalFieldLocation"))
        or optional_text(record.get("PlaceOfWorkCity"))
    )


def extract_employment_type(record: dict[str, Any]) -> str | None:
    title = optional_text(record.get("JobTitle")) or ""
    range_match = EMPLOYMENT_RANGE_PATTERN.search(title)
    if range_match:
        return f"{range_match.group(1)}-{range_match.group(2)}%"

    percentages = list(dict.fromkeys(EMPLOYMENT_PERCENT_PATTERN.findall(title)))
    if len(percentages) > 1:
        return f"{percentages[0]}-{percentages[-1]}%"
    if percentages:
        return f"{percentages[0]}%"

    level = optional_text(record.get("PositionLevelOfEmployment"))
    return f"{level}%" if level else None


def extract_description(record: dict[str, Any]) -> str | None:
    sections = [
        text
        for field in DESCRIPTION_FIELDS
        if (text := html_to_text(optional_text(record.get(field))))
    ]
    unique = list(dict.fromkeys(sections))
    return "\n\n".join(unique) if unique else None


def deduplicate_bdo_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("PublicationId")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
