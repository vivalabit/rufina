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

KPMG_SWITZERLAND_JOBS_BASE_URL = (
    "https://kpmg.com/ch/de/karriere/offene-stellen.html"
)
KPMG_SWITZERLAND_JOBS_API_URL = (
    "https://ohws.prospective.ch/public/v1/medium/1693/jobs"
)
KPMG_SWITZERLAND_RESULTS_PER_PAGE = 96
KPMG_SWITZERLAND_APPLY_BASE_URL = (
    "https://recruitingapp-2791.umantis.com/Vacancies"
)
KPMG_SWITZERLAND_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7,fr;q=0.6",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
APPLY_LANGUAGE_CODES = {"de": "ger", "en": "eng", "fr": "fre", "it": "ita"}


class KpmgSwitzerlandParseError(DirectCompanyRequestError):
    pass


class KpmgSwitzerlandJobsParser:
    """Collect KPMG Switzerland's full catalog from its Prospective API."""

    parser_id = "kpmg_switzerland"

    def __init__(
        self,
        *,
        base_url: str = KPMG_SWITZERLAND_JOBS_BASE_URL,
        api_url: str = KPMG_SWITZERLAND_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
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
                    **KPMG_SWITZERLAND_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
        except KpmgSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "KPMG Switzerland vacancy request failed"
            ) from exc
        except Exception as exc:
            raise DirectCompanyRequestError(
                "KPMG Switzerland vacancy parsing failed"
            ) from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_kpmg_switzerland_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} KPMG Switzerland vacancies from {total} "
                f"catalog records across {pages_fetched} API page requests"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Offset pages may move while vacancies are published. Repeat the walk
        # and union stable Prospective IDs when a pass contains overlap.
        for catalog_pass in range(self.max_catalog_passes):
            offsets = (
                list(range(0, expected_total, KPMG_SWITZERLAND_RESULTS_PER_PAGE))
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
                        "limit": KPMG_SWITZERLAND_RESULTS_PER_PAGE,
                    },
                )
                pages_fetched += 1
                response.raise_for_status()
                page_total, records = parse_listing_payload(response.json())

                if expected_total is None:
                    expected_total = page_total
                    required_pages = max(
                        1,
                        ceil(expected_total / KPMG_SWITZERLAND_RESULTS_PER_PAGE),
                    )
                    if required_pages > self.max_pages:
                        raise KpmgSwitzerlandParseError(
                            f"KPMG Switzerland exposes {required_pages} pages, "
                            f"above the configured limit of {self.max_pages}"
                        )
                    offsets.extend(
                        range(
                            KPMG_SWITZERLAND_RESULTS_PER_PAGE,
                            expected_total,
                            KPMG_SWITZERLAND_RESULTS_PER_PAGE,
                        )
                    )
                elif page_total != expected_total:
                    raise KpmgSwitzerlandParseError(
                        "KPMG Switzerland changed its vacancy total during pagination"
                    )

                if offset < (expected_total or 0) and not records:
                    raise KpmgSwitzerlandParseError(
                        f"KPMG Switzerland page at offset {offset} was unexpectedly empty"
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
                raise KpmgSwitzerlandParseError(
                    "KPMG Switzerland returned more vacancies than its declared total"
                )
            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), pages_fetched, expected_total or 0
            if len(records_by_id) > (expected_total or 0):
                raise KpmgSwitzerlandParseError(
                    "KPMG Switzerland returned more unique vacancies than its "
                    "declared total"
                )

        raise KpmgSwitzerlandParseError(
            f"KPMG Switzerland yielded only {len(records_by_id)} unique vacancies "
            f"of {expected_total or 0} after {self.max_catalog_passes} catalog passes"
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
            title=(
                optional_text(record.get("title"))
                or optional_text(szas.get("sza_title"))
            ),
            company="KPMG AG",
            location=extract_location(attributes, szas),
            url=public_url,
            apply_url=build_apply_url(record, szas) or public_url,
            posted_at=optional_text(record.get("start_date")),
            employment_type=extract_employment_type(attributes, szas),
            seniority=(
                optional_text(szas.get("sza_role")) or first_text(attributes.get("70"))
            ),
            description=extract_description(szas),
            raw=dict(record),
        )


def parse_listing_payload(payload: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise KpmgSwitzerlandParseError(
            "KPMG Switzerland jobs response must be an object"
        )
    total = payload.get("total")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise KpmgSwitzerlandParseError(
            "KPMG Switzerland jobs response has an invalid total"
        )
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise KpmgSwitzerlandParseError(
            "KPMG Switzerland jobs response has invalid jobs"
        )

    records: list[dict[str, Any]] = []
    for item in jobs:
        if not isinstance(item, dict):
            raise KpmgSwitzerlandParseError(
                "KPMG Switzerland jobs response contains an invalid vacancy"
            )
        links = item.get("links")
        szas = item.get("szas")
        if (
            not optional_text(item.get("id"))
            or not optional_text(item.get("viewkey"))
            or not (
                optional_text(item.get("title"))
                or (
                    isinstance(szas, dict)
                    and optional_text(szas.get("sza_title"))
                )
            )
            or not isinstance(links, dict)
            or not optional_text(links.get("directlink"))
            or not isinstance(szas, dict)
            or not optional_text(szas.get("sza_apply_link"))
        ):
            raise KpmgSwitzerlandParseError(
                "KPMG Switzerland jobs response contains an incomplete vacancy"
            )
        records.append(item)
    return total, records


def extract_location(attributes: dict[str, Any], szas: dict[str, Any]) -> str | None:
    listed_locations = all_text(attributes.get("30"))
    if listed_locations:
        return ", ".join(dict.fromkeys(listed_locations))

    cities = [
        optional_text(szas.get("sza_location.city")),
        optional_text(szas.get("sza_location.2.city")),
        optional_text(szas.get("sza_workplace.city")),
    ]
    unique_cities = list(dict.fromkeys(city for city in cities if city))
    return ", ".join(unique_cities) if unique_cities else None


def extract_employment_type(
    attributes: dict[str, Any],
    szas: dict[str, Any],
) -> str | None:
    employment = (
        optional_text(szas.get("sza_employment_type"))
        or first_text(attributes.get("50"))
    )
    minimum = optional_text(szas.get("sza_pensum.min"))
    maximum = optional_text(szas.get("sza_pensum.max"))
    workload: str | None = None
    if minimum and maximum:
        workload = f"{minimum}%" if minimum == maximum else f"{minimum}–{maximum}%"
    elif minimum or maximum:
        workload = f"{minimum or maximum}%"
    elif value := optional_text(szas.get("sza_pensum")):
        workload = value
    values = list(dict.fromkeys(value for value in (employment, workload) if value))
    return ", ".join(values) if values else None


def build_apply_url(record: dict[str, Any], szas: dict[str, Any]) -> str | None:
    vacancy_id = optional_text(szas.get("sza_apply_link"))
    source_id = optional_text(record.get("id"))
    if not vacancy_id or not source_id:
        return None
    language = optional_text(record.get("language")) or "de"
    language_code = APPLY_LANGUAGE_CODES.get(language.casefold(), "ger")
    return (
        f"{KPMG_SWITZERLAND_APPLY_BASE_URL}/{vacancy_id}/Application/CheckLogin"
        f"?srcIDPMS={source_id}&srcTextPMS=%canalname%&lang={language_code}"
    )


def extract_description(szas: dict[str, Any]) -> str | None:
    sections: list[str] = []
    for label, key in (
        ("Responsibilities", "sza_tasks"),
        ("Requirements", "sza_requirements"),
        ("About KPMG", "sza_company_profil"),
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

    contact = html_to_text(szas.get("sza_contact"))
    if contact:
        sections.append(f"Contact\n{contact}")
    return "\n\n".join(sections) or None


def benefit_sort_key(key: str) -> int:
    suffix = key.removeprefix("sza_benefits")
    return int(suffix.removeprefix("_") or 1)


def deduplicate_kpmg_switzerland_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
    return next(iter(all_text(value)), None)


def all_text(value: Any) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [text for item in value if (text := optional_text(item))]
    text = optional_text(value)
    return [text] if text else []


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
