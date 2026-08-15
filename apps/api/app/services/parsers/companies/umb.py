from __future__ import annotations

import html
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

UMB_JOBS_BASE_URL = "https://www.umb.ch/unternehmen/it-jobs-bei-umb"
UMB_JOBS_API_URL = "https://api.smartrecruiters.com/v1/companies/UMBAG1/postings"
UMB_COMPANY_IDENTIFIER = "UMBAG1"
UMB_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}


class UmbParseError(DirectCompanyRequestError):
    pass


class UmbJobsParser:
    """Collect UMB's complete public catalog from SmartRecruiters."""

    parser_id = "umb"

    def __init__(
        self,
        *,
        base_url: str = UMB_JOBS_BASE_URL,
        api_url: str = UMB_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 20,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        page_size: int = 100,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.page_size = min(100, max(1, page_size))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**UMB_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, requests_made, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except UmbParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("UMB vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("UMB vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_umb_jobs(jobs)
        request_label = "request" if requests_made == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} UMB vacancies from {total} catalog records "
                f"across {requests_made} API {request_label}"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        requests_made = 0

        # Offset pages can shift while a vacancy is published. Repeat the walk
        # and union stable SmartRecruiters IDs until the declared total is seen.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            offset = 0
            page_number = 0

            while True:
                page_number += 1
                if page_number > self.max_pages:
                    raise UmbParseError(
                        f"UMB catalog exceeds the configured limit of {self.max_pages} pages"
                    )

                response = client.get(
                    self.api_url,
                    params={"limit": self.page_size, "offset": offset},
                )
                requests_made += 1
                response.raise_for_status()
                total, next_offset, page_records = parse_catalog_payload(
                    response.json(),
                    current_offset=offset,
                )

                if expected_total is None:
                    expected_total = total
                elif total != expected_total:
                    raise UmbParseError("UMB changed its vacancy total during pagination")

                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_offset"] = offset
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

                if len(records_by_id) > expected_total:
                    raise UmbParseError("UMB catalog changed while pages were collected")
                if next_offset is None:
                    break
                offset = next_offset

            if len(records_by_id) == (expected_total or 0):
                return list(records_by_id.values()), requests_made, expected_total or 0

        raise UmbParseError(
            f"UMB returned {len(records_by_id)} unique vacancies but declared {expected_total or 0}"
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(record["ref"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_payload(
                    response.json(),
                    expected_job_id=record["id"],
                )
            except (httpx.HTTPError, UmbParseError, TypeError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        source_record = detail or record
        job_id = optional_text(record.get("id"))
        posting_url = valid_posting_url(detail.get("postingUrl"), job_id=job_id)
        apply_url = valid_posting_url(
            detail.get("applyUrl"),
            job_id=job_id,
            require_apply_query=True,
        )
        fallback_url = public_posting_url(job_id)
        salary_min, salary_max, salary_currency, salary_unit = extract_compensation(
            detail.get("compensation")
        )

        return ParsedJob(
            source=self.parser_id,
            title=optional_text(source_record.get("name")),
            company=extract_company_name(source_record) or "UMB AG",
            location=extract_location(source_record),
            url=posting_url or fallback_url,
            apply_url=apply_url or posting_url or fallback_url,
            posted_at=optional_text(source_record.get("releasedDate")),
            employment_type=extract_employment_type(source_record),
            seniority=extract_seniority(source_record),
            description=extract_description(detail),
            salary=format_salary(
                salary_min,
                salary_max,
                salary_currency,
                salary_unit,
            ),
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            salary_unit=salary_unit,
            raw=dict(record),
        )


def parse_catalog_payload(
    payload: Any,
    *,
    current_offset: int,
) -> tuple[int, int | None, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise UmbParseError("UMB catalog response must be an object")
    offset = payload.get("offset")
    limit = payload.get("limit")
    total = payload.get("totalFound")
    content = payload.get("content")
    if offset != current_offset:
        raise UmbParseError("UMB catalog returned an unexpected offset")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise UmbParseError("UMB catalog response has an invalid limit")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise UmbParseError("UMB catalog response has an invalid total")
    if not isinstance(content, list):
        raise UmbParseError("UMB catalog response has invalid content")
    if current_offset > total:
        raise UmbParseError("UMB catalog returned an offset beyond its total")
    if total == 0 and content:
        raise UmbParseError("UMB empty catalog contains unexpected vacancies")
    if current_offset < total and not content:
        raise UmbParseError("UMB catalog returned an unexpectedly empty page")
    if len(content) > limit or current_offset + len(content) > total:
        raise UmbParseError("UMB catalog page exceeds its declared bounds")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in content:
        record = validate_listing_record(item)
        job_id = record["id"]
        if job_id in seen_ids:
            raise UmbParseError("UMB catalog page contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(record)

    next_offset = current_offset + len(records)
    return total, next_offset if next_offset < total else None, records


def validate_listing_record(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise UmbParseError("UMB catalog contains an invalid vacancy")
    job_id = extract_job_id(item.get("id"))
    title = optional_text(item.get("name"))
    company = item.get("company")
    location = item.get("location")
    custom_fields = item.get("customField")
    if (
        not job_id
        or not title
        or not valid_company(company)
        or optional_text(item.get("visibility")) != "PUBLIC"
        or not valid_swiss_location(location)
        or not isinstance(custom_fields, list)
        or not valid_api_reference(item.get("ref"), job_id=job_id)
        or not optional_text(item.get("releasedDate"))
    ):
        raise UmbParseError("UMB catalog contains an incomplete or non-Swiss vacancy")
    return {**item, "id": job_id, "name": title}


def parse_detail_payload(payload: Any, *, expected_job_id: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise UmbParseError("UMB vacancy detail response must be an object")
    job_id = extract_job_id(payload.get("id"))
    sections = nested_dict(payload, "jobAd", "sections")
    if (
        job_id != expected_job_id
        or payload.get("active") is not True
        or optional_text(payload.get("visibility")) != "PUBLIC"
        or not optional_text(payload.get("name"))
        or not valid_company(payload.get("company"))
        or not valid_swiss_location(payload.get("location"))
        or not valid_posting_url(payload.get("postingUrl"), job_id=job_id)
        or not valid_posting_url(
            payload.get("applyUrl"),
            job_id=job_id,
            require_apply_query=True,
        )
        or not optional_text(payload.get("releasedDate"))
        or not isinstance(sections, dict)
        or not extract_description(payload)
    ):
        raise UmbParseError("UMB vacancy detail response is incomplete or inconsistent")
    return dict(payload)


def valid_company(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and optional_text(value.get("identifier")) == UMB_COMPANY_IDENTIFIER
        and optional_text(value.get("name")) == "UMB AG"
    )


def valid_swiss_location(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    country = optional_text(value.get("country"))
    return (
        country is not None
        and country.casefold() == "ch"
        and bool(optional_text(value.get("city")) or optional_text(value.get("fullLocation")))
    )


def valid_api_reference(value: Any, *, job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "api.smartrecruiters.com"
        and parts.path == f"/v1/companies/{UMB_COMPANY_IDENTIFIER}/postings/{job_id}"
        and not parts.query
        and not parts.fragment
    )


def valid_posting_url(
    value: Any,
    *,
    job_id: str | None,
    require_apply_query: bool = False,
) -> str | None:
    text = optional_text(value)
    if not text or not job_id:
        return None
    parts = urlsplit(text)
    path_parts = [part for part in parts.path.split("/") if part]
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or len(path_parts) != 2
        or path_parts[0] != UMB_COMPANY_IDENTIFIER
        or not (path_parts[1] == job_id or path_parts[1].startswith(f"{job_id}-"))
        or parts.fragment
    ):
        return None
    query = parse_qs(parts.query)
    if require_apply_query and query.get("oga") != ["true"]:
        return None
    return text


def public_posting_url(job_id: str | None) -> str | None:
    if not job_id:
        return None
    return f"https://jobs.smartrecruiters.com/{UMB_COMPANY_IDENTIFIER}/{job_id}"


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    return text if text and text.isdigit() and int(text) > 0 else None


def extract_company_name(record: dict[str, Any]) -> str | None:
    company = record.get("company")
    return optional_text(company.get("name")) if isinstance(company, dict) else None


def extract_location(record: dict[str, Any]) -> str | None:
    location = record.get("location")
    location = location if isinstance(location, dict) else {}
    city = optional_text(location.get("city"))
    custom_location = custom_field_value(record, "Standort")
    if city and city.casefold() == "alle" and custom_location:
        label = custom_location
    else:
        full_location = optional_text(location.get("fullLocation"))
        if full_location:
            label = ", ".join(part.strip() for part in full_location.split(",") if part.strip())
        else:
            label = ", ".join(
                part
                for part in (
                    city,
                    optional_text(location.get("region")),
                    optional_text(location.get("country")),
                )
                if part
            )
    work_mode = "Remote" if location.get("remote") is True else None
    if location.get("hybrid") is True:
        work_mode = "Hybrid"
    if label and work_mode:
        return f"{label} ({work_mode})"
    return label or work_mode


def extract_employment_type(record: dict[str, Any]) -> str | None:
    employment = record.get("typeOfEmployment")
    employment_label = (
        optional_text(employment.get("label")) if isinstance(employment, dict) else None
    )
    workload = custom_field_value(record, "Pensum")
    if employment_label and workload:
        return f"{employment_label} ({workload})"
    return employment_label or workload


def extract_seniority(record: dict[str, Any]) -> str | None:
    custom = custom_field_value(record, "Experience Level")
    if custom:
        return custom
    experience = record.get("experienceLevel")
    return optional_text(experience.get("label")) if isinstance(experience, dict) else None


def custom_field_value(record: dict[str, Any], label: str) -> str | None:
    fields = record.get("customField")
    if not isinstance(fields, Sequence) or isinstance(fields, (str, bytes)):
        return None
    for field in fields:
        if isinstance(field, dict) and optional_text(field.get("fieldLabel")) == label:
            return optional_text(field.get("valueLabel"))
    return None


def extract_description(record: dict[str, Any]) -> str | None:
    sections = nested_dict(record, "jobAd", "sections")
    if not isinstance(sections, dict):
        return None
    values: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        text = html_to_text(optional_text(section.get("text")))
        if not text:
            continue
        title = optional_text(section.get("title"))
        value = f"{title}\n{text}" if title else text
        if value not in values:
            values.append(value)
    return "\n\n".join(values) or None


def extract_compensation(
    value: Any,
) -> tuple[int | None, int | None, str | None, str | None]:
    if not isinstance(value, dict):
        return None, None, None, None
    minimum = optional_int(value.get("min"))
    maximum = optional_int(value.get("max"))
    currency = optional_text(value.get("currency"))
    period = optional_text(value.get("period"))
    return minimum, maximum, currency, period.casefold() if period else None


def format_salary(
    minimum: int | None,
    maximum: int | None,
    currency: str | None,
    unit: str | None,
) -> str | None:
    if minimum is None and maximum is None:
        return None
    if minimum is not None and maximum is not None:
        amount = f"{minimum:,}-{maximum:,}"
    elif minimum is not None:
        amount = f"From {minimum:,}"
    else:
        amount = f"Up to {maximum:,}"
    suffix = " ".join(value for value in (currency, unit) if value)
    return f"{amount} {suffix}".strip()


def deduplicate_umb_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def nested_dict(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(value)
    text = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"[\s\u200b]+", " ", str(value)).strip()
    return normalized or None
