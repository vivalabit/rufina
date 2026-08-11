from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

TI8M_JOBS_URL = "https://www.ti8m.com/en/career#job"
TI8M_CATALOG_URL = "https://career.ti8m.com/?lang=en"
TI8M_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
JOB_PATH_PATTERN = re.compile(
    rf"^/offene-stellen/[a-z0-9][a-z0-9-]*/({UUID_PATTERN})/?$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    rf"^/public/v1/redirect/({UUID_PATTERN})/ats/?$",
    re.IGNORECASE,
)
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SWISS_LOCATIONS = {
    "zurich": "Zürich, Switzerland",
    "bern": "Bern, Switzerland",
    "basel": "Basel, Switzerland",
}
FOREIGN_LOCATIONS = {"frankfurt", "düsseldorf", "dusseldorf", "singapore"}
SWISS_COUNTRIES = {"ch", "schweiz", "switzerland", "suisse", "svizzera"}


class Ti8mSwitzerlandParseError(DirectCompanyRequestError):
    pass


class Ti8mSwitzerlandJobsParser:
    """Collect ti&m vacancies in Switzerland from its complete Prospective catalog."""

    parser_id = "ti8m_switzerland"

    def __init__(
        self,
        *,
        base_url: str = TI8M_JOBS_URL,
        catalog_url: str = TI8M_CATALOG_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**TI8M_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.catalog_url)
                response.raise_for_status()
                records, total = parse_listing_html(
                    response.text, page_url=str(response.url), max_jobs=self.max_jobs
                )
                self.enrich_records(client, records)
        except Ti8mSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("ti&m vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("ti&m vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ti8m_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} ti&m Switzerland vacancies from {total} global vacancies",
        )

    def enrich_records(self, client: httpx.Client, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(str(record["url"]), headers={"Referer": self.catalog_url})
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_id=str(record["id"]),
                    expected_title=str(record["title"]),
                )
                return record, detail
            except (httpx.HTTPError, Ti8mSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="ti&m AG",
            location=optional_text(detail.get("location")) or optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=join_unique(
                optional_text(detail.get("contract_type")),
                normalize_employment_type(detail.get("employment_type")),
            ),
            seniority=optional_text(detail.get("seniority")) or extract_seniority(title),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(page_html: str, *, page_url: str, max_jobs: int) -> tuple[list[dict[str, Any]], int]:
    page = Selector(page_html)
    form = page.css("form#careercenter-form")
    limit = optional_text(page.css('form#careercenter-form input[name="limit"]::attr(value)').get())
    offset = optional_text(page.css('form#careercenter-form input[name="offset"]::attr(value)').get())
    language = optional_text(page.css('form#careercenter-form input[name="lang"]::attr(value)').get())
    cards = page.css("#jobs .job")
    if not form.get() or limit != "200" or offset != "0" or language != "en" or not cards:
        raise Ti8mSwitzerlandParseError("ti&m listing is missing its complete catalog contract")
    if len(cards) >= 200:
        raise Ti8mSwitzerlandParseError("ti&m catalog reached its embedded page limit")
    if len(cards) > max_jobs:
        raise Ti8mSwitzerlandParseError(
            f"ti&m exposes {len(cards)} vacancies, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        href = optional_text(card.css(".title a::attr(href)").get())
        detail_url = urljoin(page_url, href) if href else None
        job_id = extract_job_id(detail_url)
        title = optional_text(card.css(".title a::attr(title)").get()) or selector_text(card, ".title a")
        location_label = selector_text(card, ".location")
        field = selector_text(card, ".branch")
        location_key = comparable_text(location_label)
        is_foreign = location_key in FOREIGN_LOCATIONS
        location = SWISS_LOCATIONS.get(location_key)
        if not detail_url or not job_id or not title or not location_label or not field or (not location and not is_foreign):
            raise Ti8mSwitzerlandParseError("ti&m listing contains an incomplete vacancy or unknown location")
        if job_id in seen_ids:
            raise Ti8mSwitzerlandParseError("ti&m listing contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        if is_foreign:
            continue
        records.append({
            "id": job_id,
            "title": title,
            "location": location,
            "location_label": location_label,
            "professional_field": field,
            "url": detail_url,
            "listing_page_url": page_url,
            "total_available": len(cards),
        })
    return records, len(cards)


def parse_detail_html(page_html: str, *, page_url: str, expected_id: str, expected_title: str) -> dict[str, Any]:
    if extract_job_id(page_url) != expected_id:
        raise Ti8mSwitzerlandParseError("ti&m detail page returned a different vacancy")
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page_html), {})
    title = optional_text(schema.get("title"))
    organization = schema.get("hiringOrganization")
    company = optional_text(organization.get("name")) if isinstance(organization, dict) else None
    description_html = optional_text(schema.get("description"))
    apply_url = optional_text(page.css("a.apply-button::attr(href)").get())
    if (
        not title
        or comparable_text(title) != comparable_text(expected_title)
        or company != "ti&m AG"
        or not description_html
        or extract_apply_id(apply_url) != expected_id
    ):
        raise Ti8mSwitzerlandParseError("ti&m detail page is missing required vacancy data")
    location = extract_schema_location(schema)
    if not location:
        raise Ti8mSwitzerlandParseError("ti&m detail page does not describe a Swiss location")
    metadata = extract_detail_metadata(page)
    return {
        "title": title,
        "location": location,
        "apply_url": apply_url,
        "posted_at": optional_text(schema.get("datePosted")),
        "employment_type": schema.get("employmentType"),
        "seniority": metadata.get("Seniorität"),
        "experience": metadata.get("Erfahrung"),
        "contract_type": metadata.get("Beschäftigungsgrad"),
        "description": html_to_text(description_html),
        "schema": schema,
    }


def extract_job_posting_schemas(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        try:
            payload = json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        yield from (item for item in walk_json(payload) if item.get("@type") == "JobPosting")


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_schema_location(schema: dict[str, Any]) -> str | None:
    location = schema.get("jobLocation")
    if isinstance(location, Sequence) and not isinstance(location, (str, bytes)):
        location = next((item for item in location if isinstance(item, dict)), None)
    if not isinstance(location, dict) or not isinstance(location.get("address"), dict):
        return None
    address = location["address"]
    country = comparable_text(address.get("addressCountry"))
    city = optional_text(address.get("addressLocality"))
    if country not in SWISS_COUNTRIES or not city:
        return None
    return f"{city}, Switzerland"


def extract_detail_metadata(page: Selector) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for item in page.css("article.job .meta > div"):
        label = selector_text(item, "label")
        value = selector_text(item, "span")
        if label and value:
            metadata[label] = value
    return metadata


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text or urlsplit(text).hostname != "career.ti8m.com":
        return None
    match = JOB_PATH_PATTERN.match(urlsplit(text).path)
    return match.group(1).lower() if match else None


def extract_apply_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text or urlsplit(text).hostname != "ohws.prospective.ch":
        return None
    match = APPLY_PATH_PATTERN.match(urlsplit(text).path)
    return match.group(1).lower() if match else None


def deduplicate_ti8m_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = extract_job_id(job.url)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else [value]
    mapping = {"FULL_TIME": "Full-time", "PART_TIME": "Part-time", "CONTRACTOR": "Contract"}
    normalized = [mapping.get(text, text.replace("_", " ").title()) for item in values if (text := optional_text(item))]
    return ", ".join(dict.fromkeys(normalized)) or None


def join_unique(*values: str | None) -> str | None:
    normalized = [value for value in values if value]
    return ", ".join(dict.fromkeys(normalized)) or None


def extract_seniority(title: Any) -> str | None:
    text = comparable_text(title)
    if re.search(r"\b(head|lead|principal)\b", text):
        return "Lead"
    if re.search(r"\bsenior\b", text):
        return "Senior"
    if re.search(r"\bjunior\b", text):
        return "Junior"
    return None


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|ul|ol)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+|[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def selector_text(node: Any, selector: str) -> str | None:
    selected = node.css(selector).get()
    return optional_text(html_to_text(selected)) if selected else None


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    return re.sub(r"\n{3,}", "\n\n", text).strip() if text else None


def comparable_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip().casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = html.unescape(str(value)).strip()
    return normalized or None
