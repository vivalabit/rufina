from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

RINGIER_JOBS_BASE_URL = "https://career.ringier.ch/en/career"
RINGIER_JOBS_API_URL = "https://career.ringier.ch/api/jobs-ringier-en.json"
RINGIER_PROSPECTIVE_MEDIUM_ID = "2021"
RINGIER_SWITZERLAND = "Schweiz"
RINGIER_APPLY_URL_TEMPLATE = "https://ohws.prospective.ch/public/v1/redirect/{viewkey}/ats/"
RINGIER_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
NUMERIC_ID_PATTERN = re.compile(r"^\d+$")


class RingierParseError(DirectCompanyRequestError):
    pass


class RingierJobsParser:
    """Collect Ringier's Swiss full catalog from its cached Prospective feed."""

    parser_id = "ringier"

    def __init__(
        self,
        *,
        base_url: str = RINGIER_JOBS_BASE_URL,
        api_url: str = RINGIER_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={
                    **RINGIER_HEADERS,
                    "Origin": origin(self.base_url),
                    "Referer": self.base_url,
                },
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                records = parse_catalog_payload(
                    response.json(),
                    max_jobs=self.max_jobs,
                )
        except RingierParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Ringier vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Ringier vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ringier_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Swiss Ringier vacancies from the full Prospective catalog"
            ),
        )

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        attributes = record.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        szas = record.get("szas")
        szas = szas if isinstance(szas, dict) else {}
        links = record.get("links")
        links = links if isinstance(links, dict) else {}
        viewkey = optional_text(record.get("viewkey"))

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(record.get("title")),
            company=first_text(attributes.get("20")) or "Ringier",
            location=join_text(attributes.get("50")),
            url=optional_text(links.get("directlink")),
            apply_url=(RINGIER_APPLY_URL_TEMPLATE.format(viewkey=viewkey) if viewkey else None),
            posted_at=optional_text(record.get("start_date")),
            employment_type=extract_employment_type(attributes, szas),
            seniority=first_text(attributes.get("30")),
            description=extract_description(szas),
            raw=dict(record),
        )


def parse_catalog_payload(
    payload: Any,
    *,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise RingierParseError("Ringier jobs response must be an object")

    total = payload.get("total")
    offset = payload.get("offset")
    jobs = payload.get("jobs")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or offset != 0
        or not isinstance(jobs, list)
        or optional_text(payload.get("medium_id")) != RINGIER_PROSPECTIVE_MEDIUM_ID
    ):
        raise RingierParseError("Ringier jobs response is missing its full-catalog contract")
    if total != len(jobs):
        raise RingierParseError(f"Ringier returned {len(jobs)} vacancies but declared {total}")
    if total > max_jobs:
        raise RingierParseError(
            f"Ringier exposes {total} vacancies, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_viewkeys: set[str] = set()
    for item in jobs:
        if not isinstance(item, dict):
            raise RingierParseError("Ringier jobs response contains an invalid vacancy")
        job_id = optional_text(item.get("id"))
        viewkey = normalize_uuid(item.get("viewkey"))
        title = optional_text(item.get("title"))
        attributes = item.get("attributes")
        szas = item.get("szas")
        links = item.get("links")
        directlink = optional_text(links.get("directlink")) if isinstance(links, dict) else None
        if (
            not job_id
            or not NUMERIC_ID_PATTERN.fullmatch(job_id)
            or not viewkey
            or not title
            or not isinstance(attributes, dict)
            or not valid_attributes(attributes)
            or not isinstance(szas, dict)
            or optional_text(szas.get("sza_location.country")) != RINGIER_SWITZERLAND
            or not extract_description(szas)
            or not valid_directlink(directlink, viewkey=viewkey)
            or not optional_text(item.get("start_date"))
        ):
            raise RingierParseError("Ringier jobs response contains an incomplete Swiss vacancy")
        if job_id in seen_ids or viewkey in seen_viewkeys:
            raise RingierParseError("Ringier jobs response contains duplicate vacancy identifiers")
        seen_ids.add(job_id)
        seen_viewkeys.add(viewkey)
        records.append(dict(item))

    return records


def valid_attributes(attributes: dict[str, Any]) -> bool:
    return all(all_text(attributes.get(key)) for key in ("20", "50", "60"))


def valid_directlink(value: str | None, *, viewkey: str) -> bool:
    if not value:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == "jobs.ringier.ch"
        and parsed.path.startswith("/offene-stellen/")
        and parsed.path.rstrip("/").endswith(f"/{viewkey}")
    )


def normalize_uuid(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return str(UUID(text))
    except ValueError:
        return None


def extract_employment_type(
    attributes: dict[str, Any],
    szas: dict[str, Any],
) -> str | None:
    values = all_text(attributes.get("90"))
    workload = optional_text(szas.get("sza_pensum"))
    if workload and workload not in values:
        values.append(workload)
    return ", ".join(values) if values else None


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
    return "\n\n".join(sections) or None


def deduplicate_ringier_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def join_text(value: Any) -> str | None:
    values = list(dict.fromkeys(all_text(value)))
    return ", ".join(values) if values else None


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
