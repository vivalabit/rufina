from __future__ import annotations

import re
from collections.abc import Iterable
from math import ceil
from typing import Any
from urllib.parse import quote_plus, unquote, urlsplit

import httpx

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

SCHURTER_CAREERS_URL = "https://www.schurter.com/de/karriere/offene-stellen?country=CH"
SCHURTER_JOBS_API_URL = "https://www.schurter.com/api/website/v1/jobs"
SCHURTER_COMPANY = "SCHURTER AG"
SCHURTER_COUNTRY = "CH"
SCHURTER_LOCALE = "de"
SCHURTER_APPLY_EMAIL = "jobapplication.ch@schurter.com"
SCHURTER_PAGE_SIZE = 9
SCHURTER_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
CONTENTFUL_SPACE_ID = "k3bfto4ed09w"
CONTENTFUL_ENVIRONMENT_ID = "master"
JOB_CONTENT_TYPE_ID = "pageJob"
JOB_METADATA_CONTENT_TYPE_ID = "pageJobsCHMetadata"
PARENT_CONTENT_TYPE_ID = "bh-page"
PARENT_SLUG = "karriere/offene-stellen"
PARENT_TITLE = "Offene Stellen bei SCHURTER"
GLOBAL_WEBSITE_TAG = "website_GLOBAL"
JOB_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CONTENTFUL_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{20,32}$")
WORKLOAD_PATTERN = re.compile(r"\b(\d{1,3})(?:\s*[–-]\s*(\d{1,3}))?\s*%")


class SchurterSwitzerlandParseError(DirectCompanyRequestError):
    pass


class SchurterSwitzerlandJobsParser:
    """Collect SCHURTER's complete official Switzerland-filtered job catalog."""

    parser_id = "schurter_switzerland"

    def __init__(
        self,
        *,
        base_url: str = SCHURTER_CAREERS_URL,
        api_url: str = SCHURTER_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 1_000,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**SCHURTER_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                countries = self.fetch_country_filters(client)
                records, pages = self.collect_records(client)
        except SchurterSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("SCHURTER Switzerland vacancy request failed") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("SCHURTER Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_schurter_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} SCHURTER Switzerland vacancies across "
                f"{pages} API page{'s' if pages != 1 else ''} from a verified "
                f"{len(countries) - 1}-country catalog"
            ),
        )

    def fetch_country_filters(self, client: httpx.Client) -> list[str]:
        response = client.get(
            f"{self.api_url}/filters",
            params={"locale": SCHURTER_LOCALE, "isPreview": "false"},
        )
        response.raise_for_status()
        return parse_country_filters(response.json())

    def collect_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int]:
        records: list[dict[str, Any]] = []
        expected_total: int | None = None
        pages = 1
        seen_ids: set[str] = set()
        seen_slugs: set[str] = set()

        page = 1
        while page <= pages:
            response = client.get(
                f"{self.api_url}/all",
                params={
                    "locale": SCHURTER_LOCALE,
                    "filters": f"country={SCHURTER_COUNTRY};page={page}",
                    "isPreview": "false",
                },
            )
            response.raise_for_status()
            payload = response.json()
            total, values = parse_catalog_page(payload)
            if expected_total is None:
                expected_total = total
                if total > self.max_jobs:
                    raise SchurterSwitzerlandParseError(
                        f"SCHURTER exposes {total} Swiss jobs, above the configured "
                        f"limit of {self.max_jobs}"
                    )
                pages = max(1, ceil(total / SCHURTER_PAGE_SIZE))
            elif total != expected_total:
                raise SchurterSwitzerlandParseError(
                    "SCHURTER jobs API changed its total during pagination"
                )

            expected_page_size = min(
                SCHURTER_PAGE_SIZE,
                max(0, (expected_total or 0) - len(records)),
            )
            if len(values) != expected_page_size:
                raise SchurterSwitzerlandParseError("SCHURTER jobs API returned an incomplete page")
            for value in values:
                record = parse_catalog_record(value, catalog_index=len(records))
                job_id = record["id"]
                slug = record["slug"]
                if job_id in seen_ids or slug in seen_slugs:
                    raise SchurterSwitzerlandParseError(
                        "SCHURTER jobs API returned duplicate vacancies"
                    )
                seen_ids.add(job_id)
                seen_slugs.add(slug)
                records.append(record)
            page += 1

        if expected_total is None or len(records) != expected_total:
            raise SchurterSwitzerlandParseError(
                "SCHURTER jobs API total does not match its catalog"
            )
        return records, pages


def parse_country_filters(value: Any) -> list[str]:
    if not isinstance(value, dict) or set(value) != {"values"}:
        raise SchurterSwitzerlandParseError("SCHURTER jobs API returned malformed country filters")
    values = value.get("values")
    if (
        not isinstance(values, list)
        or not values
        or values[0] != "All"
        or SCHURTER_COUNTRY not in values
        or len(values) != len(set(values))
        or any(
            not isinstance(country, str)
            or (country != "All" and not re.fullmatch(r"[A-Z]{2}", country))
            for country in values
        )
    ):
        raise SchurterSwitzerlandParseError("SCHURTER jobs API returned malformed country filters")
    return values


def parse_catalog_page(value: Any) -> tuple[int, list[dict[str, Any]]]:
    if not isinstance(value, dict) or set(value) != {"total", "data"}:
        raise SchurterSwitzerlandParseError("SCHURTER jobs API returned a malformed catalog page")
    total = value.get("total")
    data = value.get("data")
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or not isinstance(data, list)
        or any(not isinstance(record, dict) for record in data)
    ):
        raise SchurterSwitzerlandParseError("SCHURTER jobs API returned a malformed catalog page")
    return total, data


def parse_catalog_record(value: dict[str, Any], *, catalog_index: int) -> dict[str, Any]:
    system = value.get("sys")
    fields = value.get("fields")
    metadata = value.get("metadata")
    if not isinstance(system, dict) or not isinstance(fields, dict):
        raise SchurterSwitzerlandParseError("SCHURTER jobs API returned a malformed vacancy")

    job_id = optional_text(system.get("id"))
    created_at = optional_text(system.get("createdAt"))
    updated_at = optional_text(system.get("updatedAt"))
    title = optional_text(fields.get("title"))
    slug = optional_text(fields.get("slug"))
    country = optional_text(fields.get("selectCountryISO"))
    subtitle = optional_text(fields.get("subtitle"))
    contact_email = optional_text(fields.get("contactMail"))
    parent = fields.get("parentPage")
    page_metadata = fields.get("pageMetadata")
    if (
        not job_id
        or not CONTENTFUL_ID_PATTERN.fullmatch(job_id)
        or not created_at
        or not updated_at
        or not valid_contentful_system(system, JOB_CONTENT_TYPE_ID)
        or not valid_global_tag(metadata)
        or not title
        or not slug
        or not JOB_SLUG_PATTERN.fullmatch(slug)
        or country != SCHURTER_COUNTRY
        or contact_email != SCHURTER_APPLY_EMAIL
        or not valid_parent_page(parent)
        or not valid_page_metadata(page_metadata)
    ):
        raise SchurterSwitzerlandParseError(
            "SCHURTER jobs API returned an incomplete or non-Swiss vacancy"
        )

    description = compose_description(fields)
    address = contentful_to_text(fields.get("address"))
    if not description or len(description) < 200 or not address or SCHURTER_COMPANY not in address:
        raise SchurterSwitzerlandParseError(
            "SCHURTER jobs API returned an incomplete vacancy description"
        )

    metadata_fields = swiss_metadata_fields(fields.get("jobsCHMetadata"), title=title)
    workload = workload_from_metadata(metadata_fields) or workload_from_title(title)
    public_url = f"https://www.schurter.com/de/jobs/{slug}"
    return {
        "id": job_id,
        "slug": slug,
        "title": title,
        "company": SCHURTER_COMPANY,
        "country": country,
        "location": "Switzerland",
        "subtitle": subtitle,
        "workload": workload,
        "url": public_url,
        "apply_url": application_email_url(title, public_url=public_url),
        "posted_at": created_at,
        "updated_at": updated_at,
        "description": description,
        "catalog_index": catalog_index,
        "contact_email": contact_email,
        "jobs_ch_metadata": metadata_fields,
        "api_record": dict(value),
    }


def valid_contentful_system(value: Any, content_type_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    space_id = nested_value(value, "space", "sys", "id")
    environment_id = nested_value(value, "environment", "sys", "id")
    actual_content_type = nested_value(value, "contentType", "sys", "id")
    return (
        value.get("type") == "Entry"
        and space_id == CONTENTFUL_SPACE_ID
        and environment_id == CONTENTFUL_ENVIRONMENT_ID
        and actual_content_type == content_type_id
        and value.get("locale") == SCHURTER_LOCALE
    )


def valid_global_tag(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    tags = value.get("tags")
    if not isinstance(tags, list):
        return False
    tag_ids = {
        optional_text(nested_value(tag, "sys", "id")) for tag in tags if isinstance(tag, dict)
    }
    return GLOBAL_WEBSITE_TAG in tag_ids


def valid_parent_page(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    fields = value.get("fields")
    system = value.get("sys")
    return (
        valid_contentful_system(system, PARENT_CONTENT_TYPE_ID)
        and isinstance(fields, dict)
        and optional_text(fields.get("title")) in {PARENT_TITLE, "Offene Stellen"}
        and optional_text(fields.get("slug")) in {PARENT_SLUG, "ueber-uns/karriere/offene-stellen"}
    )


def valid_page_metadata(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    fields = value.get("fields")
    if not isinstance(fields, dict):
        return False
    return (
        bool(optional_text(fields.get("title")))
        and fields.get("noIndex") is False
        and fields.get("noFollow") is False
    )


def comparable_job_title(value: Any) -> str:
    # The Swiss feed localizes only the gender suffix on some otherwise identical titles.
    text = optional_text(value) or ""
    return re.sub(r"\((?:w|f)/m/d\)", "(m/w/d)", text, flags=re.IGNORECASE).casefold()


def swiss_metadata_fields(value: Any, *, title: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise SchurterSwitzerlandParseError("SCHURTER vacancy contains malformed Swiss metadata")
    system = value.get("sys")
    fields = value.get("fields")
    if (
        not valid_contentful_system(system, JOB_METADATA_CONTENT_TYPE_ID)
        or not isinstance(fields, dict)
        or comparable_job_title(fields.get("title")) != comparable_job_title(title)
    ):
        raise SchurterSwitzerlandParseError("SCHURTER vacancy contains malformed Swiss metadata")
    return dict(fields)


def workload_from_metadata(value: dict[str, Any]) -> str | None:
    if not value:
        return None
    minimum = value.get("job_percentage_from")
    maximum = value.get("job_percentage_to")
    if (
        isinstance(minimum, bool)
        or isinstance(maximum, bool)
        or not isinstance(minimum, int)
        or not isinstance(maximum, int)
        or not 1 <= minimum <= maximum <= 100
    ):
        raise SchurterSwitzerlandParseError("SCHURTER vacancy contains an invalid workload")
    return f"{minimum}%" if minimum == maximum else f"{minimum}–{maximum}%"


def workload_from_title(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = WORKLOAD_PATTERN.search(text)
    if not match:
        return None
    minimum = int(match.group(1))
    maximum = int(match.group(2) or minimum)
    if not 1 <= minimum <= maximum <= 100:
        return None
    return f"{minimum}%" if minimum == maximum else f"{minimum}–{maximum}%"


def compose_description(fields: dict[str, Any]) -> str | None:
    parts: list[str] = []
    subtitle = optional_text(fields.get("subtitle"))
    if subtitle:
        parts.append(subtitle)

    sections = (
        (None, "positionInformation"),
        ("challengesTitle", "challenges"),
        ("qualificationTitle", "qualification"),
        ("offerTitle", "offer"),
        (None, "comment"),
        (None, "companyProfile"),
        ("contactTitle", "motivationAndContact"),
        ("addressTitle", "address"),
    )
    for title_field, content_field in sections:
        content = contentful_to_text(fields.get(content_field))
        if not content:
            continue
        heading = optional_text(fields.get(title_field)) if title_field else None
        parts.append(f"{heading}\n{content}" if heading else content)
    return optional_multiline_text("\n\n".join(parts))


def contentful_to_text(value: Any) -> str | None:
    if not isinstance(value, dict) or value.get("nodeType") != "document":
        return None
    content = value.get("content")
    if not isinstance(content, list):
        return None
    rendered = "\n".join(render_contentful_node(node) for node in content)
    return optional_multiline_text(rendered)


def render_contentful_node(value: Any, *, list_item: bool = False) -> str:
    if not isinstance(value, dict):
        return ""
    node_type = value.get("nodeType")
    if node_type == "text":
        return str(value.get("value") or "")
    children = value.get("content")
    if not isinstance(children, list):
        return ""
    if node_type in {"unordered-list", "ordered-list"}:
        return "\n".join(render_contentful_node(child, list_item=True) for child in children)
    rendered = "".join(render_contentful_node(child) for child in children)
    if node_type == "list-item" or list_item:
        return f"- {optional_text(rendered) or ''}"
    return rendered


def application_email_url(title: str, *, public_url: str) -> str:
    subject = quote_plus(f"Bewerbung: {title}")
    body = quote_plus(f"Bewerbung: {title} {public_url}")
    return f"mailto:{SCHURTER_APPLY_EMAIL}?subject={subject}&body={body}"


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path).rstrip("/")
    prefix = "/de/jobs/"
    slug = path.removeprefix(prefix) if path.startswith(prefix) else ""
    if (
        parts.scheme != "https"
        or parts.netloc.casefold().removeprefix("www.") != "schurter.com"
        or not JOB_SLUG_PATTERN.fullmatch(slug)
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://www.schurter.com{prefix}{slug}"


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    title = optional_text(record.get("title"))
    return ParsedJob(
        source="schurter_switzerland",
        title=title,
        company=SCHURTER_COMPANY,
        location=optional_text(record.get("location")),
        url=canonical_job_url(record.get("url")),
        apply_url=optional_text(record.get("apply_url")),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=optional_text(record.get("workload")),
        seniority="Senior" if "senior" in comparable_text(title).split() else None,
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def deduplicate_schurter_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def nested_value(value: Any, *path: str) -> Any:
    current = value
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


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
