from __future__ import annotations

import html
import json
import re
import unicodedata
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ESURANCE_JOBS_BASE_URL = "https://esurance.ch/work-with-us/?lang=en"
ESURANCE_COMPANY = "esurance AG"
PERSONIO_COMPANY_ID = "130701"
PERSONIO_HOST = "esurance.jobs.personio.com"
PERSONIO_JOB_PATH_PATTERN = re.compile(r"^/job/(?P<id>\d+)/?$")
PERSONIO_APPLY_PATH_PATTERN = re.compile(r"^/job/(?P<id>\d+)/apply/?$")
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")
TRAILING_WORKLOAD_PATTERN = re.compile(r"\s*\(\s*\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%\s*\)\s*$")
EMPLOYMENT_TYPE_LABELS = {
    "FULL_TIME": "Full-time",
    "PART_TIME": "Part-time",
    "CONTRACTOR": "Contract",
    "TEMPORARY": "Temporary",
    "INTERN": "Internship",
    "VOLUNTEER": "Volunteer",
    "PER_DIEM": "Per diem",
    "OTHER": "Other",
}
COUNTRY_LABELS = {
    "CH": {"switzerland", "swiss"},
    "PL": {"poland", "polish"},
}
EXPECTED_PRIMARY_COUNTRIES = {
    "zurich": "CH",
    "poland": "PL",
}
ESURANCE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}


class EsuranceParseError(DirectCompanyRequestError):
    pass


class EsuranceJobsParser:
    """Collect esurance's complete visible catalog and Personio details."""

    parser_id = "esurance"

    def __init__(
        self,
        *,
        base_url: str = ESURANCE_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 6,
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
                headers={**ESURANCE_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except EsuranceParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("esurance vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("esurance vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_esurance_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} esurance vacancies from the complete "
                "visible official careers catalog"
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
                detail = parse_personio_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                    expected_location=record["location"],
                )
                return record, detail
            except (httpx.HTTPError, EsuranceParseError, ValueError) as exc:
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
) -> list[dict[str, Any]]:
    expected = canonical_careers_url(expected_url)
    if not expected or canonical_careers_url(page_url) != expected:
        raise EsuranceParseError("esurance careers page returned an unexpected page")

    page = Selector(page_html)
    canonical_urls = {
        canonical_careers_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    header_logo_alts = {
        value
        for raw in page.css(".masthead a.logo img::attr(alt)").getall()
        if (value := optional_text(raw))
    }
    if (
        optional_text(page.css("html::attr(lang)").get()) != "en-US"
        or selector_text(page, "title") != "esurance | we care for people who care"
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != "Work With Us"
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != "esurance"
        or canonical_urls != {expected}
        or header_logo_alts != {"esurance logo"}
    ):
        raise EsuranceParseError("esurance careers page has an unexpected identity")

    catalogs = page.css("section#open-positions.es-section")
    if len(catalogs) != 1:
        raise EsuranceParseError("esurance careers page is missing open positions")
    catalog = catalogs[0]
    if (
        unique_selector_texts(catalog, ":scope > .container > .section-title > h2")
        != {"Open positions"}
        or len(
            [
                raw
                for raw in catalog.css(
                    ":scope > .container a.sec-es-jobs--button::attr(href)"
                ).getall()
                if valid_personio_catalog_url(raw)
            ]
        )
        != 1
    ):
        raise EsuranceParseError("esurance careers page has an invalid vacancy catalog")

    cards = catalog.css(":scope > .container > .es-bars > .es-bar--job")
    if len(cards) > max_jobs:
        raise EsuranceParseError(
            f"esurance exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        items = card.css(":scope > .es-bar-item")
        if len(items) != 4:
            raise EsuranceParseError("esurance catalog contains an incomplete vacancy card")
        title = selector_text(items[0])
        department = selector_text(items[1])
        location = selector_text(items[2])
        links = items[3].css("a.es-cta[href]")
        url = (
            canonical_personio_job_url(
                urljoin(page_url, optional_text(links[0].css("::attr(href)").get()) or "")
            )
            if len(links) == 1
            else None
        )
        job_id = personio_job_id(url)
        if (
            not title
            or not department
            or not location
            or not url
            or not job_id
            or selector_text(links[0]) != "See Job Description"
        ):
            raise EsuranceParseError("esurance catalog contains an invalid vacancy card")
        if job_id in seen_ids or url in seen_urls:
            raise EsuranceParseError("esurance catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": ESURANCE_COMPANY,
                "department": department,
                "location": location,
                "url": url,
                "catalog_index": index,
            }
        )
    return records


def parse_personio_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
    expected_location: str,
) -> dict[str, Any]:
    expected = canonical_personio_job_url(expected_url)
    if (
        not expected
        or canonical_personio_job_url(page_url) != expected
        or personio_job_id(expected) != expected_job_id
    ):
        raise EsuranceParseError("esurance Personio page returned a different vacancy")

    page = Selector(page_html)
    canonical_urls = {
        canonical_personio_job_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    postings: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
            postings.append(payload)
    if len(postings) != 1:
        raise EsuranceParseError("esurance Personio page is missing JobPosting data")
    posting = postings[0]

    title = optional_text(posting.get("title"))
    identifier = posting.get("identifier")
    organization = posting.get("hiringOrganization")
    address = nested_dict(posting, "jobLocation", "address")
    identifier_name = (
        optional_text(identifier.get("name")) if isinstance(identifier, dict) else None
    )
    identifier_value = (
        optional_text(identifier.get("value")) if isinstance(identifier, dict) else None
    )
    organization_name = (
        optional_text(organization.get("name")) if isinstance(organization, dict) else None
    )
    locality = optional_text(address.get("addressLocality")) if isinstance(address, dict) else None
    country = optional_text(address.get("addressCountry")) if isinstance(address, dict) else None
    posted_at = optional_text(posting.get("datePosted"))
    description = html_to_text(optional_text(posting.get("description")))
    employment_type = normalize_employment_type(posting.get("employmentType"))
    apply_urls = {
        value
        for raw in page.css('a[href*="/apply"]::attr(href)').getall()
        if (
            value := canonical_personio_apply_url(
                urljoin(page_url, optional_text(raw) or ""),
                expected_job_id=expected_job_id,
            )
        )
    }
    document_title = selector_text(page, "title")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    if (
        optional_text(page.css("html::attr(lang)").get()) != "en"
        or canonical_urls != {expected}
        or not title
        or title_fingerprint(title) != title_fingerprint(strip_workload(expected_title))
        or document_title != f"{title} | Jobs at esurance AG"
        or og_title != document_title
        or identifier_name != ESURANCE_COMPANY
        or identifier_value != f"{expected_job_id}-{PERSONIO_COMPANY_ID}"
        or organization_name != ESURANCE_COMPANY
        or not locality
        or not country
        or not location_matches(expected_location, locality=locality, country=country)
        or not valid_date(posted_at)
        or not employment_type
        or not description
        or len(description) < 100
        or len(apply_urls) != 1
    ):
        raise EsuranceParseError("esurance Personio page contains inconsistent vacancy data")

    return {
        "id": expected_job_id,
        "title": title,
        "company": ESURANCE_COMPANY,
        "location_locality": locality,
        "location_country": country,
        "posted_at": posted_at,
        "employment_type": employment_type,
        "description": description,
        "apply_url": next(iter(apply_urls)),
        "job_posting": posting,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    workload = extract_workload(record.get("title"))
    employment_type = optional_text(detail.get("employment_type"))
    if employment_type and workload:
        employment_type = f"{employment_type} ({workload})"
    return ParsedJob(
        source="esurance",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=ESURANCE_COMPANY,
        location=optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=employment_type or workload,
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() not in {"esurance.ch", "www.esurance.ch"}
        or parts.path.rstrip("/") != "/work-with-us"
        or parse_qs(parts.query) != {"lang": ["en"]}
        or parts.fragment
    ):
        return None
    return ESURANCE_JOBS_BASE_URL


def canonical_personio_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PERSONIO_JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != PERSONIO_HOST
        or not match
        or parse_qs(parts.query) != {"language": ["en"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", PERSONIO_HOST, f"/job/{match.group('id')}", "language=en", ""))


def canonical_personio_apply_url(value: Any, *, expected_job_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PERSONIO_APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != PERSONIO_HOST
        or not match
        or match.group("id") != expected_job_id
        or parse_qs(parts.query) != {"language": ["en"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", PERSONIO_HOST, f"/job/{expected_job_id}/apply", "language=en", ""))


def valid_personio_catalog_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == PERSONIO_HOST
        and parts.path in {"", "/"}
        and parse_qs(parts.query) == {"language": ["en"]}
        and not parts.fragment
    )


def personio_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = PERSONIO_JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group("id") if match else None


def location_matches(expected: Any, *, locality: str, country: str) -> bool:
    expected_text = optional_text(expected)
    if not expected_text:
        return False
    primary = normalize_comparable(expected_text.split(",", maxsplit=1)[0])
    locality_value = normalize_comparable(locality)
    country_code = country.upper()
    if (
        expected_country := EXPECTED_PRIMARY_COUNTRIES.get(primary)
    ) and country_code != expected_country:
        return False
    return primary == locality_value or primary in COUNTRY_LABELS.get(country_code, set())


def normalize_employment_type(value: Any) -> str | None:
    values: Sequence[Any]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence):
        values = value
    else:
        return None
    labels: list[str] = []
    for item in values:
        code = optional_text(item)
        label = EMPLOYMENT_TYPE_LABELS.get(code or "")
        if not label:
            return None
        if label not in labels:
            labels.append(label)
    return " / ".join(labels) or None


def strip_workload(value: Any) -> str | None:
    text = optional_text(value)
    return optional_text(TRAILING_WORKLOAD_PATTERN.sub("", text)) if text else None


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := WORKLOAD_PATTERN.search(text)):
        return None
    return optional_text(re.sub(r"\s*[–-]\s*", "–", match.group(0)))


def title_fingerprint(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalize_comparable(value))


def normalize_comparable(value: Any) -> str:
    text = optional_text(value) or ""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    ).casefold()


def valid_date(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return True


def deduplicate_esurance_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = personio_job_id(job.url) or job.url or ""
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


def unique_selector_texts(node: Any, query: str) -> set[str]:
    return {value for item in node.css(query) if (value := selector_text(item))}


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    values = [optional_text(item.get_all_text()) for item in selected]
    return optional_text(" ".join(value for value in values if value))


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
