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

PWC_SWITZERLAND_JOBS_BASE_URL = "https://www.pwc.ch/en/careers-with-pwc/open-positions.html"
PWC_SWITZERLAND_JOBS_API_URL = "https://ohws.prospective.ch/public/v1/medium/1000311/jobs"
PWC_SWITZERLAND_MEDIUM_ID = "1000311"
PWC_SWITZERLAND_HK_ID = "1008576"
PWC_SWITZERLAND_RESULTS_PER_PAGE = 96
PWC_SWITZERLAND_ALLOWED_COUNTRIES = {
    "schweiz",
    "switzerland",
    "liechtenstein",
}
PWC_SWITZERLAND_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
VIEWKEY_PATTERN = re.compile(
    r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
DIRECT_JOB_PATH_PATTERN = re.compile(
    r"^/job-vacancies/[a-z0-9]+(?:-[a-z0-9]+)*/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
WORKDAY_APPLY_PATH_PATTERN = re.compile(
    r"^/(?:Global_Experienced_Careers|Global_Campus_Careers)/job/[^/]+/[^/]+(?:/apply)?/?$",
    re.IGNORECASE,
)


class PwcSwitzerlandParseError(DirectCompanyRequestError):
    pass


class PwcSwitzerlandJobsParser:
    """Collect PwC Switzerland's complete public Prospective catalog."""

    parser_id = "pwc_switzerland"

    def __init__(
        self,
        *,
        base_url: str = PWC_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = PWC_SWITZERLAND_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **PWC_SWITZERLAND_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total, catalog_passes = self.collect_listing_records(client)
        except PwcSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("PwC Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("PwC Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_pwc_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} PwC Switzerland vacancies from {total} "
                f"Prospective records across {pages_fetched} API page requests "
                f"in {catalog_passes} catalog pass(es)"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            offsets = (
                list(range(0, expected_total, PWC_SWITZERLAND_RESULTS_PER_PAGE))
                if expected_total
                else [0]
            )
            pass_records = 0

            for offset in offsets:
                response = client.get(
                    self.api_url,
                    params={
                        "lang": "en",
                        "offset": offset,
                        "limit": PWC_SWITZERLAND_RESULTS_PER_PAGE,
                    },
                )
                response.raise_for_status()
                pages_fetched += 1
                page_total, page_offset, records = parse_listing_payload(response.json())
                if page_offset != offset:
                    raise PwcSwitzerlandParseError(
                        f"PwC Switzerland returned offset {page_offset} for "
                        f"requested offset {offset}"
                    )

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / PWC_SWITZERLAND_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise PwcSwitzerlandParseError(
                            f"PwC Switzerland exposes {required_pages} pages, above "
                            f"the configured limit of {self.max_pages}"
                        )
                    offsets.extend(
                        range(
                            PWC_SWITZERLAND_RESULTS_PER_PAGE,
                            expected_total,
                            PWC_SWITZERLAND_RESULTS_PER_PAGE,
                        )
                    )
                elif page_total != expected_total:
                    raise PwcSwitzerlandParseError(
                        "PwC Switzerland changed its vacancy total during pagination"
                    )

                if offset < (expected_total or 0) and not records:
                    raise PwcSwitzerlandParseError(
                        f"PwC Switzerland page at offset {offset} was unexpectedly empty"
                    )
                expected_page_size = min(
                    PWC_SWITZERLAND_RESULTS_PER_PAGE,
                    max(0, (expected_total or 0) - offset),
                )
                if len(records) != expected_page_size:
                    raise PwcSwitzerlandParseError(
                        f"PwC Switzerland page at offset {offset} returned "
                        f"{len(records)} records instead of {expected_page_size}"
                    )

                pass_records += len(records)
                for record in records:
                    job_id = optional_text(record.get("id"))
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(job_id or "", normalized)

            if pass_records > (expected_total or 0):
                raise PwcSwitzerlandParseError(
                    "PwC Switzerland returned more vacancies than its declared total"
                )
            if len(records_by_id) == (expected_total or 0):
                return (
                    list(records_by_id.values()),
                    pages_fetched,
                    expected_total or 0,
                    catalog_pass,
                )
            if len(records_by_id) > (expected_total or 0):
                raise PwcSwitzerlandParseError(
                    "PwC Switzerland returned more unique vacancies than its declared total"
                )

        raise PwcSwitzerlandParseError(
            f"PwC Switzerland yielded only {len(records_by_id)} unique vacancies "
            f"of {expected_total or 0} after {self.max_catalog_passes} catalog passes"
        )


def parse_listing_payload(payload: Any) -> tuple[int, int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise PwcSwitzerlandParseError("PwC Switzerland jobs response must be an object")
    if payload.get("medium_id") != PWC_SWITZERLAND_MEDIUM_ID:
        raise PwcSwitzerlandParseError("PwC Switzerland jobs response has an unexpected medium ID")
    total = payload.get("total")
    offset = payload.get("offset")
    jobs = payload.get("jobs")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise PwcSwitzerlandParseError("PwC Switzerland jobs response has an invalid total")
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise PwcSwitzerlandParseError("PwC Switzerland jobs response has an invalid offset")
    if not isinstance(jobs, list):
        raise PwcSwitzerlandParseError("PwC Switzerland jobs response has invalid jobs")

    records: list[dict[str, Any]] = []
    for item in jobs:
        validate_listing_record(item)
        records.append(item)
    return total, offset, records


def validate_listing_record(item: Any) -> None:
    if not isinstance(item, dict):
        raise PwcSwitzerlandParseError("PwC Switzerland jobs response contains an invalid vacancy")
    attributes = item.get("attributes")
    szas = item.get("szas")
    links = item.get("links")
    job_id = optional_text(item.get("id"))
    viewkey = optional_text(item.get("viewkey"))
    title = optional_text(item.get("title"))
    country = optional_text(szas.get("sza_location.country")) if isinstance(szas, dict) else None
    profile = html_to_text(szas.get("sza_company_profil")) if isinstance(szas, dict) else None
    direct_url = optional_text(links.get("directlink")) if isinstance(links, dict) else None
    apply_url = optional_text(szas.get("sza_apply_link")) if isinstance(szas, dict) else None
    if (
        not job_id
        or optional_text(item.get("hk_id")) != PWC_SWITZERLAND_HK_ID
        or not viewkey
        or not VIEWKEY_PATTERN.fullmatch(viewkey)
        or not title
        or not isinstance(attributes, dict)
        or not all(all_text(attributes.get(key)) for key in ("10", "20", "30", "40", "50"))
        or not isinstance(szas, dict)
        or not optional_text(szas.get("sza_title"))
        or not optional_text(szas.get("sza_tasks"))
        or not optional_text(szas.get("sza_requirements"))
        or not optional_text(szas.get("sza_employment_type"))
        or not optional_text(szas.get("sza_pensum"))
        or not optional_text(szas.get("sza_reference_code"))
        or not country
        or country.casefold() not in PWC_SWITZERLAND_ALLOWED_COUNTRIES
        or not profile
        or not is_pwc_switzerland_profile(profile)
        or not is_direct_job_url(direct_url, expected_viewkey=viewkey)
        or not is_workday_apply_url(apply_url)
    ):
        raise PwcSwitzerlandParseError(
            "PwC Switzerland jobs response contains an incomplete or out-of-scope vacancy"
        )


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    attributes = record.get("attributes")
    attributes = attributes if isinstance(attributes, dict) else {}
    szas = record.get("szas")
    szas = szas if isinstance(szas, dict) else {}
    links = record.get("links")
    links = links if isinstance(links, dict) else {}
    public_url = optional_text(links.get("directlink"))
    return ParsedJob(
        source="pwc_switzerland",
        title=optional_text(record.get("title")) or optional_text(szas.get("sza_title")),
        company="PwC Switzerland",
        location=extract_location(attributes, szas),
        url=public_url,
        apply_url=optional_text(szas.get("sza_apply_link")) or public_url,
        posted_at=optional_text(record.get("start_date")),
        employment_type=extract_employment_type(attributes, szas),
        seniority=first_text(attributes.get("10")),
        description=extract_description(szas),
        raw=dict(record),
    )


def extract_location(
    attributes: dict[str, Any],
    szas: dict[str, Any],
) -> str | None:
    locations = all_text(attributes.get("20"))
    if locations:
        return "; ".join(dict.fromkeys(locations))
    city = optional_text(szas.get("sza_location.city"))
    country = optional_text(szas.get("sza_location.country"))
    return ", ".join(value for value in (city, country) if value) or None


def extract_employment_type(
    attributes: dict[str, Any],
    szas: dict[str, Any],
) -> str | None:
    values = [
        optional_text(szas.get("sza_employment_type")),
        optional_text(szas.get("sza_pensum")),
        *all_text(attributes.get("40")),
    ]
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def extract_description(szas: dict[str, Any]) -> str | None:
    sections: list[str] = []
    for label, key in (
        ("Introduction", "sza_introduction"),
        ("Responsibilities", "sza_tasks"),
        ("Requirements", "sza_requirements"),
        ("About PwC Switzerland", "sza_company_profil"),
    ):
        content = html_to_text(szas.get(key))
        if content:
            sections.append(f"{label}\n{content}")
    return "\n\n".join(sections) or None


def is_pwc_switzerland_profile(value: str) -> bool:
    normalized = value.casefold()
    return normalized.startswith(("at pwc switzerland", "bei pwc schweiz"))


def is_direct_job_url(value: Any, *, expected_viewkey: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = DIRECT_JOB_PATH_PATTERN.fullmatch(parts.path)
    return bool(
        parts.scheme == "https"
        and parts.hostname == "jobs.pwc.ch"
        and not parts.query
        and not parts.fragment
        and match
        and match.group(1).casefold() == expected_viewkey.casefold()
    )


def is_workday_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return bool(
        parts.scheme == "https"
        and parts.hostname == "pwc.wd3.myworkdayjobs.com"
        and WORKDAY_APPLY_PATH_PATTERN.fullmatch(parts.path)
        and not parts.query
        and not parts.fragment
    )


def deduplicate_pwc_switzerland_jobs(
    jobs: Iterable[ParsedJob],
) -> list[ParsedJob]:
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
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(
        r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>",
        "\n",
        text,
    )
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(html.unescape(text)))


def first_text(value: Any) -> str | None:
    return next(iter(all_text(value)), None)


def all_text(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [text for item in value if (text := optional_text(item))]
    text = optional_text(value)
    return [text] if text else []


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
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"
