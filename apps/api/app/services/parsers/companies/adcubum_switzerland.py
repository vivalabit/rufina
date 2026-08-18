from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ADCUBUM_JOBS_URL = "https://www.adcubum.com/en/job/list"
ADCUBUM_COMPANY = "Adcubum AG"
ADCUBUM_PAGE_TITLE = (
    "Leading software manufacturer for the international insurance industry - Adcubum AG"
)
ADCUBUM_JOB_PORTAL_TENANT_ID = "66503e5e-1add-4934-ac5e-89a651ebd04e"
ADCUBUM_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
OPAQUE_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(
    r"^/en/job/detail/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
FORM_PATH_PATTERN = re.compile(
    r"^/en/job/form/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AdcubumSwitzerlandParseError(DirectCompanyRequestError):
    pass


class AdcubumSwitzerlandJobsParser:
    """Collect the Swiss subset of Adcubum's complete global vacancy catalog."""

    parser_id = "adcubum_switzerland"

    def __init__(
        self,
        *,
        base_url: str = ADCUBUM_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(20, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=ADCUBUM_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records, global_total = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except AdcubumSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Adcubum Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Adcubum Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_adcubum_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Adcubum Switzerland vacancies from the complete "
                f"global catalog of {global_total} jobs"
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
                    expected_record=record,
                )
            except (httpx.HTTPError, AdcubumSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> tuple[list[dict[str, Any]], int]:
    expected = canonical_list_url(expected_url)
    if not expected or canonical_list_url(page_url) != expected:
        raise AdcubumSwitzerlandParseError("Adcubum careers catalog returned an unexpected page")

    page = Selector(page_html)
    language = optional_text(page.css("html::attr(lang)").get())
    title = selector_text(page, "title")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    search_placeholders = set(page.css('input[type="text"]::attr(placeholder)').getall())
    language_switches = {
        canonical_german_list_url(urljoin(page_url, raw))
        for raw in page.css("header a[href]::attr(href)").getall()
    }
    if (
        language != "en"
        or title != ADCUBUM_PAGE_TITLE
        or og_title != ADCUBUM_PAGE_TITLE
        or "Search jobs..." not in search_placeholders
        or "https://www.adcubum.com/de/job/list" not in language_switches
    ):
        raise AdcubumSwitzerlandParseError("Adcubum careers page has an unexpected identity")

    job_lists = extract_next_job_lists(page)
    if len(job_lists) != 1:
        raise AdcubumSwitzerlandParseError(
            "Adcubum careers page is missing its structured vacancy catalog"
        )
    structured_jobs = job_lists[0]
    if len(structured_jobs) > max_jobs:
        raise AdcubumSwitzerlandParseError(
            f"Adcubum exposes {len(structured_jobs)} jobs, above the configured limit of {max_jobs}"
        )

    structured_by_id: dict[str, dict[str, Any]] = {}
    publication_ids: set[str] = set()
    for raw in structured_jobs:
        record = validate_structured_job(raw)
        job_id = record["id"]
        publication_id = record["publication_id"]
        if job_id in structured_by_id or publication_id in publication_ids:
            raise AdcubumSwitzerlandParseError(
                "Adcubum structured catalog contains duplicate vacancies"
            )
        structured_by_id[job_id] = record
        publication_ids.add(publication_id)

    dom_by_id: dict[str, dict[str, str]] = {}
    for link in page.css('main ul[role="list"] li > a[href]'):
        detail_url = canonical_job_url(
            urljoin(page_url, optional_text(link.css("::attr(href)").get()) or "")
        )
        job_id = job_id_from_url(detail_url)
        headings = link.css("h3")
        title_value = selector_text(headings[0]) if len(headings) == 1 else None
        text_values = [
            value
            for raw in link.css("div.flex.items-center span::text").getall()
            if (value := optional_text(raw))
        ]
        city = text_values[0] if len(text_values) == 1 else None
        if not job_id or not detail_url or not title_value or not city or job_id in dom_by_id:
            raise AdcubumSwitzerlandParseError(
                "Adcubum careers page contains an invalid vacancy card"
            )
        dom_by_id[job_id] = {
            "title": title_value,
            "city": city,
            "url": detail_url,
        }

    if set(dom_by_id) != set(structured_by_id):
        raise AdcubumSwitzerlandParseError(
            "Adcubum DOM catalog does not reconcile with its structured vacancies"
        )
    for job_id, dom_record in dom_by_id.items():
        structured = structured_by_id[job_id]
        if comparable_text(dom_record["title"]) != comparable_text(
            structured["title"]
        ) or comparable_text(dom_record["city"]) != comparable_text(structured["city"]):
            raise AdcubumSwitzerlandParseError(
                "Adcubum vacancy card does not match its structured metadata"
            )
        structured["url"] = dom_record["url"]

    swiss_records = [record for record in structured_by_id.values() if record["country"] == "CH"]
    if any(record["company"] != ADCUBUM_COMPANY for record in swiss_records):
        raise AdcubumSwitzerlandParseError(
            "Adcubum Swiss catalog contains an unexpected hiring company"
        )
    for record in swiss_records:
        record["location"] = swiss_location(record["city"])
        record["global_catalog_total"] = len(structured_jobs)
        record["swiss_catalog_total"] = len(swiss_records)
    return swiss_records, len(structured_jobs)


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    if not expected_url or canonical_job_url(page_url) != expected_url:
        raise AdcubumSwitzerlandParseError("Adcubum detail page returned a different vacancy")

    page = Selector(page_html)
    language = optional_text(page.css("html::attr(lang)").get())
    document_title = selector_text(page, "title")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    roots = [node for node in page.css("main > div > div") if node.css(":scope > h1")]
    if len(roots) != 1:
        raise AdcubumSwitzerlandParseError("Adcubum detail page has invalid vacancy content")
    root = roots[0]
    headings = root.css(":scope > h1")
    title = selector_text(headings[0]) if len(headings) == 1 else None
    if (
        language != "en"
        or comparable_text(title) != comparable_text(expected_record.get("title"))
        or comparable_text(document_title) != comparable_text(expected_record.get("title"))
        or comparable_text(og_title) != comparable_text(expected_record.get("title"))
    ):
        raise AdcubumSwitzerlandParseError("Adcubum detail page has invalid vacancy identity")

    metadata_values = {
        value for node in root.css(":scope > div.mb-12 div.flex") if (value := selector_text(node))
    }
    city = optional_text(expected_record.get("city"))
    employment_values = {
        value for value in metadata_values if comparable_text(value) != comparable_text(city)
    }
    if not city or city not in metadata_values or len(employment_values) != 1:
        raise AdcubumSwitzerlandParseError("Adcubum detail page has invalid Swiss location")
    employment_type = employment_values.pop()

    apply_urls = {
        value
        for raw in root.css('a[href^="/en/job/form/"]::attr(href)').getall()
        if (
            value := canonical_apply_url(
                urljoin(page_url, raw),
                expected_id=optional_text(expected_record.get("id")) or "",
            )
        )
    }
    if len(apply_urls) != 1:
        raise AdcubumSwitzerlandParseError(
            "Adcubum detail page is missing its direct application form"
        )

    description_parts: list[str] = []
    for node in root.css(":scope > div"):
        classes = set((optional_text(node.css("::attr(class)").get()) or "").split())
        if "mb-12" in classes or "mt-12" in classes:
            continue
        value = selector_multiline_text(node)
        if value:
            description_parts.append(value)
    description = optional_multiline_text("\n\n".join(description_parts))
    if not description or len(description) < 100:
        raise AdcubumSwitzerlandParseError("Adcubum detail page is missing its vacancy description")

    return {
        "title": title,
        "company": ADCUBUM_COMPANY,
        "location": swiss_location(city),
        "employment_type": employment_type,
        "description": description,
        "url": expected_url,
        "apply_url": apply_urls.pop(),
    }


def validate_structured_job(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdcubumSwitzerlandParseError("Adcubum structured catalog contains an invalid vacancy")
    job_id = optional_text(value.get("id"))
    publication_id = optional_text(value.get("publicationId"))
    title = optional_text(value.get("title"))
    city = optional_text(value.get("city"))
    country = optional_text(value.get("country"))
    category = optional_text(value.get("category"))
    company = optional_text(value.get("companyName"))
    posted_at = optional_text(value.get("publicationStart"))
    publication_url = canonical_publication_url(
        value.get("publicationUrl"),
        expected_publication_id=publication_id or "",
    )
    if (
        not job_id
        or not OPAQUE_ID_PATTERN.fullmatch(job_id)
        or not publication_id
        or not OPAQUE_ID_PATTERN.fullmatch(publication_id)
        or not title
        or not city
        or country not in {"CH", "DE", "HR"}
        or not category
        or not company
        or not posted_at
        or not DATE_PATTERN.fullmatch(posted_at)
        or not publication_url
    ):
        raise AdcubumSwitzerlandParseError(
            "Adcubum structured catalog contains an incomplete vacancy"
        )
    return {
        "id": job_id.casefold(),
        "publication_id": publication_id.casefold(),
        "title": title,
        "city": city,
        "country": country,
        "category": category,
        "company": company,
        "posted_at": posted_at,
        "publication_url": publication_url,
    }


def extract_next_job_lists(page: Selector) -> list[list[Any]]:
    results: list[list[Any]] = []
    prefix = "self.__next_f.push("
    for raw in page.css("script::text").getall():
        script = str(raw)
        if not script.startswith(prefix) or not script.endswith(")"):
            continue
        try:
            flight_call = json.loads(script[len(prefix) : -1])
        except (json.JSONDecodeError, TypeError):
            continue
        if (
            not isinstance(flight_call, list)
            or len(flight_call) != 2
            or flight_call[0] != 1
            or not isinstance(flight_call[1], str)
        ):
            continue
        payload_match = re.fullmatch(r"[0-9a-z]+:(.*)", flight_call[1], re.DOTALL)
        if not payload_match:
            continue
        try:
            payload = json.loads(payload_match.group(1))
        except (json.JSONDecodeError, TypeError):
            continue
        results.extend(find_job_lists(payload))
    return results


def find_job_lists(value: Any) -> list[list[Any]]:
    results: list[list[Any]] = []
    if isinstance(value, dict):
        jobs = value.get("jobs")
        if isinstance(jobs, list):
            results.append(jobs)
        for child in value.values():
            results.extend(find_job_lists(child))
    elif isinstance(value, list):
        for child in value:
            results.extend(find_job_lists(child))
    return results


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="adcubum_switzerland",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=ADCUBUM_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(record.get("posted_at")),
        employment_type=optional_text(detail.get("employment_type")),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def canonical_list_url(value: Any) -> str | None:
    return canonical_site_url(value, path="/en/job/list")


def canonical_german_list_url(value: Any) -> str | None:
    return canonical_site_url(value, path="/de/job/list")


def canonical_site_url(value: Any, *, path: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.adcubum.com"
        or parts.path.rstrip("/") != path
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.adcubum.com", path, "", ""))


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.adcubum.com"
        or not JOB_PATH_PATTERN.fullmatch(path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.adcubum.com", path, "", ""))


def canonical_apply_url(value: Any, *, expected_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    match = FORM_PATH_PATTERN.fullmatch(path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.adcubum.com"
        or not match
        or match.group(1).casefold() != expected_id.casefold()
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.adcubum.com", path, "", ""))


def canonical_publication_url(value: Any, *, expected_publication_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    expected_path = f"/job-advertisement/{ADCUBUM_JOB_PORTAL_TENANT_ID}/{expected_publication_id}"
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "app.jobportal.abaservices.ch"
        or path.casefold() != expected_path.casefold()
        or query != {"jp": ["ABACUS"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "app.jobportal.abaservices.ch", path, "jp=ABACUS", ""))


def job_id_from_url(value: Any) -> str | None:
    canonical = canonical_job_url(value)
    if not canonical:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(canonical).path)
    return match.group(1).casefold() if match else None


def swiss_location(value: Any) -> str | None:
    city = optional_text(value)
    return f"{city}, Switzerland" if city else None


def deduplicate_adcubum_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


def selector_multiline_text(node: Any) -> str | None:
    return optional_multiline_text("\n".join(node.css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    return re.sub(r"\s+", " ", text).strip() or None
