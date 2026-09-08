from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HUERLIMANN_CAREERS_URL = "https://www.hi-ag.ch/unternehmen/karriere"
HUERLIMANN_API_URL = (
    "https://odm.ostendis.com/ojp/data/v55/jobs/"
    "7e4b4ce19bfa48e5838035fcadc5be54/DE?domain=www.hi-ag.ch"
)
HUERLIMANN_HEADERS = {
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
PUBLICATION_TOKEN = "7e4b4ce19bfa48e5838035fcadc5be54"
EXPECTED_COMPANY = "Hürlimann Informatik AG"
EXPECTED_SITE_NAME = "Hürlimann Informatik"
DETAIL_PATH_PATTERN = re.compile(r"^/publication/[a-z0-9]+(?:-[a-z0-9]+)*/([a-z0-9]+)$")
APPLY_PATH_PATTERN = re.compile(r"^/cvdropper/[a-f0-9]+/[A-Z]{2}$", re.IGNORECASE)
EMBED_PATTERN = re.compile(
    rf'OSTENDISJOBS\.embed\(\s*"{PUBLICATION_TOKEN}"\s*,(?:\s*/\*.*?\*/)?\s*'
    r'"DE"\s*,(?:\s*/\*.*?\*/)?\s*"#ostendisJobs"',
    re.MULTILINE,
)


class HuerlimannInformatikParseError(DirectCompanyRequestError):
    pass


class HuerlimannInformatikJobsParser:
    """Collect Hürlimann Informatik's complete official Ostendis catalog."""

    parser_id = "huerlimann_informatik"

    def __init__(
        self,
        *,
        base_url: str = HUERLIMANN_CAREERS_URL,
        api_url: str = HUERLIMANN_API_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**HUERLIMANN_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                careers_response = client.get(self.base_url)
                careers_response.raise_for_status()
                parse_careers_html(
                    careers_response.text,
                    page_url=str(careers_response.url),
                    expected_url=self.base_url,
                    expected_api_url=self.api_url,
                )
                catalog_response = client.get(self.api_url, headers={"Referer": self.base_url})
                catalog_response.raise_for_status()
                records = parse_catalog_payload(catalog_response.json())
                self.enrich_records(client, records)
        except HuerlimannInformatikParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Hürlimann Informatik vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Hürlimann Informatik vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_huerlimann_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Hürlimann Informatik Switzerland vacancies "
                "from the official catalog"
            ),
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
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_title=record["title"],
                    expected_apply_url=record["apply_url"],
                )
            except (httpx.HTTPError, HuerlimannInformatikParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_careers_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_api_url: str,
) -> None:
    if not same_url(page_url, expected_url):
        raise HuerlimannInformatikParseError(
            "Hürlimann Informatik career page returned unexpected content"
        )
    page = Selector(page_html)
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    generators = unique_attribute_values(page, 'meta[name="Generator"]', "content")
    loaders = page.css("#karriere-1266-panel-2 script#ostendisLoader")
    expected_api = urlsplit(expected_api_url)
    api_parts = expected_api.path.rstrip("/").split("/")
    api_token = api_parts[-2] if len(api_parts) >= 2 else None
    spontaneous_links = {
        value
        for raw in page.css("#karriere-1266-panel-3 a::attr(href)").getall()
        if (value := optional_text(raw)) and is_spontaneous_apply_url(value)
    }
    if (
        canonicals != {expected_url}
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {"de"}
        or not any(value.startswith("Drupal 11") for value in generators)
        or len(loaders) != 1
        or optional_text(loaders[0].attrib.get("src"))
        != "https://odm.ostendis.com/ojp/assets/loader"
        or optional_text(loaders[0].attrib.get("data-token")) != PUBLICATION_TOKEN
        or api_token != PUBLICATION_TOKEN
        or parse_qs(expected_api.query) != {"domain": ["www.hi-ag.ch"]}
        or len(page.css("#karriere-1266-panel-2 #ostendisJobs")) != 1
        or len(EMBED_PATTERN.findall(page_html)) != 1
        or len(spontaneous_links) != 1
    ):
        raise HuerlimannInformatikParseError(
            "Hürlimann Informatik career page has an unexpected identity or job portal"
        )


def parse_catalog_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise HuerlimannInformatikParseError("Hürlimann Informatik catalog payload is malformed")
    error = payload.get("error")
    if not isinstance(error, dict):
        raise HuerlimannInformatikParseError("Hürlimann Informatik catalog payload is malformed")
    if error_message := optional_text(error.get("message")):
        if error_message == "Aktuell sind keine offenen Stellen vorhanden." and not payload["jobs"]:
            return []
        raise HuerlimannInformatikParseError(
            f"Hürlimann Informatik catalog returned an error: {error_message}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw_record in payload["jobs"]:
        if not isinstance(raw_record, dict):
            raise HuerlimannInformatikParseError(
                "Hürlimann Informatik catalog contains an invalid vacancy"
            )
        record = dict(raw_record)
        job_id = optional_text(record.get("id"))
        title = optional_text(record.get("title"))
        city = optional_text(record.get("city"))
        detail_url = optional_text(record.get("detail"))
        apply_url = optional_text(record.get("action"))
        detail_token = extract_detail_token(detail_url)
        if (
            not job_id
            or not job_id.isdigit()
            or not title
            or optional_text(record.get("countrycode")) != "CH"
            or not city
            or not detail_token
            or not is_apply_url(apply_url, expected_source_token=detail_token)
        ):
            raise HuerlimannInformatikParseError(
                "Hürlimann Informatik catalog contains an incomplete or non-Swiss vacancy"
            )
        if job_id in seen_ids:
            raise HuerlimannInformatikParseError(
                "Hürlimann Informatik catalog contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        record.update(
            {
                "id": job_id,
                "title": title,
                "city": city,
                "url": detail_url,
                "apply_url": apply_url,
            }
        )
        records.append(record)
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
    expected_apply_url: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url) or not extract_detail_token(page_url):
        raise HuerlimannInformatikParseError(
            "Hürlimann Informatik detail page returned a different vacancy"
        )
    page = Selector(page_html)
    schemas = list(extract_job_posting_schemas(page))
    if len(schemas) != 1:
        raise HuerlimannInformatikParseError(
            "Hürlimann Informatik detail page is missing its JobPosting data"
        )
    schema = schemas[0]
    title = optional_text(schema.get("title"))
    company = extract_company(schema)
    location = extract_swiss_location(schema.get("jobLocation"))
    description_html = optional_text(schema.get("description"))
    description = html_to_text(description_html or "")
    apply_urls = extract_apply_urls(
        description_html or "",
        expected_source_token=extract_detail_token(page_url) or "",
    )
    if (
        title != optional_text(expected_title)
        or company != EXPECTED_COMPANY
        or not location
        or not description
        or apply_urls != {expected_apply_url}
    ):
        raise HuerlimannInformatikParseError(
            "Hürlimann Informatik detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "title": title,
        "company": company,
        "location": location,
        "apply_url": expected_apply_url,
        "posted_at": normalize_iso_date(schema.get("datePosted")),
        "employment_type": normalize_employment_type(schema.get("employmentType")),
        "description": description,
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="huerlimann_informatik",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=normalize_listing_location(record) or optional_text(detail.get("location")),
        url=optional_text(record.get("url")),
        apply_url=(
            optional_text(detail.get("apply_url")) or optional_text(record.get("apply_url"))
        ),
        posted_at=(
            optional_text(detail.get("posted_at"))
            or normalize_listing_date(record.get("published"))
        ),
        employment_type=format_employment_type(
            detail.get("employment_type"), record.get("type"), record.get("workload")
        ),
        seniority=optional_text(record.get("position")),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            schema_type = candidate.get("@type")
            if schema_type == "JobPosting" or (
                isinstance(schema_type, list) and "JobPosting" in schema_type
            ):
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    return optional_text(organization.get("name")) if isinstance(organization, dict) else None


def extract_swiss_location(value: Any) -> str | None:
    locations = value if isinstance(value, list) else [value]
    for location in locations:
        if not isinstance(location, dict) or not isinstance(location.get("address"), dict):
            continue
        address = location["address"]
        country = optional_text(address.get("addressCountry"))
        locality = optional_text(address.get("addressLocality"))
        postal_code = optional_text(address.get("postalCode"))
        if country not in {"CH", "CHE", "Schweiz", "Switzerland"} or not locality:
            continue
        return f"{postal_code + ' ' if postal_code else ''}{locality}, Switzerland"
    return None


def extract_apply_urls(description_html: str, *, expected_source_token: str) -> set[str]:
    fragment = Selector(f"<div>{description_html}</div>")
    return {
        value
        for raw in fragment.css("a::attr(href)").getall()
        if (value := optional_text(raw))
        and is_apply_url(value, expected_source_token=expected_source_token)
    }


def extract_detail_token(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "link.ostendis.com"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def is_apply_url(value: Any, *, expected_source_token: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "link.ostendis.com"
        and APPLY_PATH_PATTERN.fullmatch(parts.path) is not None
        and parse_qs(parts.query) == {"src": [expected_source_token]}
        and not parts.fragment
    )


def is_spontaneous_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "link.ostendis.com"
        and parts.path == "/cvdropper/cece2c7efba84a18a5ed04d1e5bb36a5/DE"
        and len(query.get("src", [])) == 1
        and re.fullmatch(r"[a-z0-9]+", query["src"][0]) is not None
        and set(query) == {"src"}
        and not parts.fragment
    )


def normalize_listing_location(record: dict[str, Any]) -> str | None:
    if optional_text(record.get("countrycode")) != "CH":
        return None
    city = optional_text(record.get("city"))
    postal_code = optional_text(record.get("zip"))
    return f"{postal_code + ' ' if postal_code else ''}{city}, Switzerland" if city else None


def normalize_listing_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d.%m.%Y").replace(tzinfo=UTC).date().isoformat()
    except ValueError:
        return None


def normalize_iso_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
        "OTHER": "Other",
    }
    normalized: list[str] = []
    for item in values:
        text = optional_text(item)
        label = labels.get(text.upper(), text.replace("_", " ").title()) if text else None
        if label and label not in normalized:
            normalized.append(label)
    return ", ".join(normalized) or None


def format_employment_type(*values: Any) -> str | None:
    parts: list[str] = []
    for value in values:
        text = optional_text(value)
        if text and text not in parts:
            parts.append(text)
    return " · ".join(parts) or None


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_huerlimann_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f"{css}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
