from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from xml.etree import ElementTree

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AMAG_GROUP_JOBS_URL = "https://jobs.amag-group.ch/"
AMAG_GROUP_FEED_URL = "https://jobs.amag-group.ch/rss_generator-rss0.php?unit=amag&lang=de"
AMAG_HEADERS = {
    "Accept": "application/atom+xml,application/xml;q=0.9,text/html;q=0.8,*/*;q=0.7",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
EXPECTED_FEED_TITLE = "AMAG Group - Jobs & Karriere"
EXPECTED_COMPANY = "AMAG Group"
OFFICIAL_HOSTS = {"jobs.amag-group.ch", "jobs.amag.ch"}
COUNTRY_NAMES = {"CH": "Switzerland", "LI": "Liechtenstein"}
JOB_PATH_PATTERN = re.compile(r"^/([^/]+)-de-([jf])(\d+)\.html$")
MAX_FEED_BYTES = 5_000_000


class AmagGroupParseError(DirectCompanyRequestError):
    pass


class AmagGroupJobsParser:
    """Collect the complete official AMAG Group Rexx catalog."""

    parser_id = "amag_group"

    def __init__(
        self,
        *,
        base_url: str = AMAG_GROUP_JOBS_URL,
        feed_url: str = AMAG_GROUP_FEED_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 2000,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.feed_url = feed_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(20, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**AMAG_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.feed_url)
                response.raise_for_status()
                records = parse_catalog_atom(
                    response.content,
                    base_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except AmagGroupParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("AMAG Group vacancy request failed") from exc
        except (ElementTree.ParseError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("AMAG Group vacancy parsing failed") from exc

        jobs = [normalize_job(record, base_url=self.base_url) for record in records]
        if request.deduplicate:
            jobs = deduplicate_amag_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} AMAG Group vacancies from the complete official catalog"
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
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                    base_url=self.base_url,
                )
            except (httpx.HTTPError, AmagGroupParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_catalog_atom(
    content: bytes,
    *,
    base_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if (
        not content
        or len(content) > MAX_FEED_BYTES
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise AmagGroupParseError("AMAG Group catalog Atom feed is unsafe")
    try:
        root = ElementTree.fromstring(content)
    except ElementTree.ParseError as exc:
        raise AmagGroupParseError("AMAG Group catalog Atom feed is malformed") from exc

    namespace = f"{{{ATOM_NAMESPACE}}}"
    if root.tag != f"{namespace}feed":
        raise AmagGroupParseError("AMAG Group catalog has an unexpected structure")
    feed_titles = root.findall(f"{namespace}title")
    feed_links = root.findall(f"{namespace}link")
    feed_ids = root.findall(f"{namespace}id")
    if (
        len(feed_titles) != 1
        or optional_text(feed_titles[0].text) != EXPECTED_FEED_TITLE
        or len(feed_links) != 1
        or normalize_feed_home(feed_links[0].attrib.get("href"), base_url) is None
        or len(feed_ids) != 1
        or normalize_feed_home(feed_ids[0].text, base_url) is None
    ):
        raise AmagGroupParseError("AMAG Group catalog metadata is unexpected")

    entries = root.findall(f"{namespace}entry")
    if not entries or len(entries) > max_jobs:
        raise AmagGroupParseError("AMAG Group catalog size is unexpected")

    expected_tags = {
        f"{namespace}title",
        f"{namespace}category",
        f"{namespace}link",
        f"{namespace}id",
        f"{namespace}summary",
        f"{namespace}updated",
    }
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for entry in entries:
        fields = {child.tag: child for child in entry}
        if len(entry) != len(expected_tags) or set(fields) != expected_tags:
            raise AmagGroupParseError("AMAG Group catalog contains a malformed vacancy")
        title = optional_text(fields[f"{namespace}title"].text)
        category_element = fields[f"{namespace}category"]
        category = optional_text(category_element.attrib.get("term"))
        link_element = fields[f"{namespace}link"]
        feed_url = normalize_job_url(
            link_element.attrib.get("href"),
            base_url=base_url,
            kind="j",
        )
        identity_url = normalize_job_url(
            fields[f"{namespace}id"].text,
            base_url=base_url,
            kind="j",
        )
        summary_element = fields[f"{namespace}summary"]
        summary = optional_multiline_text(summary_element.text)
        posted_at = normalize_date(fields[f"{namespace}updated"].text)
        job_id = extract_job_id(feed_url, kind="j")
        if (
            not title
            or not feed_url
            or identity_url != feed_url
            or not summary
            or not posted_at
            or not job_id
            or link_element.attrib.keys() != {"href"}
            or category_element.attrib.keys() != {"term"}
            or summary_element.attrib != {"type": "html"}
            or job_id in seen_ids
        ):
            raise AmagGroupParseError(
                "AMAG Group catalog contains an incomplete or duplicate vacancy"
            )
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "category": category,
                "url": feed_url,
                "posted_at": posted_at,
                "summary": summary,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
    base_url: str,
) -> dict[str, Any]:
    expected_job_id = optional_text(expected_record.get("id"))
    expected_url = normalize_job_url(expected_record.get("url"), base_url=base_url, kind="j")
    if (
        not expected_job_id
        or not expected_url
        or normalize_job_url(page_url, base_url=base_url, kind="j") != expected_url
    ):
        raise AmagGroupParseError("AMAG Group detail page returned a different vacancy")

    page = Selector(page_html)
    schemas = [
        candidate
        for raw in page.css('script[type="application/ld+json"]::text').getall()
        for candidate in parse_json_objects(raw)
        if candidate.get("@type") == "JobPosting"
    ]
    if len(schemas) != 1:
        raise AmagGroupParseError("AMAG Group detail page is missing its JobPosting data")
    schema = schemas[0]
    canonical = normalize_job_url(
        page.css('link[rel="canonical"]::attr(href)').get(),
        base_url=base_url,
        kind="j",
    )
    title = optional_text(schema.get("title"))
    company = optional_text(nested_value(schema, "hiringOrganization", "name"))
    posted_at = normalize_date(schema.get("datePosted"))
    valid_through = normalize_date(schema.get("validThrough"))
    employment_type = optional_text(schema.get("employmentType"))
    description = html_to_text(schema.get("description"))
    locations = normalize_schema_locations(schema.get("jobLocation"))
    expected_apply_url = expected_url.replace(
        f"-de-j{expected_job_id}.html",
        f"-de-f{expected_job_id}.html",
    )
    apply_urls = {
        normalized
        for value in page.css("#btn_online_application a::attr(href)").getall()
        if (
            normalized := normalize_job_url(
                value,
                base_url=base_url,
                kind="f",
            )
        )
    }
    if (
        canonical != expected_url
        or comparable_text(title) != comparable_text(expected_record.get("title"))
        or company != EXPECTED_COMPANY
        or posted_at != expected_record.get("posted_at")
        or not valid_through
        or not employment_type
        or not description
        or not locations
        or schema.get("directApply") is not True
        or apply_urls != {expected_apply_url}
    ):
        raise AmagGroupParseError(
            "AMAG Group detail page contains an incomplete or mismatched vacancy"
        )
    return {
        "id": expected_job_id,
        "title": title,
        "company": company,
        "locations": locations,
        "public_url": canonical,
        "apply_url": expected_apply_url,
        "posted_at": posted_at,
        "valid_through": valid_through,
        "employment_type": employment_type,
        "description": description,
        "schema": schema,
    }


def normalize_job(record: dict[str, Any], *, base_url: str) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(detail.get("public_url")) or normalize_job_url(
        record.get("url"), base_url=base_url, kind="j"
    )
    return ParsedJob(
        source="amag_group",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=EXPECTED_COMPANY,
        location=format_locations(detail.get("locations")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")) or optional_text(record.get("posted_at")),
        employment_type=normalize_employment_type(detail.get("employment_type")),
        description=(
            optional_multiline_text(detail.get("description"))
            or optional_multiline_text(record.get("summary"))
        ),
        raw=dict(record),
    )


def normalize_feed_home(value: Any, base_url: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    allowed_hosts = configured_hosts(expected.hostname)
    if (
        parts.scheme != "https"
        or parts.hostname not in allowed_hosts
        or parts.username is not None
        or parts.password is not None
        or parts.port != expected.port
        or parts.path != "/"
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), "/", "", ""))


def normalize_job_url(value: Any, *, base_url: str, kind: str) -> str | None:
    text = optional_text(value)
    if not text or kind not in {"j", "f"}:
        return None
    parts = urlsplit(text)
    expected = urlsplit(base_url)
    allowed_hosts = configured_hosts(expected.hostname)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.hostname not in allowed_hosts
        or parts.username is not None
        or parts.password is not None
        or parts.port != expected.port
        or not match
        or match.group(2) != kind
        or not match.group(3).isdigit()
    ):
        return None
    return urlunsplit(("https", expected.netloc.casefold(), parts.path, "", ""))


def configured_hosts(expected_host: str | None) -> set[str]:
    if not expected_host:
        return set()
    return OFFICIAL_HOSTS | {expected_host} if expected_host in OFFICIAL_HOSTS else {expected_host}


def extract_job_id(value: str | None, *, kind: str) -> str | None:
    if not value:
        return None
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(value).path)
    return match.group(3) if match and match.group(2) == kind else None


def normalize_schema_locations(value: Any) -> list[dict[str, str]]:
    raw_locations = value if isinstance(value, list) else [value]
    locations: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for location in raw_locations:
        if not isinstance(location, dict):
            return []
        address = location.get("address")
        if not isinstance(address, dict):
            return []
        country = optional_text(address.get("addressCountry"))
        city = optional_text(address.get("addressLocality"))
        if country not in COUNTRY_NAMES or not city:
            return []
        key = (city.casefold(), country)
        if key in seen:
            return []
        seen.add(key)
        locations.append({"city": city, "country": country})
    return locations


def format_locations(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    locations: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            return None
        city = optional_text(item.get("city"))
        country = optional_text(item.get("country"))
        if not city or country not in COUNTRY_NAMES:
            return None
        locations.append(f"{city}, {COUNTRY_NAMES[country]}")
    return "; ".join(locations) or None


def normalize_employment_type(value: Any) -> str | None:
    mapping = {
        "FULL_TIME": "Full-time",
        "PART_TIME": "Part-time",
        "CONTRACTOR": "Contract",
        "INTERN": "Internship",
    }
    text = optional_text(value)
    return mapping.get(text or "", text)


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def parse_json_objects(value: Any) -> Iterator[dict[str, Any]]:
    try:
        payload = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return
    yield from walk_json(payload)


def walk_json(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def nested_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = re.sub(r"(?is)<(script|style|picture|figure)\b[^>]*>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li\b[^>]*>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol|section)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text))


def comparable_text(value: Any) -> str:
    text = optional_text(value)
    return re.sub(r"[^a-z0-9]+", "", text.casefold() if text else "")


def deduplicate_amag_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line) or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value)).replace("\u00ad", "").replace("\u200b", "")
    normalized = re.sub(r"\s+", " ", text).strip()
    return normalized or None
