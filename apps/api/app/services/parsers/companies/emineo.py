from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit
from xml.etree import ElementTree

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

EMINEO_CAREERS_URL = "https://emineo.ch/en/career/open-positions/"
EMINEO_EXPORT_URL = "https://recruitingapp-2895.umantis.com/XMLExport/136"
EMINEO_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "emineo AG"
EXPECTED_SITE_NAME = "emineo"
EXPECTED_LANGUAGE = "en-US"
EXPECTED_EXPORT_MARKER = EMINEO_EXPORT_URL
EXPECTED_LOCATIONS = {"Baar", "Zürich", "Lausanne"}
DETAIL_PATH_PATTERN = re.compile(r"^/en/career/open-positions/job-description/([1-9]\d*)/?$")
APPLY_PATH_PATTERN = re.compile(r"^/Vacancies/([1-9]\d*)/Application/CheckLogin/2/?$")
DATE_PATTERN = re.compile(r"^(\d{2}\.\d{2}\.\d{4}) CET$")
WORKLOAD_RANGE_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%(?!\d)")
WORKLOAD_PATTERN = re.compile(r"(?<!\d)(\d{1,3})\s*%(?!\d)")


class EmineoParseError(DirectCompanyRequestError):
    pass


class EmineoJobsParser:
    """Collect emineo's complete English Umantis vacancy catalog."""

    parser_id = "emineo"

    def __init__(
        self,
        *,
        base_url: str = EMINEO_CAREERS_URL,
        export_url: str = EMINEO_EXPORT_URL,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.export_url = export_url
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**EMINEO_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                page_response = client.get(self.base_url)
                page_response.raise_for_status()
                listing_records = parse_listing_html(
                    page_response.text,
                    page_url=str(page_response.url),
                    expected_url=self.base_url,
                    expected_export_url=self.export_url,
                )
                export_response = client.get(
                    self.export_url,
                    headers={"Referer": self.base_url},
                )
                export_response.raise_for_status()
                export_records = parse_export_xml(
                    export_response.text,
                    page_url=str(export_response.url),
                    expected_url=self.export_url,
                    careers_url=self.base_url,
                )
                records = reconcile_catalogs(listing_records, export_records)
        except EmineoParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("emineo vacancy request failed") from exc
        except (ElementTree.ParseError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("emineo vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_emineo_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=f"Scanned {len(jobs)} emineo Switzerland vacancies from the official catalog",
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_export_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise EmineoParseError("emineo listing returned an unexpected page")
    page = Selector(page_html)
    validate_listing_identity(page, expected_url=expected_url)
    export_markers = {
        value
        for raw in page.css("style[data-test]::attr(data-test)").getall()
        if (value := optional_text(raw))
    }
    containers = page.css(".jobs-list-main-container")
    cards = containers[0].css(":scope > .single-job-col-4") if len(containers) == 1 else []
    if export_markers != {expected_export_url} or not cards:
        raise EmineoParseError("emineo listing is missing its complete vacancy catalog")

    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        titles = unique_selector_texts(card, ".job-title")
        locations = unique_selector_texts(card, ".job-location")
        dates = unique_selector_texts(card, ".job-online-from")
        categories = unique_selector_texts(card, ".job-category")
        descriptions = unique_selector_texts(card, ".job-description")
        links = card.css("a.btn-link::attr(href)").getall()
        if (
            not all(
                len(values) == 1 for values in (titles, locations, dates, categories, descriptions)
            )
            or len(links) != 1
        ):
            raise EmineoParseError("emineo listing contains an incomplete vacancy")

        public_url = urljoin(page_url, optional_text(links[0]) or "")
        job_id = extract_detail_id(public_url, expected_host=expected_host)
        title = next(iter(titles))
        location = next(iter(locations))
        date_text = re.sub(r"^Online since:\s*", "", next(iter(dates)))
        if (
            not job_id
            or not normalize_locations(location)
            or not normalize_date(date_text)
            or job_id in seen_ids
        ):
            raise EmineoParseError("emineo listing contains an invalid vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "location_text": location,
                "posted_at": normalize_date(date_text),
                "category": next(iter(categories)).lstrip("_"),
                "summary": next(iter(descriptions)),
                "url": public_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_export_xml(
    xml_text: str,
    *,
    page_url: str,
    expected_url: str,
    careers_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise EmineoParseError("emineo export returned an unexpected page")
    root = ElementTree.fromstring(xml_text)
    containers = root.findall("./vacancies") if root.tag == "Jobs" else []
    if len(containers) != 1:
        raise EmineoParseError("emineo export has an invalid contract")

    grouped: list[list[ElementTree.Element]] = []
    current: list[ElementTree.Element] = []
    for child in list(containers[0]):
        if child.tag == "PosID":
            if current:
                grouped.append(current)
            current = [child]
        elif current:
            current.append(child)
    if current:
        grouped.append(current)
    if not grouped:
        raise EmineoParseError("emineo export is missing its vacancy catalog")

    careers_host = urlsplit(careers_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for elements in grouped:
        record_root = ElementTree.Element("record")
        record_root.extend(elements)
        job_id = element_text(record_root, "./PosID")
        title = element_text(record_root, "./Ausschreibungstext/Stellentitel")
        location_text = element_text(record_root, "./Suchkriterien/Arbeitsort")
        posted_at = normalize_date(element_text(record_root, "./LastModified"))
        apply_url = element_text(record_root, "./Apply_url")
        public_url = urljoin(careers_url, f"job-description/{job_id}") if job_id else None
        description = export_description(record_root)
        if (
            not job_id
            or not job_id.isdigit()
            or not title
            or not normalize_locations(location_text)
            or not posted_at
            or not public_url
            or extract_detail_id(public_url, expected_host=careers_host) != job_id
            or not is_apply_url(apply_url, expected_job_id=job_id)
            or not description
            or job_id in seen_ids
        ):
            raise EmineoParseError("emineo export contains an invalid vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "location_text": location_text,
                "location": normalize_locations(location_text),
                "posted_at": posted_at,
                "employment_type": normalize_workload(title)
                or element_text(record_root, "./Suchkriterien/Beschäftigungsart"),
                "seniority": element_text(record_root, "./Suchkriterien/EinstiegAls"),
                "category": element_text(record_root, "./Suchkriterien/Unternehmensbereich"),
                "summary": element_text(record_root, "./Ausschreibungstext/Kurzbeschreibung"),
                "description": description,
                "url": public_url,
                "apply_url": apply_url,
                "export_page_url": page_url,
            }
        )
    return records


def reconcile_catalogs(
    listing_records: list[dict[str, Any]],
    export_records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    listing_by_id = {record["id"]: record for record in listing_records}
    export_by_id = {record["id"]: record for record in export_records}
    if set(listing_by_id) != set(export_by_id):
        raise EmineoParseError("emineo listing and export catalogs do not match")
    reconciled: list[dict[str, Any]] = []
    for listing in listing_records:
        exported = export_by_id[listing["id"]]
        if any(
            comparable_text(listing[key]) != comparable_text(exported[key])
            for key in ("title", "location_text", "category", "summary", "posted_at", "url")
        ):
            raise EmineoParseError("emineo listing and export vacancy details do not match")
        reconciled.append({**listing, **exported, "listing": listing})
    return reconciled


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    return ParsedJob(
        source="emineo",
        title=optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=optional_text(record.get("location")),
        url=optional_text(record.get("url")),
        apply_url=optional_text(record.get("apply_url")),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=optional_text(record.get("employment_type")),
        seniority=optional_text(record.get("seniority")),
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def validate_listing_identity(page: Selector, *, expected_url: str) -> None:
    canonicals = unique_attribute_values(page, 'link[rel="canonical"]', "href")
    site_names = unique_attribute_values(page, 'meta[property="og:site_name"]', "content")
    languages = unique_attribute_values(page, "html", "lang")
    if (
        len(canonicals) != 1
        or not same_url(next(iter(canonicals)), expected_url)
        or site_names != {EXPECTED_SITE_NAME}
        or languages != {EXPECTED_LANGUAGE}
    ):
        raise EmineoParseError("emineo listing has an unexpected identity")


def extract_detail_id(value: Any, *, expected_host: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = DETAIL_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def is_apply_url(value: Any, *, expected_job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "recruitingapp-2895.umantis.com"
        and match is not None
        and match.group(1) == expected_job_id
        and parse_qs(parts.query, keep_blank_values=True) == {"lang": ["eng"]}
        and not parts.fragment
    )


def normalize_locations(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    locations = [item.strip() for item in text.split(",") if item.strip()]
    if not locations or any(location not in EXPECTED_LOCATIONS for location in locations):
        return None
    return " / ".join(locations) + ", Switzerland"


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    match = DATE_PATTERN.fullmatch(text or "")
    if not match:
        return None
    try:
        day, month, year = (int(item) for item in match.group(1).split("."))
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def export_description(record: ElementTree.Element) -> str | None:
    parts: list[str] = []
    summary = element_text(record, "./Ausschreibungstext/Kurzbeschreibung")
    if summary:
        parts.append(summary)
    for title_path, text_path in (
        ("./Ausschreibungstext/TitelAufgaben", "./Ausschreibungstext/TextAufgaben"),
        ("./Ausschreibungstext/TitelAnforderungen", "./Ausschreibungstext/TextAnforderungen"),
        ("./Ausschreibungstext/TitelWirbieten", "./Ausschreibungstext/TextWirbieten"),
    ):
        title = element_text(record, title_path)
        text = html_to_text(element_text(record, text_path) or "")
        if title and text:
            parts.append(f"{title}\n{text}")
    return optional_multiline_text("\n\n".join(parts))


def element_text(root: ElementTree.Element, path: str) -> str | None:
    element = root.find(path)
    return optional_text(element.text) if element is not None else None


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
        and actual.query == target.query
        and not actual.fragment
    )


def deduplicate_emineo_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for raw in selector.css(f'{css}::attr("{attribute}")').getall()
        if (value := optional_text(raw))
    }


def html_to_text(value: str) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


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
