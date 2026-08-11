from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

EBP_SWITZERLAND_JOBS_URL = "https://www.ebp.global/ch-de/karriere/offene-stellen/stellenangebote"
EBP_SWITZERLAND_CATALOG_URL = "https://jobs.ebp.ch/?lang=de&filter_30=64650&filter_10=42976"
EBP_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
SWITZERLAND_FILTER_ID = "64650"
EBP_REGULAR_JOBS_FILTER_ID = "42976"
JOB_PATH_PATTERN = re.compile(
    r"/offene-stellen/[^/]+/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%")
LD_JSON_SCRIPT_PATTERN = re.compile(
    r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
SWISS_COUNTRIES = {"ch", "schweiz", "switzerland", "suisse", "svizzera"}


class EbpSwitzerlandParseError(DirectCompanyRequestError):
    pass


class EbpSwitzerlandJobsParser:
    """Collect the complete regular-vacancy catalog embedded by EBP Switzerland."""

    parser_id = "ebp_switzerland"

    def __init__(
        self,
        *,
        base_url: str = EBP_SWITZERLAND_JOBS_URL,
        catalog_url: str = EBP_SWITZERLAND_CATALOG_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.catalog_url = catalog_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        validate_catalog_url(self.catalog_url)
        try:
            with httpx.Client(
                headers={**EBP_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.catalog_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                )
                self.enrich_records(client, records)
        except EbpSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("EBP Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("EBP Switzerland vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ebp_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} EBP Switzerland vacancies from the "
                "filtered Prospective catalog"
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
                response = client.get(
                    str(record["url"]),
                    headers={"Referer": self.catalog_url},
                )
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_title=optional_text(record.get("title")),
                )
                if extract_job_id(response.url) != record.get("id"):
                    raise EbpSwitzerlandParseError(
                        "EBP Switzerland detail page changed its vacancy ID"
                    )
                return record, detail
            except (
                httpx.HTTPError,
                EbpSwitzerlandParseError,
                ValueError,
            ) as exc:
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
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company="EBP Schweiz AG",
            location=(
                optional_text(detail.get("location")) or optional_text(record.get("location"))
            ),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=join_unique(
                optional_text(record.get("workload")),
                normalize_employment_type(detail.get("employment_type")),
            ),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def validate_catalog_url(catalog_url: str) -> None:
    parsed = urlsplit(catalog_url)
    query = parse_qs(parsed.query)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "jobs.ebp.ch"
        or query.get("lang") != ["de"]
        or query.get("filter_30") != [SWITZERLAND_FILTER_ID]
        or query.get("filter_10") != [EBP_REGULAR_JOBS_FILTER_ID]
    ):
        raise EbpSwitzerlandParseError(
            "EBP Switzerland catalog URL is missing its official filters"
        )


def parse_listing_html(page_html: str, *, page_url: str) -> list[dict[str, Any]]:
    page = Selector(page_html)
    if not page.css("main#content #jobs") or not page.css(".footer-jobabo"):
        raise EbpSwitzerlandParseError(
            "EBP Switzerland listing page is missing its catalog contract"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in page.css("main#content #jobs a.job"):
        detail_path = optional_text(card.attrib.get("href"))
        detail_url = urljoin(page_url, detail_path) if detail_path else None
        job_id = extract_job_id(detail_url)
        title = optional_text(card.attrib.get("title"))
        heading = selector_text(card, "h3.title")
        workload = selector_text(card, ".workload .forCHonly")
        if (
            not job_id
            or job_id in seen_ids
            or not title
            or heading != title
            or not workload
            or not WORKLOAD_PATTERN.fullmatch(workload)
            or not valid_detail_url(detail_url)
        ):
            raise EbpSwitzerlandParseError("EBP Switzerland listing contains an incomplete vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location": "Switzerland",
                "workload": workload,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_title: str | None,
) -> dict[str, Any]:
    page = Selector(page_html)
    schema = next(extract_job_posting_schemas(page), {})
    # Prospective emits JobPosting after </html>, which lxml may discard.
    if not schema:
        schema = next(extract_job_posting_schemas_from_html(page_html), {})

    title = selector_text(page, ".content.container section h1")
    schema_title = optional_text(html.unescape(str(schema.get("title", ""))))
    description_html = optional_text(schema.get("description"))
    apply_path = optional_text(page.css('a[title="Jetzt bewerben"]::attr(href)').get())
    location = extract_swiss_schema_location(schema)
    organization = extract_hiring_organization(schema)
    if (
        not title
        or not schema_title
        or not description_html
        or not apply_path
        or not location
        or organization.casefold() != "ebp schweiz ag"
    ):
        raise EbpSwitzerlandParseError(
            "EBP Switzerland detail page is missing required vacancy data"
        )
    if expected_title and title.casefold() != expected_title.casefold():
        raise EbpSwitzerlandParseError("EBP Switzerland detail page returned a different vacancy")
    if not schema_title.casefold().startswith(title.casefold()):
        raise EbpSwitzerlandParseError(
            "EBP Switzerland JobPosting title does not match the vacancy"
        )

    description = html_to_text(description_html)
    if not description:
        raise EbpSwitzerlandParseError("EBP Switzerland detail page has no vacancy description")
    return {
        "title": title,
        "location": location,
        "apply_url": urljoin(page_url, apply_path),
        "posted_at": optional_text(schema.get("datePosted")),
        "valid_through": optional_text(schema.get("validThrough")),
        "employment_type": schema.get("employmentType"),
        "description": description,
        "hiring_organization": organization,
        "schema": schema,
    }


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        yield from parse_job_posting_payload(raw_script)


def extract_job_posting_schemas_from_html(page_html: str) -> Iterator[dict[str, Any]]:
    for match in LD_JSON_SCRIPT_PATTERN.finditer(page_html):
        yield from parse_job_posting_payload(match.group(1))


def parse_job_posting_payload(raw_json: Any) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(raw_json))
    except (json.JSONDecodeError, TypeError, ValueError):
        return
    for candidate in walk_json(payload):
        job_type = candidate.get("@type")
        if job_type == "JobPosting" or (isinstance(job_type, list) and "JobPosting" in job_type):
            yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from walk_json(nested)


def extract_swiss_schema_location(schema: dict[str, Any]) -> str | None:
    locations = schema.get("jobLocation")
    if isinstance(locations, Sequence) and not isinstance(locations, (str, bytes)):
        candidates = locations
    else:
        candidates = [locations]

    values: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        address = candidate.get("address")
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        if not country or country.casefold() not in SWISS_COUNTRIES:
            continue
        locality = optional_text(address.get("addressLocality"))
        values.append(join_unique(locality, country) or country)
    return "; ".join(dict.fromkeys(values)) or None


def extract_hiring_organization(schema: dict[str, Any]) -> str:
    organization = schema.get("hiringOrganization")
    if not isinstance(organization, dict):
        return ""
    return optional_text(organization.get("name")) or ""


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.search(urlsplit(text).path)
    return match.group(1).lower() if match else None


def valid_detail_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parsed = urlsplit(text)
    return parsed.scheme == "https" and parsed.hostname == "jobs.ebp.ch"


def normalize_employment_type(value: Any) -> str | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        normalized = [normalize_employment_type(item) for item in value]
        return join_unique(*(item for item in normalized if item))
    text = optional_text(value)
    if not text:
        return None
    return {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "TEMPORARY": "Temporary",
        "INTERN": "Internship",
    }.get(text.upper(), text.replace("_", " ").title())


def deduplicate_ebp_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, selector: str) -> str | None:
    return optional_text(" ".join(node.css(f"{selector} ::text").getall())) or optional_text(
        " ".join(node.css(f"{selector}::text").getall())
    )


def join_unique(*values: str | None) -> str | None:
    unique = list(dict.fromkeys(value for value in values if value))
    return ", ".join(unique) if unique else None


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return "\n".join(line for line in lines if line).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(r"\s+", " ", str(value)).strip()
    return normalized or None
