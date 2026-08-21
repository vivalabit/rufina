from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

DATAHOUSE_ZURICH_JOBS_BASE_URL = "https://www.datahouse.ch/en/career/"
DATAHOUSE_ZURICH_JOBS_DETAIL_API_URL = (
    "https://api.smartrecruiters.com/v1/companies/wuestpartner/postings"
)
DATAHOUSE_COMPANY = "Datahouse AG"
SMARTRECRUITERS_COMPANY_IDENTIFIER = "wuestpartner"
ZURICH_SECTION_TITLE = "Zurich, Switzerland"
JOB_PATH_PATTERN = re.compile(
    r"^/wuestpartner/(?P<id>\d+)-(?P<slug>[a-z0-9-]+)$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")
DATAHOUSE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}


class DatahouseZurichParseError(DirectCompanyRequestError):
    pass


class DatahouseZurichJobsParser:
    """Collect Datahouse vacancies from the Zurich section of its careers page."""

    parser_id = "datahouse_zurich"

    def __init__(
        self,
        *,
        base_url: str = DATAHOUSE_ZURICH_JOBS_BASE_URL,
        detail_api_url: str = DATAHOUSE_ZURICH_JOBS_DETAIL_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.detail_api_url = detail_api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=DATAHOUSE_HEADERS,
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
                    detail_api_url=self.detail_api_url,
                    max_jobs=self.max_jobs,
                )
                visible_count = len(records)
                expired_count = self.enrich_records(client, records)
        except DatahouseZurichParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Datahouse Zurich vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Datahouse Zurich vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_datahouse_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} active Datahouse Zurich vacancies from "
                f"{visible_count} visible careers-page records"
                + (f" ({expired_count} expired)" if expired_count else "")
            ),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> int:
        if not records:
            return 0

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(record["detail_ref"], headers={"Referer": self.base_url})
                response.raise_for_status()
                detail = parse_detail_payload(
                    response.json(),
                    expected_title=record["title"],
                )
                return record, detail
            except (httpx.HTTPError, DatahouseZurichParseError, TypeError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

        expired_count = sum(
            1
            for record in records
            if isinstance(record.get("detail"), dict) and record["detail"].get("active") is False
        )
        records[:] = [
            record
            for record in records
            if not (
                isinstance(record.get("detail"), dict) and record["detail"].get("active") is False
            )
        ]
        return expired_count


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    detail_api_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    expected = canonical_careers_url(expected_url)
    if not expected or canonical_careers_url(page_url) != expected:
        raise DatahouseZurichParseError("Datahouse careers page returned an unexpected page")

    page = Selector(page_html)
    canonical_urls = {
        canonical_careers_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    if (
        optional_text(page.css("html::attr(lang)").get()) != "en-US"
        or selector_text(page, "title") != "Career - Datahouse"
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != "Career - Datahouse"
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != "Datahouse"
        or canonical_urls != {expected}
    ):
        raise DatahouseZurichParseError("Datahouse careers page has an unexpected identity")

    catalogs = page.css("#open-positions")
    if len(catalogs) != 1:
        raise DatahouseZurichParseError("Datahouse careers page is missing open positions")
    catalog = catalogs[0]
    markers = {
        selector_text(node)
        for node in catalog.css(":scope > .wp-block-columns p strong")
        if selector_text(node)
    }
    if "Open positions" not in markers:
        raise DatahouseZurichParseError("Datahouse careers page is missing open positions")

    headings = [
        node
        for node in catalog.css(":scope > h3.wp-block-heading")
        if selector_text(node) == ZURICH_SECTION_TITLE
    ]
    if len(headings) > 1:
        raise DatahouseZurichParseError("Datahouse careers page has duplicate Zurich sections")
    if not headings:
        return []

    sections = headings[0].xpath(
        "following-sibling::*[1][self::div[contains(concat(' ', "
        "normalize-space(@class), ' '), ' wp-block-columns ')]]"
    )
    if len(sections) != 1:
        raise DatahouseZurichParseError("Datahouse Zurich vacancy section is malformed")
    cards = sections[0].css(".dhsv-teaserbox")
    if len(cards) > max_jobs:
        raise DatahouseZurichParseError(
            f"Datahouse exposes {len(cards)} Zurich jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        links = card.css("a.link[href]")
        titles = card.css(".content h3.wp-block-heading")
        descriptions = [value for node in card.css(".content p") if (value := selector_text(node))]
        image_alts = {
            value
            for raw in card.css(".image img::attr(alt)").getall()
            if (value := optional_text(raw))
        }
        if len(links) != 1 or len(titles) != 1:
            raise DatahouseZurichParseError(
                "Datahouse Zurich catalog contains an incomplete vacancy card"
            )

        title = selector_text(titles[0])
        description = optional_multiline_text("\n\n".join(descriptions))
        url = canonical_job_url(
            urljoin(page_url, optional_text(links[0].css("::attr(href)").get()) or "")
        )
        job_id = job_id_from_url(url)
        if (
            not title
            or not description
            or len(description) < 40
            or image_alts != {"Datahouse"}
            or not url
            or not job_id
        ):
            raise DatahouseZurichParseError(
                "Datahouse Zurich catalog contains an invalid vacancy card"
            )
        if job_id in seen_ids or url in seen_urls:
            raise DatahouseZurichParseError("Datahouse Zurich catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": DATAHOUSE_COMPANY,
                "location": "Zürich, Switzerland",
                "listing_description": description,
                "url": url,
                "detail_ref": f"{detail_api_url.rstrip('/')}/{job_id}",
                "catalog_index": index,
            }
        )
    return records


def parse_detail_payload(payload: Any, *, expected_title: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DatahouseZurichParseError("Datahouse vacancy detail response must be an object")
    job_id = extract_job_id(payload.get("id"))
    company = payload.get("company")
    location = payload.get("location")
    active = payload.get("active")
    sections = nested_dict(payload, "jobAd", "sections")
    description = extract_description(payload)
    if (
        not job_id
        or not isinstance(active, bool)
        or optional_text(payload.get("visibility")) != "PUBLIC"
        or optional_text(payload.get("name")) != optional_text(expected_title)
        or not valid_company(company)
        or not valid_zurich_location(location)
        or not optional_text(payload.get("releasedDate"))
        or not isinstance(sections, dict)
        or not description
        or "datahouse" not in description.casefold()
    ):
        raise DatahouseZurichParseError(
            "Datahouse vacancy detail response is incomplete or inconsistent"
        )
    if active is False:
        # SmartRecruiters can republish an expired role under a new URL while the
        # old payload keeps its original ID. The listing must still be removed,
        # so do not require active-posting URL identity for an expired record.
        return dict(payload)
    if not valid_posting_url(payload.get("postingUrl"), job_id=job_id) or not valid_posting_url(
        payload.get("applyUrl"),
        job_id=job_id,
        require_apply_query=True,
    ):
        raise DatahouseZurichParseError(
            "Datahouse vacancy detail response is incomplete or inconsistent"
        )
    return dict(payload)


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) and detail.get("active") is True else {}
    public_url = valid_posting_url(
        detail.get("postingUrl"), job_id=extract_job_id(detail.get("id"))
    ) or optional_text(record.get("url"))
    apply_url = valid_posting_url(
        detail.get("applyUrl"),
        job_id=extract_job_id(detail.get("id")),
        require_apply_query=True,
    )
    return ParsedJob(
        source="datahouse_zurich",
        title=optional_text(detail.get("name")) or optional_text(record.get("title")),
        company=DATAHOUSE_COMPANY,
        location=extract_location(detail) or optional_text(record.get("location")),
        url=public_url,
        apply_url=apply_url or public_url,
        posted_at=optional_text(detail.get("releasedDate")),
        employment_type=extract_employment_type(detail, title=record.get("title")),
        seniority=extract_seniority(detail),
        description=(
            extract_description(detail)
            or optional_multiline_text(record.get("listing_description"))
        ),
        raw=dict(record),
    )


def valid_company(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and optional_text(value.get("identifier")) == SMARTRECRUITERS_COMPANY_IDENTIFIER
        and optional_text(value.get("name")) == "Wüest Partner"
    )


def valid_zurich_location(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    city = optional_text(value.get("city"))
    country = optional_text(value.get("country"))
    return bool(
        city and city.casefold() in {"zurich", "zürich"} and country and country.casefold() == "ch"
    )


def valid_posting_url(
    value: Any,
    *,
    job_id: str | None,
    require_apply_query: bool = False,
) -> str | None:
    text = optional_text(value)
    if not text or not job_id:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path.rstrip("/"))
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or not match
        or match.group("id") != job_id
        or parts.fragment
    ):
        return None
    query = parse_qs(parts.query)
    if require_apply_query:
        if query != {"oga": ["true"]}:
            return None
    elif query:
        return None
    return text


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or JOB_PATH_PATTERN.fullmatch(path) is None
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.smartrecruiters.com", path, "", ""))


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or parts.netloc.casefold() != "www.datahouse.ch":
        return None
    if parts.path.rstrip("/") != "/en/career" or parts.query or parts.fragment:
        return None
    return "https://www.datahouse.ch/en/career/"


def job_id_from_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(text).path.rstrip("/"))
    return extract_job_id(match.group("id")) if match else None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    return text if text and text.isdigit() and int(text) > 0 else None


def extract_location(record: dict[str, Any]) -> str | None:
    location = record.get("location")
    if not isinstance(location, dict):
        return None
    full_location = optional_text(location.get("fullLocation"))
    if full_location and full_location != ",":
        label = ", ".join(part.strip() for part in full_location.split(",") if part.strip())
    else:
        city = optional_text(location.get("city"))
        region = optional_text(location.get("region"))
        label = ", ".join(value for value in (city, region, "Switzerland") if value)
    work_mode = "Remote" if location.get("remote") is True else None
    if location.get("hybrid") is True:
        work_mode = "Hybrid"
    if label and work_mode:
        return f"{label} ({work_mode})"
    return label or work_mode


def extract_employment_type(record: dict[str, Any], *, title: Any) -> str | None:
    employment = record.get("typeOfEmployment")
    label = optional_text(employment.get("label")) if isinstance(employment, dict) else None
    title_text = optional_text(title)
    workload_match = WORKLOAD_PATTERN.search(title_text) if title_text else None
    workload = (
        optional_text(re.sub(r"\s*[–-]\s*", "–", workload_match.group(0)))
        if workload_match
        else None
    )
    if label and workload:
        return f"{label} ({workload})"
    return label or workload


def extract_seniority(record: dict[str, Any]) -> str | None:
    experience = record.get("experienceLevel")
    return optional_text(experience.get("label")) if isinstance(experience, dict) else None


def extract_description(record: dict[str, Any]) -> str | None:
    sections = nested_dict(record, "jobAd", "sections")
    if not isinstance(sections, dict):
        return None
    values: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        section_text = html_to_text(optional_text(section.get("text")))
        if not section_text:
            continue
        title = optional_text(section.get("title"))
        value = f"{title}\n{section_text}" if title else section_text
        if value not in values:
            values.append(value)
    return "\n\n".join(values) or None


def deduplicate_datahouse_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        detail = job.raw.get("detail")
        detail_id = extract_job_id(detail.get("id")) if isinstance(detail, dict) else None
        key = detail_id or extract_job_id(job.raw.get("id")) or job.url or ""
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
