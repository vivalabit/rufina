from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ISOLUTIONS_JOBS_URL = "https://www.isolutions.ch/en/career/#module-1396"
ISOLUTIONS_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
EXPECTED_COMPANY = "isolutions AG"
EXPECTED_LANGUAGE = "en-US"
EXPECTED_CATALOG_ID = "module-1396"
EXPECTED_DEPARTMENTS = {
    "1501": "Sales",
    "1502": "Development",
    "1618": "Infrastructure",
    "6250": "Managed Cloud Services",
    "1619": "Consulting",
}
EXPECTED_LOCATIONS = {
    "1257": "Bern",
    "1258": "Basel",
    "1259": "Zürich",
}
EXPECTED_FOOTER_PARTS = {
    "Schanzenstrasse 4c",
    "3008 Bern",
    "Güterstrasse 144",
    "4053 Basel",
    "The Circle 38",
    "8058 Zürich",
}
EXPECTED_REQUIREMENT_KEYS = {"responsibilities", "requirements"}
JOB_PATH_PATTERN = re.compile(r"^/en/career/([a-z0-9]+(?:-[a-z0-9]+)*)/?$")
MODULE_FRAGMENT_PATTERN = re.compile(r"^#(module-\d+)$")
FILTER_PATTERN = re.compile(r"^filter-(\d+)$")
PERSONIO_PATH_PATTERN = re.compile(r"^/job/(\d+)(?:/apply)?/?$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class IsolutionsParseError(DirectCompanyRequestError):
    pass


class IsolutionsJobsParser:
    """Collect isolutions AG's complete Swiss career catalog and Personio data."""

    parser_id = "isolutions"

    def __init__(
        self,
        *,
        base_url: str = ISOLUTIONS_JOBS_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ISOLUTIONS_HEADERS, "Referer": self.base_url},
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
                )
                self.enrich_records(client, records)
        except IsolutionsParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("isolutions vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("isolutions vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_isolutions_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} isolutions Switzerland vacancies from the "
                "official catalog"
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
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, IsolutionsParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

            ats_url = optional_text(detail.get("ats_url"))
            ats_kind = optional_text(detail.get("ats_kind"))
            if ats_url and ats_kind:
                try:
                    ats_response = client.get(
                        ats_url,
                        headers={"Referer": record["url"]},
                    )
                    ats_response.raise_for_status()
                    if ats_kind == "personio":
                        detail["ats"] = parse_personio_html(
                            ats_response.text,
                            expected_job_id=detail["ats_job_id"],
                            expected_title=detail["title"],
                            expected_locations=record["location_names"],
                        )
                    elif ats_kind == "breezy":
                        detail["ats"] = parse_breezy_html(
                            ats_response.text,
                            expected_job_id=detail["ats_job_id"],
                            expected_title=detail["title"],
                        )
                except (httpx.HTTPError, IsolutionsParseError, ValueError) as exc:
                    record["ats_error"] = str(exc)
            return record, detail

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        ats = detail.get("ats")
        ats = ats if isinstance(ats, dict) else {}
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=optional_text(record.get("location")),
            url=public_url,
            apply_url=optional_text(detail.get("apply_url")) or public_url,
            posted_at=optional_text(ats.get("posted_at")),
            employment_type=optional_text(ats.get("employment_type")),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
) -> list[dict[str, Any]]:
    if not same_url(page_url, expected_url):
        raise IsolutionsParseError("isolutions listing returned an unexpected page")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    validate_organization_schema(page)
    validate_swiss_footer(page)
    catalog_id = catalog_fragment_id(expected_url)
    catalogs = page.css(f"section#{catalog_id}.c-job-list") if catalog_id else []
    if len(catalogs) != 1:
        raise IsolutionsParseError("isolutions listing is missing its vacancy catalog")
    catalog = catalogs[0]
    if (
        optional_text(catalog.attrib.get("data-load-more-increase")) != "6"
        or unique_selector_texts(catalog, ":scope h3.c-section-heading") != {"Jobs"}
        or unique_selector_texts(catalog, ":scope h2.h2") != {"Vacancies for you"}
    ):
        raise IsolutionsParseError("isolutions listing has an invalid vacancy catalog")
    departments = parse_filter_options(catalog, group_name="Fields")
    locations = parse_filter_options(catalog, group_name="Locations")
    if departments != EXPECTED_DEPARTMENTS or locations != EXPECTED_LOCATIONS:
        raise IsolutionsParseError("isolutions listing has unexpected catalog filters")

    cards = catalog.css(":scope .c-job-list__table > a.c-job-list__row__container")
    if not cards:
        raise IsolutionsParseError("isolutions listing is missing its vacancy catalog")
    expected_host = urlsplit(expected_url).netloc.casefold()
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for card in cards:
        class_tokens = set((optional_text(card.attrib.get("class")) or "").split())
        filter_ids = {
            match.group(1)
            for token in class_tokens
            if (match := FILTER_PATTERN.fullmatch(token))
        }
        department_ids = filter_ids.intersection(departments)
        location_ids = filter_ids.intersection(locations)
        titles = unique_selector_texts(card, ":scope > .c-layout--md h4.h4")
        title_attribute = optional_text(card.attrib.get("title"))
        department_values = unique_selector_texts(
            card,
            ":scope > .c-layout--md > .col-12.col-md-8 > p.c-text",
        )
        location_values = [
            value
            for node in card.css(
                ":scope > .c-layout--md > .col-auto > p.c-text"
            )
            if (value := html_to_text(node.get()))
        ]
        detail_url = urljoin(page_url, optional_text(card.attrib.get("href")) or "")
        job_id = extract_job_id(detail_url, expected_host=expected_host)
        title = next(iter(titles)) if len(titles) == 1 else None
        location_names = split_locations(location_values[1] if len(location_values) == 2 else None)
        expected_location_names = {locations[item] for item in location_ids}
        department = (
            departments[next(iter(department_ids))]
            if len(department_ids) == 1
            else None
        )
        if (
            not job_id
            or job_id in seen_ids
            or not title
            or title_fingerprint(title) != title_fingerprint(title_attribute)
            or department_values != {department}
            or location_values[:1] != ["Location"]
            or not location_names
            or set(location_names) != expected_location_names
            or "filter-departments" not in class_tokens
            or "filter-locations" not in class_tokens
        ):
            raise IsolutionsParseError("isolutions listing contains an invalid vacancy")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": EXPECTED_COMPANY,
                "department": department,
                "location": ", ".join(location_names),
                "location_names": location_names,
                "url": detail_url,
                "listing_page_url": page_url,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    expected_host = urlsplit(expected_url).netloc.casefold()
    if (
        not same_url(page_url, expected_url)
        or extract_job_id(page_url, expected_host=expected_host) != expected_job_id
    ):
        raise IsolutionsParseError("isolutions detail page returned a different vacancy")

    page = Selector(page_html)
    validate_page_identity(page, expected_url=expected_url)
    validate_organization_schema(page)
    validate_swiss_footer(page)
    titles = unique_selector_texts(page, "main .c-headline__title h1")
    title = next(iter(titles)) if len(titles) == 1 else None
    og_titles = unique_attribute_values(page, 'meta[property="og:title"]', "content")
    if (
        not title
        or title_fingerprint(title) != title_fingerprint(expected_title)
        or len(og_titles) != 1
        or not compatible_title(next(iter(og_titles)), expected_title)
    ):
        raise IsolutionsParseError("isolutions detail page contains a different vacancy")

    description_section_id = job_description_section_id(page)
    description_sections = (
        page.css(f"main section#{description_section_id}")
        if description_section_id
        else []
    )
    requirement_nodes: dict[str, Any] = {}
    for node in page.css("main section .c-text__col .c-rte"):
        headings = unique_selector_texts(node, ":scope > h2")
        if len(headings) == 1:
            heading_key = requirement_heading_key(next(iter(headings)))
            if heading_key:
                requirement_nodes[heading_key] = node
    description_parts = [
        html_to_text(description_sections[0].get())
        if len(description_sections) == 1
        else None,
        *[
            html_to_text(requirement_nodes[key].get())
            for key in ("responsibilities", "requirements")
            if key in requirement_nodes
        ],
    ]
    description = optional_multiline_text(
        "\n\n".join(value for value in description_parts if value)
    )
    apply_urls = {
        value
        for raw in page.css(
            'main .c-headline a.c-button--brand[title="Apply now"]::attr(href)'
        ).getall()
        if (value := optional_text(raw)) and is_supported_apply_url(value)
    }
    apply_url = next(iter(apply_urls)) if len(apply_urls) == 1 else None
    ats_kind, ats_job_id = extract_ats_identity(apply_url)
    if (
        len(description_sections) != 1
        or set(requirement_nodes) != EXPECTED_REQUIREMENT_KEYS
        or not description
        or not apply_url
        or not ats_kind
        or not ats_job_id
    ):
        raise IsolutionsParseError("isolutions detail page contains an incomplete vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "apply_url": apply_url,
        "description": description,
        "ats_kind": ats_kind,
        "ats_job_id": ats_job_id,
        "ats_url": ats_job_url(ats_kind, ats_job_id),
    }


def parse_personio_html(
    page_html: str,
    *,
    expected_job_id: str,
    expected_title: str,
    expected_locations: list[str],
) -> dict[str, Any]:
    page = Selector(page_html)
    postings: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
            postings.append(payload)
    if len(postings) != 1:
        raise IsolutionsParseError("isolutions Personio page is missing JobPosting data")
    posting = postings[0]
    identifier = posting.get("identifier")
    organization = posting.get("hiringOrganization")
    job_locations = posting.get("jobLocation")
    employment_types = posting.get("employmentType")
    identifier_value = identifier.get("value") if isinstance(identifier, dict) else None
    organization_name = organization.get("name") if isinstance(organization, dict) else None
    location_regions: set[str] = set()
    countries: set[str] = set()
    if isinstance(job_locations, (dict, list)):
        for item in job_locations if isinstance(job_locations, list) else [job_locations]:
            address = item.get("address") if isinstance(item, dict) else None
            if isinstance(address, dict):
                region = optional_text(address.get("addressRegion"))
                country = optional_text(address.get("addressCountry"))
                if region:
                    location_regions.add(normalize_location_region(region))
                if country:
                    countries.add(country)
    posted_at = optional_text(posting.get("datePosted"))
    employment_type = normalize_employment_type(employment_types)
    if (
        title_fingerprint(posting.get("title")) != title_fingerprint(expected_title)
        or not optional_text(identifier_value)
        or not str(identifier_value).startswith(f"{expected_job_id}-")
        or comparable_text(organization_name) != "isolutions"
        or location_regions != set(expected_locations)
        or countries != {"CH"}
        or not posted_at
        or DATE_PATTERN.fullmatch(posted_at) is None
        or not employment_type
    ):
        raise IsolutionsParseError("isolutions Personio JobPosting data is inconsistent")
    return {
        "job_id": expected_job_id,
        "posted_at": posted_at,
        "employment_type": employment_type,
        "locations": sorted(location_regions),
    }


def parse_breezy_html(
    page_html: str,
    *,
    expected_job_id: str,
    expected_title: str,
) -> dict[str, Any]:
    posting = single_job_posting(page_html, provider="Breezy")
    organization = posting.get("hiringOrganization")
    organization_name = organization.get("name") if isinstance(organization, dict) else None
    job_locations = posting.get("jobLocation")
    locations = job_locations if isinstance(job_locations, list) else [job_locations]
    countries = {
        country
        for item in locations
        if isinstance(item, dict)
        and isinstance((address := item.get("address")), dict)
        and (country := optional_text(address.get("addressCountry")))
    }
    posted_at = optional_text(posting.get("datePosted"))
    employment_type = normalize_employment_type(posting.get("employmentType"))
    if (
        set(title_fingerprint(posting.get("title"))) != set(title_fingerprint(expected_title))
        or comparable_text(organization_name) != "isolutions"
        or countries != {"CH"}
        or not posted_at
        or DATE_PATTERN.fullmatch(posted_at) is None
        or not employment_type
    ):
        raise IsolutionsParseError("isolutions Breezy JobPosting data is inconsistent")
    return {
        "job_id": expected_job_id,
        "posted_at": posted_at,
        "employment_type": employment_type,
    }


def single_job_posting(page_html: str, *, provider: str) -> dict[str, Any]:
    page = Selector(page_html)
    postings: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "JobPosting":
            postings.append(payload)
    if len(postings) != 1:
        raise IsolutionsParseError(
            f"isolutions {provider} page is missing JobPosting data"
        )
    return postings[0]


def parse_filter_options(selector: Any, *, group_name: str) -> dict[str, str]:
    matching: list[dict[str, str]] = []
    for fieldset in selector.css("form.c-filter fieldset.js-multi-filter"):
        names = unique_selector_texts(fieldset, ".c-select__value")
        if names != {group_name}:
            continue
        options: dict[str, str] = {}
        for node in fieldset.css(".c-select__option"):
            toggle = optional_text(node.attrib.get("data-toggle"))
            match = re.fullmatch(r"\.filter-(\d+)", toggle or "")
            value = html_to_text(node.get())
            if not match or not value or match.group(1) in options:
                return {}
            options[match.group(1)] = value
        matching.append(options)
    return matching[0] if len(matching) == 1 else {}


def validate_page_identity(page: Selector, *, expected_url: str) -> None:
    languages = unique_attribute_values(page, "html", "lang")
    og_urls = unique_attribute_values(page, 'meta[property="og:url"]', "content")
    start_urls = unique_attribute_values(page, 'meta[name="msapplication-starturl"]', "content")
    alternates = {
        value
        for node in page.css('link[rel="alternate"]')
        if comparable_text(node.attrib.get("hreflang")) == "en-us"
        and (value := optional_text(node.attrib.get("href")))
    }
    if (
        languages != {EXPECTED_LANGUAGE}
        or len(og_urls) != 1
        or not same_url(next(iter(og_urls)), expected_url)
        or len(start_urls) != 1
        or not same_url(next(iter(start_urls)), expected_url)
        or len(alternates) > 1
        or (bool(alternates) and not same_url(next(iter(alternates)), expected_url))
    ):
        raise IsolutionsParseError("isolutions page has an unexpected identity")


def validate_organization_schema(page: Selector) -> None:
    organizations: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("@type") == "Organization":
            organizations.append(payload)
    if len(organizations) != 1:
        raise IsolutionsParseError("isolutions page is missing its organization identity")
    organization = organizations[0]
    contacts = organization.get("contactPoint")
    telephone = None
    if isinstance(contacts, list) and len(contacts) == 1 and isinstance(contacts[0], dict):
        telephone = optional_text(contacts[0].get("telephone"))
    if (
        not same_url(organization.get("url"), "https://www.isolutions.ch/en/")
        or optional_text(organization.get("logo"))
        != "https://www.isolutions.ch/media/bwpp3qmx/power_gradient.svg"
        or telephone != "0041 31 560 88 88"
    ):
        raise IsolutionsParseError("isolutions page has an invalid organization identity")


def validate_swiss_footer(page: Selector) -> None:
    footers = page.css(".c-footer")
    footer_text = html_to_text(footers[0].get()) if len(footers) == 1 else None
    if not footer_text or not all(part in footer_text for part in EXPECTED_FOOTER_PARTS):
        raise IsolutionsParseError("isolutions page is missing its Swiss office identity")


def job_description_section_id(page: Selector) -> str | None:
    links = page.css("main .c-headline__text-container .c-link__group a")
    ids = {
        match.group(1)
        for node in links
        if comparable_text(node.attrib.get("title")) == "job description"
        and (match := MODULE_FRAGMENT_PATTERN.fullmatch(optional_text(node.attrib.get("href")) or ""))
    }
    if len(ids) == 1:
        return next(iter(ids))
    if links:
        first_href = optional_text(links[0].attrib.get("href")) or ""
        first_match = MODULE_FRAGMENT_PATTERN.fullmatch(first_href)
        if first_match:
            return first_match.group(1)
    return None


def catalog_fragment_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    fragment = urlsplit(text).fragment
    return fragment if fragment == EXPECTED_CATALOG_ID else None


def split_locations(value: Any) -> list[str]:
    text = optional_text(value)
    if not text:
        return []
    values = [optional_text(item) for item in text.split(",")]
    return [item for item in values if item]


def normalize_employment_type(value: Any) -> str | None:
    values = value if isinstance(value, list) else [value]
    normalized = {
        optional_text(item)
        for item in values
        if optional_text(item) in {"FULL_TIME", "PART_TIME"}
    }
    if normalized == {"FULL_TIME"}:
        return "Full-time"
    if normalized == {"PART_TIME"}:
        return "Part-time"
    if normalized == {"FULL_TIME", "PART_TIME"}:
        return "Full-time / Part-time"
    return None


def normalize_location_region(value: str) -> str:
    return {"Basel-Stadt": "Basel"}.get(value, value)


def requirement_heading_key(value: Any) -> str | None:
    heading = comparable_text(value).rstrip(":")
    if heading == "this is what you get up for in the morning":
        return "responsibilities"
    if heading.startswith("we would like you to"):
        return "requirements"
    return None


def extract_job_id(value: Any, *, expected_host: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != expected_host
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def extract_personio_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = PERSONIO_PATH_PATTERN.fullmatch(parts.path)
    return match.group(1) if match else None


def is_personio_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    match = PERSONIO_PATH_PATTERN.fullmatch(parts.path)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "isolutions.jobs.personio.com"
        and match is not None
        and parts.fragment in {"", "apply"}
    )


def extract_breezy_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = re.fullmatch(r"/p/([a-f0-9]{14})-[a-z0-9-]+(?:/apply)?/?", parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "isolutions.breezy.hr"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return match.group(1)


def is_supported_apply_url(value: Any) -> bool:
    return is_personio_apply_url(value) or extract_breezy_job_id(value) is not None


def extract_ats_identity(value: Any) -> tuple[str | None, str | None]:
    personio_id = extract_personio_job_id(value)
    if personio_id and is_personio_apply_url(value):
        return "personio", personio_id
    breezy_id = extract_breezy_job_id(value)
    if breezy_id:
        return "breezy", breezy_id
    return None, None


def ats_job_url(kind: str, job_id: str) -> str:
    if kind == "personio":
        return f"https://isolutions.jobs.personio.com/job/{job_id}"
    if kind == "breezy":
        return f"https://isolutions.breezy.hr/p/{job_id}"
    raise ValueError(f"Unsupported isolutions ATS: {kind}")


def title_fingerprint(value: Any) -> tuple[str, ...]:
    text = optional_text(value)
    return tuple(re.findall(r"[^\W_]+", (text or "").casefold(), flags=re.UNICODE))


def compatible_title(value: Any, expected: Any) -> bool:
    actual_tokens = title_fingerprint(value)
    expected_tokens = title_fingerprint(expected)
    return actual_tokens == expected_tokens or actual_tokens == (
        *expected_tokens,
        "m",
        "f",
        "d",
    )


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
    )


def deduplicate_isolutions_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def unique_attribute_values(selector: Any, css: str, attribute: str) -> set[str]:
    return {
        value
        for node in selector.css(css)
        if (value := optional_text(node.attrib.get(attribute)))
    }


def unique_selector_texts(selector: Any, css: str) -> set[str]:
    return {value for node in selector.css(css) if (value := html_to_text(node.get()))}


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|strong|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    normalized = optional_multiline_text(html.unescape(text).replace("\xa0", " "))
    return re.sub(r"(?m)(^- .*)\n\n(?=- )", r"\1\n", normalized) if normalized else None


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


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
