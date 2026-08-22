from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import quote_plus, unquote, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

OPERAIO_CAREERS_URL = "https://www.operaio.ch/en/career"
OPERAIO_COMPANY = "Operaio GmbH"
OPERAIO_CONTACT_URL = "https://www.operaio.ch/en/about-us"
OPERAIO_CONTACT_EMAIL = "customer@operaio.ch"
OPERAIO_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
EXPECTED_SITE_NAME = "operaio.ch"
EXPECTED_LANGUAGE = "en"
EXPECTED_PAGE_HEADING = "Become an Operaio"
EXPECTED_CATALOG_HEADING = "Our open positions"
WIX_ID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
LINKEDIN_JOB_PATH_PATTERN = re.compile(r"^/jobs/view/(?:[^/]+-)?(\d+)/?$")
WORKLOAD_PATTERN = re.compile(r"^\d{1,3}\s*[–-]\s*\d{1,3}%$")


class OperaioParseError(DirectCompanyRequestError):
    pass


class OperaioJobsParser:
    """Collect Operaio's complete official Wix CMS vacancy catalog."""

    parser_id = "operaio"

    def __init__(
        self,
        *,
        base_url: str = OPERAIO_CAREERS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=OPERAIO_HEADERS,
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
        except OperaioParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Operaio vacancy request failed") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Operaio vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_operaio_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Operaio vacancies from the complete official "
                "Wix CMS catalog"
            ),
        )


def parse_catalog_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise OperaioParseError("Operaio careers catalog returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    headings = {selector_text(node) for node in page.css("h1, h2")}
    if not {EXPECTED_PAGE_HEADING, EXPECTED_CATALOG_HEADING}.issubset(headings):
        raise OperaioParseError("Operaio careers page is missing its vacancy catalog")

    viewer = parse_json_script(page, "wix-viewer-model")
    business_name = nested_value(
        viewer,
        "siteFeaturesConfigs",
        "seo",
        "context",
        "businessName",
    )
    if business_name != OPERAIO_COMPANY:
        raise OperaioParseError("Operaio careers page has an invalid business identity")

    warmup = parse_json_script(page, "wix-warmup-data")
    records_value = nested_value(
        warmup,
        "appsWarmupData",
        "dataBinding",
        "dataStore",
        "recordsByCollectionId",
        "Career",
    )
    if not isinstance(records_value, dict):
        raise OperaioParseError("Operaio careers page has an invalid CMS catalog")
    records_by_id = records_value

    cards = [
        card
        for card in page.css('div.wixui-repeater__item[role="listitem"]')
        if extract_card_id(card.attrib.get("id"))
    ]
    if len(cards) != len(records_by_id):
        raise OperaioParseError("Operaio CMS catalog does not match its visible cards")
    if len(cards) > max_jobs:
        raise OperaioParseError(
            f"Operaio exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )

    contact_emails = {
        normalized
        for value in page.css('a[href^="mailto:"]::attr(href)').getall()
        if (normalized := normalize_contact_email(value))
    }
    if contact_emails != {f"mailto:{OPERAIO_CONTACT_EMAIL}"}:
        raise OperaioParseError("Operaio careers page is missing its official contact email")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, card in enumerate(cards):
        record_id = extract_card_id(card.attrib.get("id"))
        record_value = records_by_id.get(record_id or "")
        if not record_id or record_id in seen_ids or not isinstance(record_value, dict):
            raise OperaioParseError("Operaio careers catalog contains an invalid card")
        seen_ids.add(record_id)
        records.append(
            normalize_catalog_record(
                record_value,
                card=card,
                record_id=record_id,
                catalog_index=index,
                listing_page_url=canonical_careers_url(page_url),
            )
        )
    if seen_ids != set(records_by_id):
        raise OperaioParseError("Operaio CMS catalog contains unlisted vacancies")
    return records


def normalize_catalog_record(
    value: dict[str, Any],
    *,
    card: Any,
    record_id: str,
    catalog_index: int,
    listing_page_url: str | None,
) -> dict[str, Any]:
    raw_id = optional_text(value.get("_id"))
    title = optional_text(value.get("title"))
    location = optional_text(value.get("location"))
    arrangement = optional_text(value.get("employmentType"))
    workload = normalize_workload(value.get("workMode"))
    created_at = extract_wix_date(value.get("_createdDate"))
    updated_at = extract_wix_date(value.get("_updatedDate"))

    card_headings = [selector_text(node) for node in card.css("h4")]
    card_values = {
        text for node in card.css("p") if (text := selector_text(node))
    }
    card_workloads = {
        normalized
        for text in card_values
        if (normalized := normalize_workload(text))
    }
    contact_links = {
        normalized
        for raw in card.css('a[data-testid="linkElement"]::attr(href)').getall()
        if (normalized := canonical_contact_url(raw))
    }
    contact_labels = {
        selector_text(node)
        for node in card.css('a[data-testid="linkElement"]')
        if selector_text(node)
    }
    if (
        raw_id != record_id
        or not title
        or not location
        or "Zürich Flughafen" not in location
        or "Stettlen" not in location
        or arrangement != "Hybrid"
        or not workload
        or not created_at
        or not updated_at
        or card_headings != [title]
        or not {location, arrangement}.issubset(card_values)
        or card_workloads != {workload}
        or contact_links != {OPERAIO_CONTACT_URL}
        or contact_labels != {"Contact Us"}
    ):
        raise OperaioParseError("Operaio careers catalog contains an incomplete vacancy")

    raw_link = optional_text(value.get("link"))
    public_url = canonical_linkedin_job_url(raw_link) if raw_link else None
    if raw_link and not public_url:
        raise OperaioParseError("Operaio CMS catalog contains an unsafe application link")
    apply_url = public_url or application_email_url(title)
    description = "\n".join(
        (
            title,
            f"Location: {location}",
            f"Work arrangement: {arrangement}",
            f"Workload: {workload}",
        )
    )
    return {
        "id": record_id,
        "title": title,
        "company": OPERAIO_COMPANY,
        "location": f"{location}, Switzerland",
        "arrangement": arrangement,
        "workload": workload,
        "url": public_url,
        "apply_url": apply_url,
        "posted_at": created_at,
        "updated_at": updated_at,
        "description": description,
        "catalog_index": catalog_index,
        "listing_page_url": listing_page_url,
        "contact_url": OPERAIO_CONTACT_URL,
        "cms_record": dict(value),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    title = optional_text(record.get("title"))
    workload = optional_text(record.get("workload"))
    arrangement = optional_text(record.get("arrangement"))
    employment_type = " · ".join(
        value for value in (workload, arrangement) if value
    ) or None
    return ParsedJob(
        source="operaio",
        title=title,
        company=OPERAIO_COMPANY,
        location=optional_text(record.get("location")),
        url=optional_text(record.get("url")),
        apply_url=optional_text(record.get("apply_url")),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=employment_type,
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise OperaioParseError("Operaio page has an invalid identity")


def parse_json_script(page: Selector, script_id: str) -> dict[str, Any]:
    scripts = page.css(f"script#{script_id}")
    if len(scripts) != 1:
        raise OperaioParseError(f"Operaio page is missing {script_id}")
    raw = scripts[0].css("::text").get()
    try:
        payload = json.loads(str(raw))
    except (TypeError, json.JSONDecodeError) as exc:
        raise OperaioParseError(f"Operaio page contains invalid {script_id}") from exc
    if not isinstance(payload, dict):
        raise OperaioParseError(f"Operaio page contains invalid {script_id}")
    return payload


def nested_value(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def extract_card_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text or "__" not in text:
        return None
    record_id = text.rsplit("__", 1)[-1].casefold()
    return record_id if WIX_ID_PATTERN.fullmatch(record_id) else None


def extract_wix_date(value: Any) -> str | None:
    if not isinstance(value, dict) or set(value) != {"$date"}:
        return None
    return optional_text(value.get("$date"))


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text).replace(" - ", "–")
    return normalized if WORKLOAD_PATTERN.fullmatch(normalized) else None


def canonical_linkedin_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = LINKEDIN_JOB_PATH_PATTERN.fullmatch(unquote(parts.path))
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "linkedin.com"
        or not match
        or parts.fragment
    ):
        return None
    return f"https://www.linkedin.com/jobs/view/{match.group(1)}"


def canonical_contact_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "operaio.ch"
        or parts.path.rstrip("/") not in {"/en/about-us", "/about-us"}
        or parts.query
        or parts.fragment
    ):
        return None
    return OPERAIO_CONTACT_URL


def canonical_careers_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "operaio.ch"
        or parts.path.rstrip("/") not in {"/en/career", "/career"}
        or parts.query
        or parts.fragment
    ):
        return None
    return OPERAIO_CAREERS_URL


def normalize_contact_email(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme.casefold() != "mailto"
        or unquote(parts.path).casefold() != OPERAIO_CONTACT_EMAIL
        or parts.query
        or parts.fragment
    ):
        return None
    return f"mailto:{OPERAIO_CONTACT_EMAIL}"


def application_email_url(title: str) -> str:
    subject = quote_plus(f"Application for {title}")
    return f"mailto:{OPERAIO_CONTACT_EMAIL}?subject={subject}"


def same_url(value: Any, expected: Any) -> bool:
    actual = canonical_careers_url(value)
    target = canonical_careers_url(expected)
    return bool(actual and target and actual == target)


def deduplicate_operaio_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id"))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(selector: Any) -> str | None:
    return optional_text(" ".join(selector.css("::text").getall()))


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).split()) or None
