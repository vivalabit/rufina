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

SMINO_JOBS_BASE_URL = "https://smino.jobs.personio.com/"
SMINO_COMPANY = "smino AG"
PERSONIO_COMPANY_ID = "89984"
PERSONIO_HOST = "smino.jobs.personio.com"
PERSONIO_JOB_PATH_PATTERN = re.compile(r"^/job/(?P<id>\d+)/?$")
PERSONIO_APPLY_PATH_PATTERN = re.compile(r"^/job/(?P<id>\d+)/apply/?$")
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")
EMPLOYMENT_TYPE_LABELS = {
    "FULL_TIME": "Vollzeit",
    "PART_TIME": "Teilzeit",
    "CONTRACTOR": "Freelance",
    "TEMPORARY": "Befristet",
    "INTERN": "Praktikum",
    "VOLUNTEER": "Ehrenamt",
    "PER_DIEM": "Tageseinsatz",
    "OTHER": "Sonstige",
}
SCHEDULE_CODES = {
    "vollzeit": "FULL_TIME",
    "teilzeit": "PART_TIME",
}
COUNTRY_NAMES = {"CH": "Switzerland", "ES": "Spain"}
EXPECTED_COUNTRIES = {"zurich": "CH", "barcelona": "ES"}
SMINO_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}


class SminoParseError(DirectCompanyRequestError):
    pass


class SminoJobsParser:
    """Collect the complete visible smino Personio vacancy catalog."""

    parser_id = "smino"

    def __init__(
        self,
        *,
        base_url: str = SMINO_JOBS_BASE_URL,
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
                headers={**SMINO_HEADERS, "Referer": self.base_url},
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
        except SminoParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("smino vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("smino vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_smino_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} smino vacancies from the complete visible "
                "official Personio catalog"
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
                    expected_schedule=record["schedule"],
                )
                return record, detail
            except (httpx.HTTPError, SminoParseError, ValueError) as exc:
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
        raise SminoParseError("smino careers page returned an unexpected page")

    page = Selector(page_html)
    canonical_urls = {
        canonical_careers_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    logo_sources = [
        optional_text(image.css("::attr(src)").get()) for image in page.css('img[alt="smino AG"]')
    ]
    if (
        optional_text(page.css("html::attr(lang)").get()) != "en"
        or selector_text(page, "title") != "Jobs bei smino AG"
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != "Jobs bei smino AG"
        or canonical_urls != {expected}
        or len(logo_sources) != 1
        or not valid_personio_logo_url(logo_sources[0])
    ):
        raise SminoParseError("smino careers page has an unexpected identity")

    catalogs = page.css('[aria-label="Offene Positionen"]')
    if len(catalogs) != 1 or unique_selector_texts(page, "h1") != {"Offene Stellen"}:
        raise SminoParseError("smino careers page is missing open positions")

    cards = catalogs[0].css("a.job-box[href]")
    if len(cards) > max_jobs:
        raise SminoParseError(
            f"smino exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        titles = [value for node in card.css("h3") if (value := selector_text(node))]
        metadata = [
            value for node in card.css("div.jb-description span") if (value := selector_text(node))
        ]
        url = canonical_personio_job_url(
            urljoin(page_url, optional_text(card.css("::attr(href)").get()) or "")
        )
        job_id = personio_job_id(url)
        if len(titles) != 1 or len(metadata) != 3 or not url or not job_id:
            raise SminoParseError("smino catalog contains an invalid vacancy card")
        if job_id in seen_ids or url in seen_urls:
            raise SminoParseError("smino catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(url)
        records.append(
            {
                "id": job_id,
                "title": titles[0],
                "company": SMINO_COMPANY,
                "location": metadata[0],
                "schedule": metadata[1],
                "employment": metadata[2],
                "url": url,
                "apply_url": personio_apply_url(job_id),
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
    expected_schedule: str,
) -> dict[str, Any]:
    expected = canonical_personio_job_url(expected_url)
    if (
        not expected
        or canonical_personio_job_url(page_url) != expected
        or personio_job_id(expected) != expected_job_id
    ):
        raise SminoParseError("smino Personio page returned a different vacancy")

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
        raise SminoParseError("smino Personio page is missing JobPosting data")
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
    organization_logo = (
        optional_text(organization.get("logo")) if isinstance(organization, dict) else None
    )
    locality = optional_text(address.get("addressLocality")) if isinstance(address, dict) else None
    country = optional_text(address.get("addressCountry")) if isinstance(address, dict) else None
    posted_at = optional_text(posting.get("datePosted"))
    description = html_to_text(optional_text(posting.get("description")))
    employment_codes = normalize_employment_codes(posting.get("employmentType"))
    employment_type = employment_type_label(employment_codes)
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
        or title_fingerprint(title) != title_fingerprint(expected_title)
        or document_title != f"{title} | Jobs bei smino AG"
        or og_title != document_title
        or identifier_name != SMINO_COMPANY
        or identifier_value != f"{expected_job_id}-{PERSONIO_COMPANY_ID}"
        or organization_name != SMINO_COMPANY
        or not valid_personio_logo_url(organization_logo)
        or not locality
        or not country
        or not location_matches(expected_location, locality=locality, country=country)
        or not schedule_matches(expected_schedule, employment_codes)
        or not valid_date(posted_at)
        or not employment_type
        or not description
        or len(description) < 100
        or apply_urls != {personio_apply_url(expected_job_id)}
    ):
        raise SminoParseError("smino Personio page contains inconsistent vacancy data")

    return {
        "id": expected_job_id,
        "title": title,
        "company": SMINO_COMPANY,
        "location": normalized_location(
            locality=locality,
            country=country,
            remote="remote" in normalize_comparable(expected_location),
        ),
        "location_locality": locality,
        "location_country": country.upper(),
        "posted_at": posted_at,
        "employment_type": employment_type,
        "description": description,
        "apply_url": next(iter(apply_urls)),
        "job_posting": posting,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    workload = extract_workload(record.get("title"))
    employment_parts = [
        optional_text(record.get("employment")),
        optional_text(record.get("schedule")),
        workload,
    ]
    employment_type = " · ".join(dict.fromkeys(part for part in employment_parts if part)) or None
    return ParsedJob(
        source="smino",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=SMINO_COMPANY,
        location=(
            optional_text(detail.get("location"))
            or listing_location(optional_text(record.get("location")))
        ),
        url=optional_text(record.get("url")),
        apply_url=(
            optional_text(detail.get("apply_url")) or optional_text(record.get("apply_url"))
        ),
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=employment_type,
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != PERSONIO_HOST
        or parts.path not in {"", "/"}
        or query not in ({}, {"language": ["de"]})
        or parts.fragment
    ):
        return None
    return SMINO_JOBS_BASE_URL


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
        or parse_qs(parts.query) not in ({}, {"language": ["de"]})
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", PERSONIO_HOST, f"/job/{match.group('id')}", "language=de", ""))


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
        or parse_qs(parts.query) not in ({}, {"language": ["de"]})
        or parts.fragment
    ):
        return None
    return personio_apply_url(expected_job_id)


def personio_apply_url(job_id: str) -> str:
    return f"https://{PERSONIO_HOST}/job/{job_id}/apply?language=de"


def personio_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = PERSONIO_JOB_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group("id") if match else None


def valid_personio_logo_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "assets.cdn.personio.de"
        and PERSONIO_COMPANY_ID in parts.path
        and parts.path.casefold().endswith((".png", ".jpg", ".jpeg", ".webp"))
        and not parts.fragment
    )


def location_matches(expected: Any, *, locality: str, country: str) -> bool:
    expected_text = optional_text(expected)
    if not expected_text:
        return False
    primary = re.sub(r"\s*\([^)]*\)\s*$", "", expected_text)
    primary_value = normalize_comparable(primary)
    locality_value = normalize_comparable(locality)
    country_code = country.upper()
    expected_country = EXPECTED_COUNTRIES.get(primary_value)
    return primary_value == locality_value and (
        expected_country is None or country_code == expected_country
    )


def schedule_matches(expected: Any, codes: list[str]) -> bool:
    expected_code = SCHEDULE_CODES.get(normalize_comparable(expected))
    return bool(expected_code and expected_code in codes)


def normalize_employment_codes(value: Any) -> list[str]:
    values: Sequence[Any]
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, Sequence):
        values = value
    else:
        return []
    codes: list[str] = []
    for item in values:
        code = optional_text(item)
        if not code or code not in EMPLOYMENT_TYPE_LABELS:
            return []
        if code not in codes:
            codes.append(code)
    return codes


def employment_type_label(codes: list[str]) -> str | None:
    labels = [EMPLOYMENT_TYPE_LABELS[code] for code in codes]
    return " / ".join(labels) or None


def normalized_location(*, locality: str, country: str, remote: bool) -> str:
    label = f"{locality}, {COUNTRY_NAMES.get(country.upper(), country.upper())}"
    return f"{label} (Remote)" if remote else label


def listing_location(value: str | None) -> str | None:
    if not value:
        return None
    remote = "remote" in normalize_comparable(value)
    locality = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip()
    country = EXPECTED_COUNTRIES.get(normalize_comparable(locality))
    return (
        normalized_location(locality=locality, country=country, remote=remote) if country else value
    )


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


def deduplicate_smino_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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
