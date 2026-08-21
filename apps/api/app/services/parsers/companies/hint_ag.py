from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

HINT_JOBS_URL = "https://hintag.ch/jobs/stellenangebote/"
HINT_PORTAL_URL = "https://jobs.dualoo.com/portal/t1jerlne?lang=DE"
HINT_COMPANY = "HINT AG"
HINT_PORTAL_ID = "t1jerlne"
HINT_SPONTANEOUS_APPLY_URL = (
    "https://jobs.dualoo.com/link/d1d9bb61-5b5e-4ef0-afb6-939a38782679/"
    "apply?lang=DE"
)
HINT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
PORTAL_EMBED_PATTERN = re.compile(
    r"portalUrl\s*:\s*['\"](https://jobs\.dualoo\.com/portal/t1jerlne)"
    r"(?:\?[^'\"]*)?['\"]"
)
DETAIL_PATH_PATTERN = re.compile(
    rf"^/portal/{HINT_PORTAL_ID}/({UUID_PATTERN})/detail/?$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    rf"^/portal/{HINT_PORTAL_ID}/({UUID_PATTERN})/apply/?$",
    re.IGNORECASE,
)
CANONICAL_DETAIL_PATH_PATTERN = re.compile(
    rf"^/portal/([a-z0-9]{{8}})/({UUID_PATTERN})/detail/?$",
    re.IGNORECASE,
)
WORKLOAD_RANGE_PATTERN = re.compile(
    r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%(?!\d)"
)
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%(?!\d)")


class HintAgParseError(DirectCompanyRequestError):
    pass


class HintAgJobsParser:
    """Collect HINT AG's complete official embedded Dualoo catalog."""

    parser_id = "hint_ag"

    def __init__(
        self,
        *,
        base_url: str = HINT_JOBS_URL,
        portal_url: str = HINT_PORTAL_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.portal_url = portal_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**HINT_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                parent_response = client.get(self.base_url)
                parent_response.raise_for_status()
                portal_url = parse_career_page(
                    parent_response.text,
                    page_url=str(parent_response.url),
                    expected_url=self.base_url,
                    expected_portal_url=self.portal_url,
                )
                portal_response = client.get(
                    portal_url,
                    headers={"Referer": self.base_url},
                )
                portal_response.raise_for_status()
                records = parse_portal_html(
                    portal_response.text,
                    page_url=str(portal_response.url),
                    expected_url=self.portal_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except HintAgParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("HINT AG vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("HINT AG vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_hint_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} HINT AG vacancies from the complete "
                "official Dualoo catalog"
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
                    record["url"],
                    headers={"Referer": record["listing_page_url"]},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
            except (httpx.HTTPError, HintAgParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_career_page(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_portal_url: str,
) -> str:
    if not same_url(page_url, expected_url):
        raise HintAgParseError("HINT AG careers page returned unexpected content")
    page = Selector(page_html)
    canonical_urls = unique_attribute_values(
        page,
        'link[rel="canonical"]',
        "href",
    )
    site_names = unique_attribute_values(
        page,
        'meta[property="og:site_name"]',
        "content",
    )
    logo_urls = {
        urljoin(page_url, value)
        for value in page.css('link[rel="preload"][as="image"]::attr(href)').getall()
    }
    if (
        canonical_urls != {canonical_career_url(expected_url)}
        or site_names != {HINT_COMPANY}
        or unique_attribute_values(page, "html", "lang") != {"de-DE"}
        or selector_text(page, "title") != "Stellenangebote - HINT AG"
        or "Unsere Fachkräfte sind unsere Zukunft"
        not in {
            selector_text(heading)
            for heading in page.css("h1.elementor-heading-title")
        }
        or "https://hintag.ch/wp-content/uploads/2022/08/hintag-lenzburg-1.svg"
        not in logo_urls
    ):
        raise HintAgParseError("HINT AG careers page has an invalid identity")

    portal_matches = PORTAL_EMBED_PATTERN.findall(page_html)
    expected_portal = canonical_portal_url(expected_portal_url)
    expected_base = expected_portal.removesuffix("?lang=DE") if expected_portal else None
    spontaneous_urls = {
        canonical_spontaneous_url(urljoin(page_url, raw))
        for raw in page.css('a[href*="jobs.dualoo.com/link/"]::attr(href)').getall()
    }
    if (
        len(portal_matches) != 1
        or portal_matches[0] != expected_base
        or len(page.css("script#dualoo-iframe-1")) != 1
        or spontaneous_urls != {HINT_SPONTANEOUS_APPLY_URL}
    ):
        raise HintAgParseError("HINT AG careers page is missing its official job portal")
    return expected_portal_url


def parse_portal_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise HintAgParseError("HINT AG Dualoo portal returned unexpected content")
    page = Selector(page_html)
    boxes = page.css(".JobInfoBox")
    if (
        unique_attribute_values(page, 'meta[property="og:title"]', "content")
        != {"HINT AG - Offene Stellen"}
        or unique_attribute_values(page, "#jobPortalUrl", "value")
        != {HINT_PORTAL_ID}
        or unique_attribute_values(page, "#lang", "value") != {"DE"}
        or len(boxes) != 1
    ):
        raise HintAgParseError("HINT AG Dualoo portal has an invalid identity")

    cards = boxes[0].css(":scope > a.jobElement")
    if len(cards) > max_jobs:
        raise HintAgParseError(
            f"HINT AG exposes {len(cards)} jobs, above the configured limit of "
            f"{max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, card in enumerate(cards):
        detail_url = canonical_detail_url(
            urljoin(page_url, optional_text(card.attrib.get("href")) or "")
        )
        job_id = extract_detail_id(detail_url)
        title = selector_text(card, ".jobName")
        listing_location = selector_text(card, ".cityName")
        starts_at = selector_text(card, ".jobDate")
        starts_at_code = optional_text(card.css(".jobDate::attr(data-date)").get())
        if (
            not detail_url
            or not job_id
            or not title
            or listing_location != "HINT AG - Lenzburg"
            or starts_at != "ab sofort"
            or starts_at_code != "IMMEDIATELY"
            or job_id in seen_ids
        ):
            raise HintAgParseError(
                "HINT AG catalog contains an invalid or duplicate vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": HINT_COMPANY,
                "location": "Lenzburg, Switzerland",
                "employment_type": normalize_workload(title),
                "starts_at": starts_at,
                "url": detail_url,
                "listing_page_url": canonical_portal_url(page_url),
                "listing_location": listing_location,
                "catalog_index": index,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_detail_url(expected_record.get("url"))
    expected_id = optional_text(expected_record.get("id"))
    expected_title = optional_text(expected_record.get("title"))
    if (
        not expected_url
        or not expected_id
        or not expected_title
        or not same_url(page_url, expected_url)
        or extract_detail_id(page_url) != expected_id
    ):
        raise HintAgParseError("HINT AG detail page returned a different vacancy")

    page = Selector(page_html)
    canonical_values = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    canonical_url = (
        canonical_internal_detail_url(next(iter(canonical_values)))
        if len(canonical_values) == 1
        else None
    )
    schemas = list(extract_job_posting_schemas(page))
    if (
        not canonical_url
        or len(schemas) != 1
        or unique_attribute_values(page, "#jobPortalUrl", "value")
        != {HINT_PORTAL_ID}
        or unique_attribute_values(page, "#lang", "value") != {"DE"}
    ):
        raise HintAgParseError("HINT AG detail page has an invalid identity")

    schema = schemas[0]
    title = optional_text(schema.get("title"))
    company = extract_company(schema)
    locations = extract_swiss_locations(schema.get("jobLocation"))
    description = combine_description(schema)
    visible_title = selector_text(page, "h1.jobName")
    visible_location = selector_text(page, "span.cityName")
    visible_company = selector_text(page, "#contactOneCompany")
    apply_urls = {
        canonical_apply_url(urljoin(page_url, raw), expected_job_id=expected_id)
        for raw in page.css("a.btn-apply::attr(href)").getall()
    }
    if (
        title != expected_title
        or visible_title != expected_title
        or company != HINT_COMPANY
        or visible_company != HINT_COMPANY
        or visible_location != "HINT AG - Lenzburg"
        or locations != ["Lenzburg, Switzerland"]
        or not description
        or schema.get("directApply") is not True
        or None in apply_urls
        or len(apply_urls) != 1
    ):
        raise HintAgParseError("HINT AG detail page contains an incomplete vacancy")

    return {
        "id": expected_id,
        "title": title,
        "company": company,
        "location": locations[0],
        "apply_url": apply_urls.pop(),
        "posted_at": optional_text(schema.get("datePosted")),
        "employment_type": normalize_workload(title)
        or normalize_employment_type(schema.get("employmentType")),
        "description": description,
        "canonical_url": canonical_url,
        "canonical_job_id": extract_internal_detail_id(canonical_url),
        "schema": schema,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="hint_ag",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=HINT_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def canonical_career_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "hintag.ch"
        or parts.path.rstrip("/") != "/jobs/stellenangebote"
        or parts.query
        or parts.fragment
    ):
        return None
    return HINT_JOBS_URL


def canonical_portal_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.dualoo.com"
        or parts.path.rstrip("/") != f"/portal/{HINT_PORTAL_ID}"
        or query != {"lang": ["DE"]}
        or parts.fragment
    ):
        return None
    return HINT_PORTAL_URL


def canonical_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.dualoo.com"
        or not match
        or query != {"lang": ["DE"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.dualoo.com", parts.path.rstrip("/"), "lang=DE", ""))


def canonical_internal_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = CANONICAL_DETAIL_PATH_PATTERN.fullmatch(parts.path)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.dualoo.com"
        or not match
        or query != {"lang": ["DE"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.dualoo.com", parts.path.rstrip("/"), "lang=DE", ""))


def canonical_apply_url(value: Any, *, expected_job_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.dualoo.com"
        or not match
        or match.group(1).casefold() != expected_job_id.casefold()
        or query != {"lang": ["DE"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.dualoo.com", parts.path.rstrip("/"), "lang=DE", ""))


def canonical_spontaneous_url(value: Any) -> str | None:
    return HINT_SPONTANEOUS_APPLY_URL if same_url(value, HINT_SPONTANEOUS_APPLY_URL) else None


def extract_detail_id(value: Any) -> str | None:
    url = canonical_detail_url(value)
    match = DETAIL_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1).casefold() if match else None


def extract_internal_detail_id(value: Any) -> str | None:
    url = canonical_internal_detail_url(value)
    match = CANONICAL_DETAIL_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(2).casefold() if match else None


def extract_company(schema: dict[str, Any]) -> str | None:
    organization = schema.get("hiringOrganization")
    return optional_text(organization.get("name")) if isinstance(organization, dict) else None


def extract_swiss_locations(value: Any) -> list[str]:
    locations = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for location in locations:
        address = location.get("address") if isinstance(location, dict) else None
        if not isinstance(address, dict):
            continue
        country = optional_text(address.get("addressCountry"))
        locality = optional_text(address.get("addressLocality"))
        if (
            not country
            or country.casefold() not in {"ch", "che", "switzerland", "schweiz"}
            or not locality
        ):
            continue
        label = f"{locality}, Switzerland"
        if label not in normalized:
            normalized.append(label)
    return normalized


def extract_job_posting_schemas(page: Selector) -> Iterator[dict[str, Any]]:
    for raw_script in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(str(raw_script))
        except (TypeError, json.JSONDecodeError):
            continue
        for candidate in walk_json(payload):
            if candidate.get("@type") == "JobPosting":
                yield candidate


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def combine_description(schema: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for key in ("description", "responsibilities", "skills", "qualifications", "jobBenefits"):
        text = html_to_text(optional_text(schema.get(key)) or "")
        if text and text not in parts:
            parts.append(text)
    return "\n\n".join(parts) or None


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if match := WORKLOAD_RANGE_PATTERN.search(text):
        lower, upper = (int(item) for item in match.groups())
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    if match := WORKLOAD_PATTERN.search(text):
        workload = int(match.group(1))
        return f"{workload}%" if 1 <= workload <= 100 else None
    return None


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    labels = {"FULL_TIME": "Full-time", "PART_TIME": "Part-time", "INTERN": "Internship"}
    normalized: list[str] = []
    for item in values:
        text = optional_text(item)
        if text:
            label = labels.get(text.upper(), text.replace("_", " ").title())
            if label not in normalized:
                normalized.append(label)
    return ", ".join(normalized) or None


def deduplicate_hint_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_detail_id(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


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
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path.rstrip("/") == target.path.rstrip("/")
        and parse_qs(actual.query, keep_blank_values=True)
        == parse_qs(target.query, keep_blank_values=True)
        and not actual.fragment
    )


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def unique_attribute_values(page: Selector, selector: str, attribute: str) -> set[str]:
    return {
        value
        for raw in page.css(f"{selector}::attr({attribute})").getall()
        if (value := optional_text(raw))
    }


def selector_text(node: Any, selector: str | None = None) -> str | None:
    target = node.css(selector) if selector else node
    return optional_text(" ".join(target.css("::text").getall()))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[\s\u200b]+", " ", value).strip() or None
