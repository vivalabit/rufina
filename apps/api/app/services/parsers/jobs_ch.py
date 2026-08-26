from __future__ import annotations

import html
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from urllib.parse import urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import httpx

from app.models.parsers import JobsChSearchRequest, ParsedJob, ParserSearchResponse

JOBS_CH_BASE_URL = "https://www.jobs.ch"
JOBS_CH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    )
}
JOBS_CH_DATE_POSTED = {
    "Past 24 hours": 1,
    "Past week": 7,
    "Past month": 30,
}
JOBS_CH_TIMEZONE = ZoneInfo("Europe/Zurich")


class JobsChParseError(RuntimeError):
    pass


class JobsChRequestError(RuntimeError):
    pass


class JobsChParser:
    """Search public jobs.ch pages and normalize their structured job data."""

    parser_id = "jobs_ch"

    def __init__(
        self,
        *,
        base_url: str = JOBS_CH_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: JobsChSearchRequest) -> ParserSearchResponse:
        search_terms = split_search_terms(request.keywords)
        query_terms: list[str | None] = search_terms or [None]
        search_url = self.build_search_url(request, keyword=query_terms[0])
        records_by_term: list[list[dict[str, Any]]] = []
        seen_ids: set[str] = set()
        completed_query = False
        last_error: Exception | None = None

        with httpx.Client(
            headers=JOBS_CH_HEADERS,
            timeout=self.timeout_seconds,
            follow_redirects=True,
            transport=self.transport,
        ) as client:
            for keyword in query_terms:
                term_records: list[dict[str, Any]] = []
                for page in range(1, self.max_pages + 1):
                    params = self.build_search_params(request, page=page, keyword=keyword)
                    try:
                        response = client.get(f"{self.base_url}/en/vacancies/", params=params)
                        response.raise_for_status()
                        init_state = extract_js_object(response.text, "__INIT__ =")
                        bucket = get_results_bucket(init_state)
                        completed_query = True
                    except (httpx.HTTPError, JobsChParseError, json.JSONDecodeError) as exc:
                        last_error = exc
                        break

                    rows = bucket.get("results", []) if isinstance(bucket, dict) else []
                    if not isinstance(rows, list) or not rows:
                        break

                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        vacancy_id = str(row.get("id") or "").strip()
                        if not vacancy_id or vacancy_id in seen_ids:
                            continue
                        seen_ids.add(vacancy_id)
                        record = dict(row)
                        record["search_url"] = str(response.url)
                        record["search_term"] = keyword
                        term_records.append(record)
                        if len(term_records) >= request.results_limit:
                            break

                    if len(term_records) >= request.results_limit:
                        break

                    meta = bucket.get("meta", {}) if isinstance(bucket, dict) else {}
                    num_pages = meta.get("numPages") if isinstance(meta, dict) else None
                    if not isinstance(num_pages, int) or page >= num_pages:
                        break

                records_by_term.append(term_records)

            if not completed_query and last_error is not None:
                raise JobsChRequestError("jobs.ch search request failed") from last_error

            selected_records = interleave_records(records_by_term, request.results_limit)
            self.enrich_records(client, selected_records)

        jobs: list[ParsedJob] = []
        for record in selected_records:
            job = self.normalize_job(record)
            filter_date = first_string(record.get("initialPublicationDate")) or job.posted_at
            if request.date_posted != "Any time" and not is_within_date_posted_window(
                filter_date,
                request.date_posted,
            ):
                continue
            jobs.append(job)
        if request.deduplicate:
            jobs = self.deduplicate(jobs)

        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=search_url,
            jobs=jobs[: request.results_limit],
            message=self.unsupported_filters_message(request),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        if not records:
            return

        def fetch_detail(record: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
            vacancy_id = str(record.get("id") or "").strip()
            detail_url = self.build_detail_url(vacancy_id)
            headers = {"Referer": str(record.get("search_url") or "")} if record.get("search_url") else None
            try:
                response = client.get(detail_url, headers=headers)
                response.raise_for_status()
                return record, response.text
            except httpx.HTTPError as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, page_html = future.result()
                if not page_html:
                    continue
                schema = extract_job_posting_schema(page_html)
                if schema:
                    record["job_posting_schema"] = schema
                salary = extract_salary_info(page_html, schema)
                if salary:
                    record["detail_salary"] = salary

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        schema = record.get("job_posting_schema")
        schema = schema if isinstance(schema, dict) else {}
        vacancy_id = str(record.get("id") or "").strip()
        url = normalize_jobs_ch_url(first_string(schema.get("url"))) or self.build_detail_url(
            vacancy_id
        )
        description_html = first_string(schema.get("description"))
        salary = record.get("detail_salary")
        salary = salary if isinstance(salary, dict) else {}

        return ParsedJob(
            source=self.parser_id,
            title=first_string(schema.get("title")) or first_string(record.get("title")),
            company=extract_company(record, schema),
            location=extract_location(record, schema),
            url=url,
            apply_url=normalize_jobs_ch_url(extract_apply_url(schema)) or url,
            posted_at=(
                first_string(schema.get("datePosted"))
                or first_string(record.get("publicationDate"))
                or first_string(record.get("initialPublicationDate"))
            ),
            employment_type=first_string(schema.get("employmentType")),
            seniority=extract_seniority(schema),
            description=html_to_text(description_html) if description_html else None,
            salary=first_string(salary.get("text")),
            salary_min=optional_int(salary.get("minimum")),
            salary_max=optional_int(salary.get("maximum")),
            salary_currency=first_string(salary.get("currency")),
            salary_unit=first_string(salary.get("unit")),
            raw=record,
        )

    def build_detail_url(self, vacancy_id: str) -> str:
        return f"{self.base_url}/en/vacancies/detail/{vacancy_id}/"

    def build_search_url(
        self,
        request: JobsChSearchRequest,
        *,
        keyword: str | None = None,
    ) -> str:
        query = urlencode(self.build_search_params(request, page=1, keyword=keyword))
        base = f"{self.base_url}/en/vacancies/"
        return f"{base}?{query}" if query else base

    @staticmethod
    def build_search_params(
        request: JobsChSearchRequest,
        *,
        page: int,
        keyword: str | None = None,
    ) -> dict[str, str | int]:
        params: dict[str, str | int] = {}
        effective_keyword = request.keywords.strip() if keyword is None else keyword.strip()
        if effective_keyword:
            params["term"] = effective_keyword
        if request.location.strip():
            params["location"] = request.location.strip()
        if request.date_posted in JOBS_CH_DATE_POSTED:
            params["publication-date"] = JOBS_CH_DATE_POSTED[request.date_posted]
        if page > 1:
            params["page"] = page
        return params

    @staticmethod
    def unsupported_filters_message(request: JobsChSearchRequest) -> str | None:
        unsupported: list[str] = []
        if request.remote != "Any":
            unsupported.append("remote")
        if request.experience_level != "Any":
            unsupported.append("experience level")
        if request.job_type != "Any":
            unsupported.append("job type")
        if request.country not in {"Any", "Switzerland"}:
            unsupported.append("country")
        if not unsupported:
            return None
        return f"jobs.ch does not apply these filters: {', '.join(unsupported)}"

    @staticmethod
    def deduplicate(jobs: list[ParsedJob]) -> list[ParsedJob]:
        seen: set[str] = set()
        unique_jobs: list[ParsedJob] = []
        for job in jobs:
            key = job.url or f"{job.title}|{job.company}|{job.location}"
            if key in seen:
                continue
            seen.add(key)
            unique_jobs.append(job)
        return unique_jobs


def split_search_terms(keywords: str) -> list[str]:
    """Split an OR expression into stable, case-insensitively unique searches."""
    terms: list[str] = []
    seen: set[str] = set()
    for value in re.split(r"\s+OR\s+", keywords.strip(), flags=re.IGNORECASE):
        term = value.strip()
        normalized = term.casefold()
        if not term or normalized in seen:
            continue
        seen.add(normalized)
        terms.append(term)
    return terms


def interleave_records(
    records_by_term: list[list[dict[str, Any]]],
    limit: int,
) -> list[dict[str, Any]]:
    """Merge term results fairly while retaining each query's source ordering."""
    selected: list[dict[str, Any]] = []
    longest = max((len(records) for records in records_by_term), default=0)
    for index in range(longest):
        for records in records_by_term:
            if index >= len(records):
                continue
            selected.append(records[index])
            if len(selected) >= limit:
                return selected
    return selected


def extract_js_object(text: str, marker: str) -> dict[str, Any]:
    marker_pos = text.find(marker)
    if marker_pos == -1:
        raise JobsChParseError(f"Marker not found: {marker}")

    start = text.find("{", marker_pos)
    if start == -1:
        raise JobsChParseError(f"JSON object not found after marker: {marker}")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        character = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(text[start : index + 1])
                if not isinstance(parsed, dict):
                    raise JobsChParseError("jobs.ch init state is not an object")
                return parsed
    raise JobsChParseError(f"Unclosed JSON object after marker: {marker}")


def get_results_bucket(init_state: dict[str, Any]) -> dict[str, Any]:
    vacancy = init_state.get("vacancy", {})
    results = vacancy.get("results", {}) if isinstance(vacancy, dict) else {}
    bucket = results.get("main", {}) if isinstance(results, dict) else {}
    return bucket if isinstance(bucket, dict) else {}


def is_within_date_posted_window(
    value: str | None,
    date_posted: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Verify jobs.ch dates locally because promoted results can bypass URL filters."""
    max_days = JOBS_CH_DATE_POSTED.get(date_posted)
    if max_days is None:
        return date_posted == "Any time"

    posted_at = parse_jobs_ch_datetime(value)
    if posted_at is None:
        return False

    reference = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=JOBS_CH_TIMEZONE)
    age = reference.astimezone(UTC) - posted_at.astimezone(UTC)
    return timedelta(0) <= age <= timedelta(days=max_days)


def parse_jobs_ch_datetime(value: str | None) -> datetime | None:
    if not value or not value.strip():
        return None

    raw = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
            return datetime.combine(date.fromisoformat(raw), time.min, tzinfo=JOBS_CH_TIMEZONE)
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=JOBS_CH_TIMEZONE)


def extract_job_posting_schema(page_html: str) -> dict[str, Any] | None:
    pattern = re.compile(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(page_html):
        try:
            parsed = json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            continue
        items = parsed if isinstance(parsed, list) else [parsed]
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            if item_type == "JobPosting" or (
                isinstance(item_type, list) and "JobPosting" in item_type
            ):
                return item
    return None


def extract_salary_info(
    page_html: str,
    schema: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    schema_salary = extract_schema_salary(schema or {})
    if schema_salary and (
        schema_salary.get("minimum") is not None or schema_salary.get("maximum") is not None
    ):
        return schema_salary

    for candidate in find_salary_candidates(page_html):
        parsed = parse_salary_range_text(candidate)
        if parsed:
            return parsed
    return schema_salary


def extract_schema_salary(schema: dict[str, Any]) -> dict[str, Any] | None:
    base_salary = schema.get("baseSalary")
    if not isinstance(base_salary, dict):
        return None

    currency = first_string(base_salary.get("currency"))
    value = base_salary.get("value")
    minimum: int | None = None
    maximum: int | None = None
    unit: str | None = None
    if isinstance(value, dict):
        minimum = optional_int(value.get("minValue"))
        maximum = optional_int(value.get("maxValue"))
        single_value = optional_int(value.get("value"))
        minimum = minimum if minimum is not None else single_value
        maximum = maximum if maximum is not None else single_value
        unit = normalize_salary_unit(first_string(value.get("unitText")))
    else:
        single_value = optional_int(value)
        minimum = single_value
        maximum = single_value

    if not any((currency, minimum is not None, maximum is not None, unit)):
        return None
    return {
        "minimum": minimum,
        "maximum": maximum,
        "currency": currency,
        "unit": unit,
        "text": format_salary(currency, minimum, maximum, unit),
    }


def find_salary_candidates(page_html: str) -> list[str]:
    patterns = [
        re.compile(
            r'<li[^>]*data-cy=["\'][^"\']*salary[^"\']*["\'][^>]*>(.*?)</li>',
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r'<div[^>]*data-cy=["\'][^"\']*salary[^"\']*["\'][^>]*>(.*?)</div>',
            re.IGNORECASE | re.DOTALL,
        ),
    ]
    candidates: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for match in pattern.finditer(page_html):
            candidate = " ".join(html_to_text(match.group(1)).split())
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
    full_page_text = " ".join(html_to_text(page_html).split())
    if full_page_text and full_page_text not in seen:
        candidates.append(full_page_text)
    return candidates


def parse_salary_range_text(value: str) -> dict[str, Any] | None:
    number_pattern = r"(?:\d{1,3}(?:[\s'’.,]\d{3})+|\d+)"
    match = re.search(
        r"(?P<currency>CHF|EUR|USD|GBP)\s*"
        rf"(?P<minimum>{number_pattern})\s*(?:-|–|—|to|bis)\s*"
        rf"(?P<maximum>{number_pattern})"
        r"(?:\s*(?:/|per|pro)\s*(?P<unit>an|year|jahr|mois|month|monat|heure|hour|stunde))?",
        " ".join(value.split()),
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    minimum = optional_int(match.group("minimum"))
    maximum = optional_int(match.group("maximum"))
    if minimum is None or maximum is None:
        return None
    unit = normalize_salary_unit(match.group("unit"))
    if unit is None and max(minimum, maximum) >= 1000:
        unit = "YEAR"
    currency = match.group("currency").upper()
    return {
        "minimum": minimum,
        "maximum": maximum,
        "currency": currency,
        "unit": unit,
        "text": format_salary(currency, minimum, maximum, unit),
    }


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        digits = re.sub(r"[^\d]", "", value)
        return int(digits) if digits else None
    return None


def normalize_salary_unit(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().lower()
    mapping = {
        "an": "YEAR",
        "year": "YEAR",
        "jahr": "YEAR",
        "mois": "MONTH",
        "month": "MONTH",
        "monat": "MONTH",
        "heure": "HOUR",
        "hour": "HOUR",
        "stunde": "HOUR",
    }
    return mapping.get(normalized, normalized.upper())


def format_salary(
    currency: str | None,
    minimum: int | None,
    maximum: int | None,
    unit: str | None,
) -> str | None:
    if minimum is None and maximum is None:
        return None
    prefix = f"{currency} " if currency else ""
    if minimum is not None and maximum is not None:
        amount = str(minimum) if minimum == maximum else f"{minimum}-{maximum}"
    else:
        amount = str(minimum if minimum is not None else maximum)
    suffix = f" / {unit.lower()}" if unit else ""
    return f"{prefix}{amount}{suffix}"


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def first_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, list):
        values = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(values) or None
    return None


def extract_company(record: dict[str, Any], schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    if isinstance(organization, dict):
        company = first_string(organization.get("name"))
        if company:
            return company
    company = record.get("company")
    if isinstance(company, dict):
        return first_string(company.get("name"))
    return first_string(company)


def extract_location(record: dict[str, Any], schema: dict[str, Any]) -> str | None:
    place = first_string(record.get("place"))
    if place:
        return place
    job_location = schema.get("jobLocation")
    if isinstance(job_location, list):
        job_location = job_location[0] if job_location else None
    if not isinstance(job_location, dict):
        return None
    address = job_location.get("address")
    if not isinstance(address, dict):
        return None
    parts = [
        first_string(address.get("postalCode")),
        first_string(address.get("addressLocality")) or first_string(address.get("addressRegion")),
        first_string(address.get("addressCountry")),
    ]
    return " ".join(part for part in parts if part) or None


def extract_apply_url(schema: dict[str, Any]) -> str | None:
    action = schema.get("potentialAction")
    if not isinstance(action, dict):
        return None
    target = action.get("target")
    if isinstance(target, dict):
        return first_string(target.get("urlTemplate")) or first_string(target.get("url"))
    return first_string(target)


def normalize_jobs_ch_url(value: str | None) -> str | None:
    """Turn jobs.ch's broken terminal /apply route into the vacancy detail URL."""
    if not value:
        return None

    parts = urlsplit(value)
    hostname = (parts.hostname or "").casefold()
    if hostname != "jobs.ch" and not hostname.endswith(".jobs.ch"):
        return value

    normalized_path = re.sub(r"/apply/?$", "/", parts.path, flags=re.IGNORECASE)
    if normalized_path == parts.path:
        return value
    return urlunsplit(parts._replace(path=normalized_path))


def extract_seniority(schema: dict[str, Any]) -> str | None:
    requirement = schema.get("experienceRequirements")
    if isinstance(requirement, dict):
        return first_string(requirement.get("monthsOfExperience"))
    return first_string(requirement)
