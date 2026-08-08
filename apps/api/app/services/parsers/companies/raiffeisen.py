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

RAIFFEISEN_JOBS_BASE_URL = "https://jobs.raiffeisen.ch/"
RAIFFEISEN_JOBS_API_URL = "https://ohws.prospective.ch/public/v1/medium/1950/jobs"
RAIFFEISEN_RESULTS_PER_PAGE = 96
RAIFFEISEN_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,fr;q=0.8,it;q=0.7,en;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class RaiffeisenParseError(DirectCompanyRequestError):
    pass


class RaiffeisenJobsParser:
    """Collect Raiffeisen's complete catalog from its public Prospective API."""

    parser_id = "raiffeisen"

    def __init__(
        self,
        *,
        base_url: str = RAIFFEISEN_JOBS_BASE_URL,
        api_url: str = RAIFFEISEN_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **RAIFFEISEN_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, _total = self.collect_listing_records(client)
        except RaiffeisenParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Raiffeisen vacancy request failed") from exc
        except Exception as exc:
            raise DirectCompanyRequestError("Raiffeisen vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_raiffeisen_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Raiffeisen vacancies across {pages_fetched} API pages"),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # New vacancies can shift an offset-based result set during a scan. Repeat
        # the page walk and union stable IDs before declaring the catalog complete.
        for catalog_pass in range(self.max_catalog_passes):
            offsets = (
                list(range(0, expected_total, RAIFFEISEN_RESULTS_PER_PAGE))
                if expected_total
                else [0]
            )
            pass_records = 0

            for offset in offsets:
                response = client.get(
                    self.api_url,
                    params={
                        "lang": "de",
                        "offset": offset,
                        "limit": RAIFFEISEN_RESULTS_PER_PAGE,
                    },
                )
                pages_fetched += 1
                response.raise_for_status()
                page_total, records = parse_listing_payload(response.json())

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / RAIFFEISEN_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise RaiffeisenParseError(
                            f"Raiffeisen exposes {required_pages} pages, above the "
                            f"configured limit of {self.max_pages}"
                        )
                    offsets.extend(
                        range(
                            RAIFFEISEN_RESULTS_PER_PAGE,
                            expected_total,
                            RAIFFEISEN_RESULTS_PER_PAGE,
                        )
                    )
                elif page_total != expected_total:
                    raise RaiffeisenParseError(
                        "Raiffeisen changed its vacancy total during pagination"
                    )

                if offset < (expected_total or 0) and not records:
                    raise RaiffeisenParseError(
                        f"Raiffeisen page at offset {offset} was unexpectedly empty"
                    )

                pass_records += len(records)
                for record in records:
                    job_id = optional_text(record.get("id"))
                    if not job_id:
                        continue
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id, normalized)

            if pass_records > (expected_total or 0):
                raise RaiffeisenParseError(
                    "Raiffeisen returned more vacancies than its declared total"
                )
            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), pages_fetched, expected_total or 0
            if len(records_by_id) > (expected_total or 0):
                raise RaiffeisenParseError(
                    "Raiffeisen returned more unique vacancies than its declared total"
                )

        raise RaiffeisenParseError(
            f"Raiffeisen yielded only {len(records_by_id)} unique vacancies of "
            f"{expected_total or 0} after {self.max_catalog_passes} catalog passes"
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        attributes = record.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        szas = record.get("szas")
        szas = szas if isinstance(szas, dict) else {}
        links = record.get("links")
        links = links if isinstance(links, dict) else {}
        public_url = optional_text(links.get("directlink")) or self.base_url

        return ParsedJob(
            source=self.parser_id,
            title=(optional_text(record.get("title")) or optional_text(szas.get("sza_title"))),
            company=first_text(attributes.get("100")) or "Raiffeisen",
            location=extract_location(attributes, szas),
            url=public_url,
            apply_url=optional_text(szas.get("sza_apply_link")) or public_url,
            posted_at=optional_text(record.get("start_date")),
            employment_type=extract_employment_type(attributes, szas),
            seniority=optional_text(szas.get("sza_role")),
            description=extract_description(szas),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise RaiffeisenParseError("Raiffeisen jobs response must be an object")
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RaiffeisenParseError("Raiffeisen jobs response has an invalid total")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise RaiffeisenParseError("Raiffeisen jobs response has invalid jobs")

    records: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict):
            raise RaiffeisenParseError("Raiffeisen jobs response contains an invalid vacancy")
        links = item.get("links")
        if (
            not optional_text(item.get("id"))
            or not (
                optional_text(item.get("title"))
                or (
                    isinstance(item.get("szas"), dict)
                    and optional_text(item["szas"].get("sza_title"))
                )
            )
            or not isinstance(links, dict)
            or not optional_text(links.get("directlink"))
        ):
            raise RaiffeisenParseError("Raiffeisen jobs response contains an incomplete vacancy")
        records.append(item)
    return total, records


def extract_location(attributes: dict[str, Any], szas: dict[str, Any]) -> str | None:
    listed_location = first_text(attributes.get("arbeitsort"))
    if listed_location:
        return listed_location

    cities = [
        optional_text(szas.get("sza_location.city")),
        optional_text(szas.get("sza_location.2.city")),
        optional_text(szas.get("sza_location.3.city")),
    ]
    unique_cities = list(dict.fromkeys(city for city in cities if city))
    if unique_cities:
        return ", ".join(unique_cities)
    return optional_text(szas.get("sza_location"))


def extract_employment_type(
    attributes: dict[str, Any],
    szas: dict[str, Any],
) -> str | None:
    values = [
        optional_text(szas.get("sza_employment_type"))
        or first_text(attributes.get("beschaeftigungsart")),
        optional_text(szas.get("sza_pensum")) or first_text(attributes.get("53")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def extract_description(szas: dict[str, Any]) -> str | None:
    sections: list[str] = []
    for label, key in (
        ("Introduction", "sza_introduction"),
        ("Responsibilities", "sza_tasks"),
        ("Requirements", "sza_requirements"),
    ):
        content = html_to_text(szas.get(key))
        if content:
            sections.append(f"{label}\n{content}")

    benefits: list[str] = []
    for key in sorted(
        (key for key in szas if re.fullmatch(r"sza_benefits(?:_\d+)?", key)),
        key=benefit_sort_key,
    ):
        content = html_to_text(szas.get(key))
        if content and content not in benefits:
            benefits.append(content)
    if benefits:
        sections.append("Benefits\n" + "\n\n".join(benefits))
    return "\n\n".join(sections) or None


def benefit_sort_key(key: str) -> int:
    suffix = key.removeprefix("sza_benefits")
    return int(suffix.removeprefix("_") or 1)


def deduplicate_raiffeisen_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
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
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def first_text(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return next((text for item in value if (text := optional_text(item))), None)
    return optional_text(value)


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
