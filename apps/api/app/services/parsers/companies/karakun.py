from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

KARAKUN_CAREERS_URL = "https://karakun.com/en/jobs/"
KARAKUN_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "Karakun AG"
EXPECTED_LOCATION = "Basel, Switzerland"
EXPECTED_LANGUAGE = "en-GB"
EXPECTED_CATALOG_HEADING = "Open Positions at Karakun"
EXPECTED_APPLY_EMAIL = "hr@karakun.com"
JOB_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LEGACY_JOB_PATHS = {"/fsse-en", "/fsse-en/"}


class KarakunParseError(DirectCompanyRequestError):
    pass


class KarakunJobsParser:
    """Collect Karakun's complete visible WordPress vacancy catalog."""

    parser_id = "karakun"

    def __init__(
        self,
        *,
        base_url: str = KARAKUN_CAREERS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**KARAKUN_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_catalog_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except KarakunParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Karakun vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Karakun vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_karakun_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Karakun vacancies from the complete official catalog"),
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
                    record["listing_url"],
                    headers={"Referer": record["listing_page_url"]},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, KarakunParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_catalog_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise KarakunParseError("Karakun catalog returned unexpected content")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    headings = {selector_text(node) for node in page.css("#page-content h2")}
    if EXPECTED_CATALOG_HEADING not in headings:
        raise KarakunParseError("Karakun careers page is missing its vacancy catalog")

    links: list[tuple[Any, str, str]] = []
    for link in page.css("#page-content a.k-overlay-link"):
        listing_url = canonical_listing_job_url(
            urljoin(page_url, optional_text(link.attrib.get("href")) or "")
        )
        job_id = extract_job_id(listing_url)
        if listing_url and job_id:
            links.append((link, listing_url, job_id))

    if len(links) > max_jobs:
        raise KarakunParseError(
            f"Karakun exposes {len(links)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for link, listing_url, job_id in links:
        title = optional_text(link.attrib.get("title"))
        visible_title = selector_text(link, ".k-title")
        if not title or visible_title != title:
            raise KarakunParseError("Karakun catalog contains an incomplete vacancy card")
        if job_id in seen_ids or listing_url in seen_urls:
            raise KarakunParseError("Karakun catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(listing_url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "location": EXPECTED_LOCATION,
                "url": listing_url,
                "listing_url": listing_url,
                "listing_page_url": canonical_url(page_url),
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    public_url = canonical_detail_job_url(page_url)
    if not public_url or extract_job_id(public_url) != expected_job_id:
        raise KarakunParseError("Karakun detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=public_url)
    content_nodes = page.css("#page-content")
    titles = page.css("#page-content h1")
    schemas = list(extract_web_page_schemas(page))
    organizations = list(extract_organization_schemas(page))
    if len(content_nodes) != 1 or len(titles) != 1 or len(schemas) != 1:
        raise KarakunParseError("Karakun detail page has an invalid identity")

    title = selector_text(titles[0])
    schema = schemas[0]
    schema_url = canonical_detail_job_url(schema.get("url"))
    schema_published = optional_text(schema.get("datePublished"))
    schema_modified = optional_text(schema.get("dateModified"))
    companies = {
        optional_text(item.get("name")) for item in organizations if is_karakun_url(item.get("url"))
    }
    apply_urls = {
        normalized
        for raw in page.css('#page-content a[aria-label="Apply for this job"]::attr(href)').getall()
        if (normalized := normalize_apply_url(raw))
    }
    description = html_to_text(content_nodes.get() or "")
    if (
        not title
        or not titles_compatible(title, expected_title)
        or schema_url != public_url
        or not schema_published
        or not schema_modified
        or companies != {EXPECTED_COMPANY}
        or len(apply_urls) != 1
        or not description
        or len(description) < 200
    ):
        raise KarakunParseError("Karakun detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": EXPECTED_LOCATION,
        "url": public_url,
        "apply_url": apply_urls.pop(),
        "posted_at": schema_published,
        "updated_at": schema_modified,
        "description": description,
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(detail.get("url")) or optional_text(record.get("url"))
    title = optional_text(detail.get("title")) or optional_text(record.get("title"))
    return ParsedJob(
        source="karakun",
        title=title,
        company=EXPECTED_COMPANY,
        location=EXPECTED_LOCATION,
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=None,
        seniority="Senior" if comparable_text(title).startswith("senior ") else None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or site_names != {EXPECTED_COMPANY}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise KarakunParseError("Karakun page has an invalid identity")


def extract_web_page_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    yield from extract_schemas(page, schema_type="WebPage")


def extract_organization_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    yield from extract_schemas(page, schema_type="Organization")


def extract_schemas(page: Selector, *, schema_type: str) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") == schema_type:
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def canonical_listing_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() not in {"karakun.com", "www.karakun.com"}
        or parts.query
        or parts.fragment
    ):
        return None
    if path not in LEGACY_JOB_PATHS and not re.fullmatch(r"/(?:en/)?jobs/[^/]+/?", path):
        return None
    if not extract_job_id_from_path(path):
        return None
    return urlunsplit(("https", "karakun.com", parts.path.rstrip("/") or "/", "", ""))


def canonical_detail_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() not in {"karakun.com", "www.karakun.com"}
        or not re.fullmatch(r"/en/jobs/[^/]+/?", path)
        or parts.query
        or parts.fragment
        or not extract_job_id_from_path(path)
    ):
        return None
    return urlunsplit(("https", "karakun.com", parts.path.rstrip("/") + "/", "", ""))


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    return extract_job_id_from_path(unquote(urlsplit(text).path)) if text else None


def extract_job_id_from_path(path: str) -> str | None:
    slug = path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"[()]", "", slug.casefold())
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug if JOB_SLUG_PATTERN.fullmatch(slug) else None


def normalize_apply_url(value: Any) -> str | None:
    text = html.unescape(optional_text(value) or "")
    parts = urlsplit(text)
    if parts.scheme.casefold() != "mailto" or parts.path.casefold() != EXPECTED_APPLY_EMAIL:
        return None
    query = parse_qs(parts.query, keep_blank_values=False)
    if set(query) - {"subject"} or len(query.get("subject", [])) > 1 or parts.fragment:
        return None
    subject = optional_text(query.get("subject", [None])[0])
    return (
        f"mailto:{EXPECTED_APPLY_EMAIL}?{urlencode({'subject': subject})}"
        if subject
        else (f"mailto:{EXPECTED_APPLY_EMAIL}")
    )


def titles_compatible(value: Any, expected: Any) -> bool:
    actual_tokens = title_tokens(value)
    expected_tokens = title_tokens(expected)
    return bool(actual_tokens and expected_tokens) and (
        actual_tokens == expected_tokens
        or (
            len(actual_tokens & expected_tokens)
            >= min(len(actual_tokens), len(expected_tokens)) - 1
            and len(actual_tokens ^ expected_tokens) <= 2
        )
    )


def title_tokens(value: Any) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", comparable_text(value)))


def is_karakun_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return parts.scheme == "https" and parts.netloc.casefold() in {
        "karakun.com",
        "www.karakun.com",
    }


def canonical_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def same_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == "https"
        and actual.scheme == target.scheme
        and actual.netloc.casefold().removeprefix("www.")
        == target.netloc.casefold().removeprefix("www.")
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and parse_qs(actual.query, keep_blank_values=True)
        == parse_qs(target.query, keep_blank_values=True)
        and not actual.fragment
    )


def deduplicate_karakun_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any, css: str | None = None) -> str | None:
    target = selector.css(css) if css else selector
    return optional_text(" ".join(target.css("::text").getall()))


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    decoded = html.unescape(value)
    decoded = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1>", "", decoded)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", decoded)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = html.unescape(text).replace("\xa0", " ")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    return re.sub(r"\n{3,}", "\n\n", normalized).strip() or None


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None
