from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

MANOR_CAREERS_URL = "https://careers.manor.ch/de/offene-stellen/offene-stellen"
MANOR_FEED_URL = "https://live.solique.ch/manor/de/jobs/"
MANOR_IFRAME_URL = "https://live.solique.ch/manor/de/"
MANOR_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,it-CH;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DETAIL_PATH_PATTERN = re.compile(r"^/manor/job/details/([0-9]+)/$")
LISTING_META_PATTERN = re.compile(r"^(\d{2}\.\d{2}\.\d{4})\s*\|\s*ID:\s*([0-9]+)$")
EMPLOYMENT_TYPES = {
    "FULL_TIME": "Full-time",
    "PART_TIME": "Part-time",
    "TEMPORARY": "Temporary",
    "INTERN": "Internship",
    "APPRENTICESHIP": "Apprenticeship",
}
WINDOWS_1252_CONTROLS = str.maketrans(
    {
        "\x85": "…",
        "\x91": "‘",
        "\x92": "’",
        "\x93": "“",
        "\x94": "”",
        "\x95": "•",
        "\x96": "–",
        "\x97": "—",
    }
)


class ManorParseError(DirectCompanyRequestError):
    pass


class ManorJobsParser:
    """Collect Manor's complete public Solique vacancy catalog."""

    parser_id = "manor"

    def __init__(
        self,
        *,
        base_url: str = MANOR_CAREERS_URL,
        feed_url: str = MANOR_FEED_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.feed_url = feed_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**MANOR_HEADERS, "Referer": self.base_url},
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
                )
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except ManorParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Manor vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Manor vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_manor_jobs(jobs)
        page_label = "page" if pages_fetched == 1 else "pages"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Manor vacancies from {total} catalog records "
                f"across {pages_fetched} Solique {page_label}"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        # Page boundaries can shift while Manor publishes a vacancy. Repeat the
        # walk and union stable Solique detail IDs until the declared total is seen.
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_response = client.get(self.feed_url, params={"page": 1})
            first_response.raise_for_status()
            total, first_records = parse_listing_payload(first_response.json(), page=1)
            pages_fetched += 1
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise ManorParseError("Manor changed its vacancy total during pagination")

            if total == 0:
                return [], pages_fetched, 0
            page_size = len(first_records)
            if page_size < 1:
                raise ManorParseError("Manor catalog is missing its page size")
            required_pages = ceil(total / page_size)
            if required_pages > self.max_pages:
                raise ManorParseError(
                    f"Manor catalog exceeds the configured limit of {self.max_pages} pages"
                )

            page_results = [first_records]
            for page_number in range(2, required_pages + 1):
                response = client.get(self.feed_url, params={"page": page_number})
                response.raise_for_status()
                page_total, page_records = parse_listing_payload(
                    response.json(),
                    page=page_number,
                )
                pages_fetched += 1
                if page_total != expected_total:
                    raise ManorParseError("Manor changed its vacancy total during pagination")
                expected_count = min(page_size, total - ((page_number - 1) * page_size))
                if len(page_records) != expected_count:
                    raise ManorParseError("Manor catalog returned an incomplete page")
                page_results.append(page_records)

            for page_number, page_records in enumerate(page_results, start=1):
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_page"] = page_number
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["id"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise ManorParseError("Manor catalog changed while pages were collected")

        raise ManorParseError(
            f"Manor returned {len(records_by_id)} unique vacancies but declared "
            f"{expected_total or 0}"
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
                    expected_requisition_id=record["requisition_id"],
                )
            except (httpx.HTTPError, ManorParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_careers_html(page_html: str, *, page_url: str, expected_url: str) -> None:
    if not same_url(page_url, expected_url):
        raise ManorParseError("Manor career page returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_values(page, 'link[rel="canonical"]::attr(href)')
    languages = unique_values(page, "html::attr(lang)")
    titles = unique_values(page, "title::text")
    iframes = unique_values(page, "iframe#responsive-iframe::attr(src)")
    if (
        canonicals != {expected_url}
        or languages != {"de"}
        or titles != {"Offene Stellen | Manor Jobs"}
        or iframes != {MANOR_IFRAME_URL}
    ):
        raise ManorParseError("Manor career page has an unexpected identity")


def parse_listing_payload(payload: Any, *, page: int) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(payload, dict):
        raise ManorParseError("Manor catalog response must be an object")
    total = payload.get("jobsCount")
    listing_html = payload.get("html")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise ManorParseError("Manor catalog has an invalid vacancy total")
    if not isinstance(listing_html, str):
        raise ManorParseError("Manor catalog has invalid HTML")
    listing = Selector(listing_html)
    current_pages = {
        optional_int(value)
        for value in listing.css(".job-pagination a.current::attr(data-page)").getall()
    }
    current_pages.discard(None)
    articles = listing.css("section.job-list article")
    if total == 0:
        if articles:
            raise ManorParseError("Manor empty catalog contains unexpected vacancies")
        return 0, []
    if current_pages != {page} or not articles:
        raise ManorParseError("Manor catalog returned an unexpected page")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for article in articles:
        record = parse_listing_article(article)
        if record["id"] in seen_ids:
            raise ManorParseError("Manor catalog page contains duplicate vacancy IDs")
        seen_ids.add(record["id"])
        records.append(record)
    return total, records


def parse_listing_article(article: Any) -> dict[str, Any]:
    metadata = selector_text(article, ".job-row-1")
    title = selector_text(article, ".job-row-2 a")
    detail_links = unique_values(article, ".job-row-2 a::attr(href)")
    summary = selector_text(article, ".job-row-3")
    match = LISTING_META_PATTERN.fullmatch(metadata or "")
    if not match or not title or len(detail_links) != 1 or not summary:
        raise ManorParseError("Manor catalog contains an incomplete vacancy")
    relative_url = next(iter(detail_links))
    detail_url = normalize_detail_url(urljoin(MANOR_IFRAME_URL, relative_url))
    if not detail_url:
        raise ManorParseError("Manor catalog contains an invalid vacancy URL")
    detail_id = DETAIL_PATH_PATTERN.fullmatch(urlsplit(detail_url).path)
    parts = [optional_text(item) for item in summary.split("|")]
    values = [item for item in parts if item]
    if len(values) < 3:
        raise ManorParseError("Manor catalog contains invalid vacancy metadata")
    return {
        "id": detail_id.group(1),
        "requisition_id": match.group(2),
        "title": title,
        "posted_at": normalize_listing_date(match.group(1)),
        "location": values[0],
        "employment_label": values[1],
        "contract_label": values[2],
        "start_label": values[3] if len(values) > 3 else None,
        "url": detail_url,
    }


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_title: str,
    expected_requisition_id: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise ManorParseError("Manor vacancy returned unexpected content")
    page = Selector(page_html)
    canonicals = unique_values(page, 'link[rel="canonical"]::attr(href)')
    postings = [item for item in extract_json_objects(page) if item.get("@type") == "JobPosting"]
    if canonicals != {expected_url} or len(postings) != 1:
        raise ManorParseError("Manor vacancy has an unexpected identity")
    posting = postings[0]
    structured_title = optional_text(posting.get("title"))
    title = html.unescape(structured_title) if structured_title else None
    company = nested_text(posting, "hiringOrganization", "name")
    company_url = nested_text(posting, "hiringOrganization", "sameAs")
    location = nested_text(posting, "jobLocation", "address", "addressLocality")
    country = nested_text(posting, "jobLocation", "address", "addressCountry")
    description = html_to_text(optional_text(posting.get("description")))
    posted_at = normalize_iso_datetime(posting.get("datePosted"))
    employment_type = normalize_employment_type(posting.get("employmentType"))
    apply_urls = {
        normalized
        for raw in page.css('.ad-apply a.button[href*="career_job_req_id"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw, expected_requisition_id))
    }
    if (
        title != expected_title
        or company != "Manor AG"
        or company_url != "https://www.manor.ch/"
        or not location
        or country != "CH"
        or not description
        or not posted_at
        or not employment_type
        or len(apply_urls) != 1
    ):
        raise ManorParseError("Manor vacancy contains incomplete structured data")
    return {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "posted_at": posted_at,
        "employment_type": employment_type,
        "apply_url": next(iter(apply_urls)),
        "structured_data": posting,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="manor",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company="Manor AG",
        location=(optional_text(detail.get("location")) or optional_text(record.get("location"))),
        url=optional_text(record.get("url")),
        apply_url=(optional_text(detail.get("apply_url")) or optional_text(record.get("url"))),
        posted_at=(
            optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at"))
        ),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or normalize_listing_employment(record.get("employment_label"))
        ),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def normalize_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "live.solique.ch"
        or parts.query
        or parts.fragment
        or not DETAIL_PATH_PATTERN.fullmatch(parts.path)
    ):
        return None
    return urlunsplit(("https", "live.solique.ch", parts.path, "", ""))


def normalize_apply_url(value: Any, expected_requisition_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "career55.sapsf.eu"
        or parts.path != "/careers"
        or query.get("career_ns") != ["job_application"]
        or query.get("company") != ["manorag"]
        or query.get("career_job_req_id") != [expected_requisition_id]
    ):
        return None
    canonical_query = urlencode(
        {
            "career_ns": "job_application",
            "company": "manorag",
            "career_job_req_id": expected_requisition_id,
        }
    )
    return urlunsplit(("https", "career55.sapsf.eu", "/careers", canonical_query, ""))


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    normalized = [EMPLOYMENT_TYPES[item] for item in values if item in EMPLOYMENT_TYPES]
    return " / ".join(dict.fromkeys(normalized)) or None


def normalize_listing_employment(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    folded = text.casefold()
    if folded.startswith(("vollzeit", "temps plein", "tempo pieno")):
        return f"Full-time · {text}"
    if folded.startswith(("teilzeit", "temps partiel", "tempo parziale")):
        return f"Part-time · {text}"
    return text


def normalize_listing_date(value: str) -> str:
    try:
        day, month, year = (int(part) for part in value.split("."))
        return date(year, month, day).isoformat()
    except ValueError as exc:
        raise ManorParseError("Manor catalog contains an invalid publication date") from exc


def normalize_iso_datetime(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        datetime.fromisoformat(text)
    except ValueError:
        return None
    return text


def deduplicate_manor_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    output: list[ParsedJob] = []
    seen: set[str] = set()
    for job in jobs:
        key = optional_text(job.raw.get("id")) or optional_text(job.url)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(job)
    return output


def extract_json_objects(page: Selector) -> Iterator[dict[str, Any]]:
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw))
        except (TypeError, json.JSONDecodeError):
            continue
        yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


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


def selector_text(selector: Any, css: str) -> str | None:
    nodes = selector.css(css)
    return optional_text(" ".join(nodes[0].css("::text").getall())) if len(nodes) == 1 else None


def unique_values(selector: Any, css: str) -> set[str]:
    return {value for raw in selector.css(css).getall() if (value := optional_text(raw))}


def nested_text(value: Any, *keys: str) -> str | None:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return optional_text(current)


def optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = (
        str(value)
        .translate(WINDOWS_1252_CONTROLS)
        .replace("\u200b", "")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = re.sub(
        r"[\s\u200b]+",
        " ",
        str(value).translate(WINDOWS_1252_CONTROLS),
    ).strip()
    return normalized or None


def same_url(left: Any, right: Any) -> bool:
    actual = optional_text(left)
    expected = optional_text(right)
    if not actual or not expected:
        return False
    left_parts = urlsplit(actual)
    right_parts = urlsplit(expected)
    return (
        left_parts.scheme == right_parts.scheme == "https"
        and left_parts.netloc.casefold() == right_parts.netloc.casefold()
        and left_parts.path.rstrip("/") == right_parts.path.rstrip("/")
        and left_parts.query == right_parts.query
        and not left_parts.fragment
    )
