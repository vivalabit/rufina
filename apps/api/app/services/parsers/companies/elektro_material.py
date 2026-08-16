from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ELEKTRO_MATERIAL_JOBS_BASE_URL = (
    "https://elektro-material.ch/de/cms/seite/offene-stellen-t33143s226453a4614994"
)
ELEKTRO_MATERIAL_CMS_API_URL = (
    "https://www.elektro-material.ch/emwebservices/v2/elektromaterial/cms/pages"
)
ELEKTRO_MATERIAL_SMARTRECRUITERS_API_URL = (
    "https://api.smartrecruiters.com/v1/companies/REXEL1/postings"
)
LISTING_PAGE_ID = "offene-stellen-t33143s226453a4614994"
COMPANY_NAME = "Elektro-Material AG"
SMARTRECRUITERS_COMPANY = "REXEL1"
CMS_JOB_PATH = re.compile(r"^/de/cms/seite/([a-z0-9-]+)$")
ONECLICK_PATH = re.compile(
    r"^/oneclick-ui/company/REXEL1/publication/"
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"\b\d{1,3}(?:\s*[–-]\s*\d{1,3})?\s*%")
HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}


class ElektroMaterialParseError(DirectCompanyRequestError):
    pass


class ElektroMaterialJobsParser:
    """Collect Elektro-Material's complete CMS vacancy catalog."""

    parser_id = "elektro_material"

    def __init__(
        self,
        *,
        base_url: str = ELEKTRO_MATERIAL_JOBS_BASE_URL,
        cms_api_url: str = ELEKTRO_MATERIAL_CMS_API_URL,
        smartrecruiters_api_url: str = ELEKTRO_MATERIAL_SMARTRECRUITERS_API_URL,
        timeout_seconds: float = 30.0,
        max_catalog_records: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.cms_api_url = cms_api_url
        self.smartrecruiters_api_url = smartrecruiters_api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_catalog_records = max(1, max_catalog_records)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(
                    self.cms_api_url,
                    params=cms_params(LISTING_PAGE_ID),
                )
                response.raise_for_status()
                records = parse_catalog_payload(
                    response.json(),
                    page_url=self.base_url,
                    max_records=self.max_catalog_records,
                )
                self.enrich_records(client, records)
        except ElektroMaterialParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Elektro-Material vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Elektro-Material vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Elektro-Material vacancies from "
                f"{len(records)} CMS catalog records"
            ),
        )

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
    ) -> None:
        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                cms_response = client.get(
                    self.cms_api_url,
                    params=cms_params(record["slug"]),
                )
                cms_response.raise_for_status()
                cms_detail = parse_detail_cms_payload(
                    cms_response.json(),
                    expected_title=record["title"],
                    expected_url=record["url"],
                )
                api_response = client.get(
                    f"{self.smartrecruiters_api_url}/{cms_detail['publication_uuid']}"
                )
                api_response.raise_for_status()
                detail = parse_smartrecruiters_payload(
                    api_response.json(),
                    expected_uuid=cms_detail["publication_uuid"],
                    expected_title=record["title"],
                    expected_location=record["location"],
                    apply_url=cms_detail["apply_url"],
                )
                detail["cms"] = cms_detail
                return record, detail
            except (
                httpx.HTTPError,
                ElektroMaterialParseError,
                TypeError,
                ValueError,
            ) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records) or 1)) as pool:
            futures = [pool.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or record["title"],
            company=COMPANY_NAME,
            location=optional_text(detail.get("location")) or record["location"],
            url=optional_text(detail.get("url")) or record["url"],
            apply_url=optional_text(detail.get("apply_url")),
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=(
                optional_text(detail.get("employment_type")) or extract_workload(record["title"])
            ),
            seniority=optional_text(detail.get("seniority")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def cms_params(page_id: str) -> dict[str, str]:
    return {
        "fields": "DEFAULT",
        "pageLabelOrId": page_id,
        "pageType": "ContentPage",
        "cmsTicketId": "",
        "lang": "de",
        "curr": "CHF",
    }


def parse_catalog_payload(
    payload: Any,
    *,
    page_url: str,
    max_records: int,
) -> list[dict[str, Any]]:
    validate_page(
        payload,
        expected_title="Jobs und Karriere : Offene Stellen",
        expected_type="EMCorporateContentPage2",
    )
    components = main_components(payload)
    records: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    seen_uids: set[str] = set()

    for component in components:
        if component.get("typeCode") != "CMSParagraphComponent":
            continue
        content = component.get("content")
        if not isinstance(content, str):
            continue
        page = Selector(content)
        title_nodes = page.css("h3").getall()
        if not title_nodes:
            continue
        job_links = [
            optional_text(link)
            for link in page.css('a[href*="/de/cms/seite/"]::attr(href)').getall()
        ]
        job_links = [link for link in job_links if link]
        if not job_links:
            continue
        if len(job_links) != 1:
            raise ElektroMaterialParseError(
                "Elektro-Material listing contains an ambiguous vacancy link"
            )
        match = CMS_JOB_PATH.fullmatch(urlsplit(job_links[0]).path)
        titles = [optional_text(value) for value in title_nodes]
        titles = [html_to_text(value) for value in titles if value]
        paragraph = html_to_text(page.css("p").get())
        anchor_text = html_to_text(page.css("a").get())
        uid = optional_text(component.get("uid"))
        modified_at = normalize_timestamp(component.get("modifiedtime"))
        if (
            not match
            or len(titles) != 1
            or not titles[0]
            or not paragraph
            or anchor_text != "Mehr erfahren"
            or not uid
            or not modified_at
        ):
            raise ElektroMaterialParseError(
                "Elektro-Material listing contains an incomplete vacancy"
            )
        location = parse_listing_location(paragraph, anchor_text=anchor_text)
        slug = match.group(1)
        if not location:
            raise ElektroMaterialParseError(
                "Elektro-Material listing contains an invalid Swiss location"
            )
        if slug in seen_slugs or uid in seen_uids:
            raise ElektroMaterialParseError("Elektro-Material listing contains duplicate vacancies")
        seen_slugs.add(slug)
        seen_uids.add(uid)
        records.append(
            {
                "id": slug,
                "slug": slug,
                "listing_component_uid": uid,
                "title": titles[0],
                "location": location,
                "url": urljoin(page_url, job_links[0]),
                "listing_modified_at": modified_at,
            }
        )

    if not records:
        raise ElektroMaterialParseError("Elektro-Material listing did not expose any vacancies")
    if len(records) > max_records:
        raise ElektroMaterialParseError(
            f"Elektro-Material returned {len(records)} records, above the configured "
            f"limit of {max_records}"
        )
    for record in records:
        record["total_available"] = len(records)
    return records


def parse_detail_cms_payload(
    payload: Any,
    *,
    expected_title: str,
    expected_url: str,
) -> dict[str, Any]:
    if (
        not isinstance(payload, dict)
        or optional_text(payload.get("typeCode")) != "EMCorporateContentPage2"
        or not optional_text(payload.get("uid"))
        or not optional_text(payload.get("title"))
    ):
        raise ElektroMaterialParseError("Elektro-Material detail page returned an unexpected page")
    components = main_components(payload)
    descriptions: list[dict[str, Any]] = []
    buttons: list[dict[str, Any]] = []
    for component in components:
        if not isinstance(component, dict):
            raise ElektroMaterialParseError(
                "Elektro-Material detail page contains an invalid component"
            )
        if component.get("typeCode") == "CMSParagraphComponent":
            content = component.get("content")
            if isinstance(content, str) and Selector(content).css("h1").get():
                descriptions.append(component)
        elif component.get("typeCode") == "CMSButtonComponent":
            button_title = optional_text(component.get("title"))
            if button_title and button_title.casefold() == "jetzt bewerben":
                buttons.append(component)
    if len(descriptions) != 1 or len(buttons) != 1:
        raise ElektroMaterialParseError(
            "Elektro-Material detail page has an ambiguous description or apply button"
        )

    content = descriptions[0].get("content")
    description = html_to_text(content)
    detail_title = html_to_text(Selector(content).css("h1").get())
    apply_url = optional_text(buttons[0].get("localizedUrl"))
    publication_uuid = publication_id(apply_url)
    if (
        detail_title != optional_text(expected_title)
        or not description
        or not publication_uuid
        or not valid_cms_job_url(expected_url)
    ):
        raise ElektroMaterialParseError(
            "Elektro-Material detail page is incomplete or inconsistent"
        )
    return {
        "page_uid": optional_text(payload.get("uid")),
        "description_component_uid": optional_text(descriptions[0].get("uid")),
        "apply_component_uid": optional_text(buttons[0].get("uid")),
        "publication_uuid": publication_uuid,
        "apply_url": apply_url,
        "description": description,
    }


def parse_smartrecruiters_payload(
    payload: Any,
    *,
    expected_uuid: str,
    expected_title: str,
    expected_location: str,
    apply_url: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ElektroMaterialParseError(
            "Elektro-Material SmartRecruiters response must be an object"
        )
    job_id = optional_text(payload.get("id"))
    title = optional_text(payload.get("name"))
    company = payload.get("company")
    location = payload.get("location")
    custom_fields = custom_field_map(payload.get("customField"))
    posting_url = valid_posting_url(payload.get("postingUrl"), job_id=job_id)
    released_at = normalize_timestamp(payload.get("releasedDate"))
    description = smartrecruiters_description(payload)
    expected_city = expected_location.split(",", maxsplit=1)[0]
    actual_city = optional_text(location.get("city")) if isinstance(location, dict) else None
    if (
        not job_id
        or not job_id.isdigit()
        or optional_text(payload.get("uuid")) != expected_uuid
        or not titles_match(title, expected_title)
        or payload.get("active") is not True
        or optional_text(payload.get("visibility")) != "PUBLIC"
        or not isinstance(company, dict)
        or optional_text(company.get("identifier")) != SMARTRECRUITERS_COMPANY
        or optional_text(company.get("name")) != "REXEL"
        or not isinstance(location, dict)
        or optional_text(location.get("country")) != "ch"
        or not actual_city
        or actual_city.casefold() != expected_city.casefold()
        or custom_fields.get("Legal Entity") != COMPANY_NAME.upper()
        or custom_fields.get("Country/Region") != "Switzerland"
        or custom_fields.get("Brands") != COMPANY_NAME
        or not posting_url
        or not released_at
        or not description
        or publication_id(apply_url) != expected_uuid
    ):
        raise ElektroMaterialParseError(
            "Elektro-Material SmartRecruiters vacancy is incomplete or inconsistent"
        )
    return {
        "id": job_id,
        "publication_uuid": expected_uuid,
        "title": optional_text(expected_title),
        "company": COMPANY_NAME,
        "location": f"{actual_city}, Switzerland",
        "url": posting_url,
        "apply_url": apply_url,
        "posted_at": released_at,
        "employment_type": (
            custom_fields.get("Employment Type")
            or nested_text(payload, "typeOfEmployment", "label")
        ),
        "seniority": nested_text(payload, "experienceLevel", "label"),
        "description": description,
        "ref_number": optional_text(payload.get("refNumber")),
        "custom_fields": custom_fields,
    }


def validate_page(payload: Any, *, expected_title: str, expected_type: str) -> None:
    if (
        not isinstance(payload, dict)
        or optional_text(payload.get("title")) != optional_text(expected_title)
        or optional_text(payload.get("typeCode")) != expected_type
        or not optional_text(payload.get("uid"))
    ):
        raise ElektroMaterialParseError("Elektro-Material CMS returned an unexpected page")


def main_components(payload: dict[str, Any]) -> list[dict[str, Any]]:
    content_slots = payload.get("contentSlots")
    slots = content_slots.get("contentSlot") if isinstance(content_slots, dict) else None
    if not isinstance(slots, list):
        raise ElektroMaterialParseError("Elektro-Material CMS page has invalid slots")
    main_slots = [
        slot for slot in slots if isinstance(slot, dict) and slot.get("position") == "MainContent"
    ]
    if len(main_slots) != 1:
        raise ElektroMaterialParseError("Elektro-Material CMS page is missing its main content")
    components_data = main_slots[0].get("components")
    components = components_data.get("component") if isinstance(components_data, dict) else None
    if not isinstance(components, list) or not all(isinstance(item, dict) for item in components):
        raise ElektroMaterialParseError("Elektro-Material CMS page has invalid components")
    return components


def parse_listing_location(value: str, *, anchor_text: str) -> str | None:
    text = optional_text(value.replace(anchor_text, ""))
    if not text:
        return None
    text = re.sub(r"^(?:Standort|Hauptsitz)\s+", "", text, flags=re.IGNORECASE)
    return f"{text}, Switzerland" if text and "," not in text else None


def publication_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = ONECLICK_PATH.fullmatch(parts.path)
    query = parse_qs(parts.query)
    if (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.smartrecruiters.com"
        and match
        and query == {"dcr_ci": [SMARTRECRUITERS_COMPANY]}
        and not parts.fragment
    ):
        return match.group(1).lower()
    return None


def valid_cms_job_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return bool(
        parts.scheme == "https"
        and parts.netloc.casefold() in {"elektro-material.ch", "www.elektro-material.ch"}
        and CMS_JOB_PATH.fullmatch(parts.path)
        and not parts.query
        and not parts.fragment
    )


def valid_posting_url(value: Any, *, job_id: str | None) -> str | None:
    text = optional_text(value)
    if not text or not job_id:
        return None
    parts = urlsplit(text)
    path_parts = [part for part in parts.path.split("/") if part]
    if (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.smartrecruiters.com"
        and len(path_parts) == 2
        and path_parts[0] == SMARTRECRUITERS_COMPANY
        and path_parts[1].startswith(f"{job_id}-")
        and not parts.query
        and not parts.fragment
    ):
        return text
    return None


def custom_field_map(value: Any) -> dict[str, str]:
    if not isinstance(value, list):
        return {}
    fields: dict[str, str] = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        label = optional_text(item.get("fieldLabel"))
        field_value = optional_text(item.get("valueLabel"))
        if label and field_value and label not in fields:
            fields[label] = field_value
    return fields


def smartrecruiters_description(payload: dict[str, Any]) -> str | None:
    job_ad = payload.get("jobAd")
    sections = job_ad.get("sections") if isinstance(job_ad, dict) else None
    if not isinstance(sections, dict):
        return None
    parts: list[str] = []
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        title = optional_text(section.get("title"))
        body = html_to_text(section.get("text"))
        if body:
            parts.append(f"{title}\n\n{body}" if title else body)
    return optional_multiline_text("\n\n".join(parts))


def nested_text(payload: dict[str, Any], key: str, child: str) -> str | None:
    value = payload.get(key)
    return optional_text(value.get(child)) if isinstance(value, dict) else None


def deduplicate_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        detail = job.raw.get("detail")
        key = optional_text(detail.get("id")) if isinstance(detail, dict) else None
        key = key or optional_text(job.raw.get("slug"))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def extract_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not (match := WORKLOAD_PATTERN.search(text)):
        return None
    return optional_text(re.sub(r"\s*[–-]\s*", "–", match.group(0)))


def titles_match(actual: Any, expected: Any) -> bool:
    actual_text = optional_text(actual)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    if actual_text.casefold() == expected_text.casefold():
        return True

    def without_workload(value: str) -> str | None:
        stripped = WORKLOAD_PATTERN.sub("", value)
        return optional_text(re.sub(r"[\s,;:–-]+$", "", stripped))

    actual_without_workload = without_workload(actual_text)
    expected_without_workload = without_workload(expected_text)
    return bool(
        actual_without_workload
        and expected_without_workload
        and actual_without_workload.casefold() == expected_without_workload.casefold()
    )


def normalize_timestamp(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    return optional_multiline_text(html.unescape(re.sub(r"<[^>]+>", "", text)))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
