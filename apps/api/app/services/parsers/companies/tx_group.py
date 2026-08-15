from __future__ import annotations

import html
import re
import time
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

TX_GROUP_JOBS_BASE_URL = "https://jobs.tx.group/jobs"
TX_GROUP_JOBS_FEED_URL = "https://jobs.tx.group/jobs.json"
TX_GROUP_FEED_VERSION = "https://jsonfeed.org/version/1.1"
TX_GROUP_ALLOWED_ORGANIZATIONS = {
    "TX Group AG": "jobs.tx.group",
    "20 Minuten": "jobs.20minuten.ch",
    "Tamedia": "jobs.tamedia.ch",
}
TX_GROUP_ALLOWED_JOB_HOSTS = set(TX_GROUP_ALLOWED_ORGANIZATIONS.values())
TX_GROUP_HEADERS = {
    "Accept": "text/html,application/feed+json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,fr-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
JOB_PATH_PATTERN = re.compile(r"^(?:/fr)?/jobs/(\d+)-[a-z0-9][a-z0-9-]*$", re.IGNORECASE)
FEED_JOB_PATH_PATTERN = re.compile(r"^/jobs/(\d+)-[a-z0-9][a-z0-9-]*$", re.IGNORECASE)
CATALOG_COUNT_PATTERN = re.compile(
    r"<(?:h2|span)[^>]*>\s*(\d+)\s+(?:Jobs|Stellen|Postes)\b",
    re.IGNORECASE,
)


class TxGroupParseError(DirectCompanyRequestError):
    pass


class TxGroupJobsParser:
    """Collect the complete TX Group Teamtailor catalog from its official JSON Feed."""

    parser_id = "tx_group"

    def __init__(
        self,
        *,
        base_url: str = TX_GROUP_JOBS_BASE_URL,
        feed_url: str = TX_GROUP_JOBS_FEED_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 500,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.feed_url = feed_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=TX_GROUP_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, requests_fetched, catalog_passes = self.collect_records(client)
        except TxGroupParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("TX Group vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("TX Group vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_tx_group_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} TX Group vacancies from the complete official "
                f"Teamtailor JSON Feed, reconciled in {catalog_passes} catalog pass(es) "
                f"across {requests_fetched} requests"
            ),
        )

    def collect_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        requests_fetched = 0
        last_listing_ids: set[str] = set()
        last_feed_ids: set[str] = set()

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            cache_token = str(time.time_ns())
            listing_response = client.get(self.base_url, params={"_": cache_token})
            listing_response.raise_for_status()
            requests_fetched += 1
            listing_records = parse_listing_html(
                listing_response.text,
                page_url=str(listing_response.url),
                expected_url=self.base_url,
                max_jobs=self.max_jobs,
            )

            feed_response = client.get(
                self.feed_url,
                params={"_": cache_token},
                headers={"Referer": self.base_url, "Accept": "application/feed+json"},
            )
            feed_response.raise_for_status()
            requests_fetched += 1
            records = parse_feed_payload(
                feed_response.json(),
                page_url=str(feed_response.url),
                expected_url=self.feed_url,
                listing_records=listing_records,
                max_jobs=self.max_jobs,
                catalog_pass=catalog_pass,
            )

            last_listing_ids = set(listing_records)
            last_feed_ids = {str(record["job_id"]) for record in records}
            if last_listing_ids == last_feed_ids:
                return records, requests_fetched, catalog_pass

        raise TxGroupParseError(
            "TX Group HTML catalog and JSON Feed did not converge after "
            f"{self.max_catalog_passes} pass(es): "
            f"{len(last_listing_ids)} listing IDs versus {len(last_feed_ids)} feed IDs"
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> dict[str, dict[str, Any]]:
    validate_catalog_response_url(page_url, expected_url=expected_url)
    page = Selector(page_html)
    if selector_text(page, '[data-test="company-logo"]') != "TX Group AG":
        raise TxGroupParseError("TX Group catalog has an unexpected company identity")
    catalogs = page.css("#jobs_list_container")
    if len(catalogs) != 1:
        raise TxGroupParseError("TX Group catalog is missing its official jobs list")
    count_matches = CATALOG_COUNT_PATTERN.findall(page_html)
    if len(count_matches) != 1:
        raise TxGroupParseError("TX Group catalog is missing its declared job count")
    declared_count = int(count_matches[0])
    if declared_count > max_jobs:
        raise TxGroupParseError(
            f"TX Group exposes {declared_count} jobs, above the configured limit of {max_jobs}"
        )

    records: dict[str, dict[str, Any]] = {}
    links = catalogs[0].css("li a[href]")
    for link in links:
        title = selector_text(link)
        public_url = canonical_job_url(link.css("::attr(href)").get())
        job_id = extract_job_id(public_url)
        if not title or not public_url or not job_id:
            raise TxGroupParseError("TX Group catalog contains an incomplete vacancy")
        if job_id in records:
            raise TxGroupParseError("TX Group catalog contains duplicate vacancy IDs")
        records[job_id] = {
            "job_id": job_id,
            "title": title,
            "public_url": public_url,
        }

    if len(records) != declared_count:
        raise TxGroupParseError(
            f"TX Group catalog declared {declared_count} jobs but exposed {len(records)}"
        )
    return records


def parse_feed_payload(
    payload: Any,
    *,
    page_url: str,
    expected_url: str,
    listing_records: dict[str, dict[str, Any]],
    max_jobs: int,
    catalog_pass: int,
) -> list[dict[str, Any]]:
    validate_feed_response_url(page_url, expected_url=expected_url)
    if not isinstance(payload, dict):
        raise TxGroupParseError("TX Group JSON Feed response must be an object")
    items = payload.get("items")
    if (
        payload.get("version") != TX_GROUP_FEED_VERSION
        or payload.get("title") != "TX Group AG"
        or canonical_plain_url(payload.get("home_page_url"))
        != canonical_plain_url(TX_GROUP_JOBS_BASE_URL)
        or canonical_plain_url(payload.get("feed_url"))
        != canonical_plain_url(TX_GROUP_JOBS_FEED_URL)
        or not isinstance(items, list)
    ):
        raise TxGroupParseError("TX Group JSON Feed has unexpected metadata")
    if len(items) > max_jobs:
        raise TxGroupParseError(
            f"TX Group JSON Feed exposes {len(items)} jobs, above the configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        record = validate_feed_item(item, listing_records=listing_records)
        job_id = str(record["job_id"])
        if job_id in seen_ids:
            raise TxGroupParseError("TX Group JSON Feed contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        record["catalog_pass"] = catalog_pass
        record["total_available"] = len(items)
        records.append(record)
    return records


def validate_feed_item(
    item: Any,
    *,
    listing_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise TxGroupParseError("TX Group JSON Feed contains an invalid vacancy")
    schema = item.get("_jobposting")
    if not isinstance(schema, dict):
        raise TxGroupParseError("TX Group JSON Feed contains an incomplete vacancy")
    identifier = schema.get("identifier")
    organization = schema.get("hiringOrganization")
    locations = schema.get("jobLocation")
    feed_uuid = optional_text(item.get("id"))
    title = optional_text(item.get("title"))
    content_html = optional_text(item.get("content_html"))
    published_at = optional_text(item.get("date_published"))
    schema_title = optional_text(schema.get("title"))
    schema_description = optional_text(schema.get("description"))
    schema_date = optional_text(schema.get("datePosted"))
    if not isinstance(identifier, dict) or not isinstance(organization, dict):
        raise TxGroupParseError("TX Group JSON Feed contains an incomplete vacancy")
    job_id = optional_text(identifier.get("value"))
    organization_name = optional_text(organization.get("name"))
    expected_host = TX_GROUP_ALLOWED_ORGANIZATIONS.get(organization_name or "")
    listing = listing_records.get(job_id or "")
    feed_url = canonical_feed_job_url(item.get("url"))
    feed_url_id = extract_feed_job_id(feed_url)
    if (
        not valid_uuid(feed_uuid)
        or not job_id
        or not job_id.isdigit()
        or identifier.get("@type") != "PropertyValue"
        or optional_text(identifier.get("name")) != organization_name
        or not organization_name
        or not expected_host
        or organization.get("@type") != "Organization"
        or canonical_organization_url(organization.get("sameAs")) != f"https://{expected_host}"
        or schema.get("@type") != "JobPosting"
        or not title
        or comparable_text(title) != comparable_text(schema_title)
        or not content_html
        or content_html != schema_description
        or not published_at
        or published_at != schema_date
        or feed_url_id != job_id
        or (listing and comparable_text(listing.get("title")) != comparable_text(title))
        or (listing and urlsplit(str(listing.get("public_url"))).hostname != expected_host)
        or not valid_swiss_locations(locations)
    ):
        raise TxGroupParseError(
            "TX Group JSON Feed contains an incomplete, mismatched, or out-of-scope vacancy"
        )
    public_url = (
        str(listing["public_url"])
        if listing
        else urlunsplit(("https", expected_host, urlsplit(feed_url or "").path, "", ""))
    )
    return {
        "job_id": job_id,
        "feed_uuid": feed_uuid,
        "title": title,
        "company": organization_name,
        "location": extract_locations(locations),
        "public_url": public_url,
        "apply_url": application_url(public_url),
        "posted_at": published_at,
        "employment_type": optional_text(schema.get("employmentType")),
        "description": html_to_text(content_html),
        "listing": dict(listing or {}),
        "feed_item": dict(item),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    return ParsedJob(
        source="tx_group",
        title=optional_text(record.get("title")),
        company=optional_text(record.get("company")) or "TX Group AG",
        location=optional_text(record.get("location")),
        url=optional_text(record.get("public_url")),
        apply_url=optional_text(record.get("apply_url")),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=optional_text(record.get("employment_type")),
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def validate_catalog_response_url(value: Any, *, expected_url: str) -> None:
    if not matching_request_url(value, expected_url=expected_url):
        raise TxGroupParseError("TX Group catalog redirected unexpectedly")


def validate_feed_response_url(value: Any, *, expected_url: str) -> None:
    if not matching_request_url(value, expected_url=expected_url):
        raise TxGroupParseError("TX Group JSON Feed redirected unexpectedly")


def matching_request_url(value: Any, *, expected_url: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    expected = urlsplit(expected_url)
    return bool(
        parts.scheme == expected.scheme == "https"
        and parts.hostname == expected.hostname
        and parts.path.rstrip("/") == expected.path.rstrip("/")
        and {part.split("=", 1)[0] for part in parts.query.split("&") if part} <= {"_"}
        and not parts.fragment
    )


def canonical_plain_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
        return None
    return urlunsplit(("https", parts.hostname.casefold(), parts.path.rstrip("/"), "", ""))


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname not in TX_GROUP_ALLOWED_JOB_HOSTS
        or not JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", parts.hostname, parts.path, "", ""))


def canonical_feed_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "jobs.tx.group"
        or not FEED_JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.tx.group", parts.path, "", ""))


def extract_job_id(value: Any) -> str | None:
    url = canonical_job_url(value)
    match = JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def extract_feed_job_id(value: Any) -> str | None:
    url = canonical_feed_job_url(value)
    match = FEED_JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def canonical_organization_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname not in TX_GROUP_ALLOWED_JOB_HOSTS
        or parts.path.rstrip("/")
        or parts.query
        or parts.fragment
    ):
        return None
    return f"https://{parts.hostname}"


def application_url(public_url: str) -> str:
    return f"{public_url}/applications/new"


def valid_swiss_locations(value: Any) -> bool:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        return False
    for location in value:
        if not isinstance(location, dict):
            return False
        address = location.get("address")
        if (
            location.get("@type") != "Place"
            or not isinstance(address, dict)
            or address.get("@type") != "PostalAddress"
            or optional_text(address.get("addressCountry")) != "CH"
            or not optional_text(address.get("addressLocality"))
        ):
            return False
    return True


def extract_locations(value: Any) -> str | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    names = []
    for location in value:
        address = location.get("address") if isinstance(location, dict) else None
        if isinstance(address, dict):
            locality = optional_text(address.get("addressLocality"))
            if locality:
                names.append(locality)
    unique = list(dict.fromkeys(names))
    return "; ".join(unique) or None


def valid_uuid(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        return str(UUID(text)) == text.casefold()
    except ValueError:
        return False


def deduplicate_tx_group_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("job_id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(html.unescape(text)))


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    return optional_text(" ".join(selected[0].css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    normalized = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return normalized or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", html.unescape(str(value))).strip() or None
