from __future__ import annotations

import html
import re
import time
from collections.abc import Iterable, Sequence
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit
from uuid import UUID

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

BEARINGPOINT_JOBS_BASE_URL = (
    "https://www.bearingpoint.com/de-ch/karriere/stellenangebote/?country=CH"
)
BEARINGPOINT_JOBS_FEED_URL_DE = "https://bearingpointag.teamtailor.com/jobs.json"
BEARINGPOINT_JOBS_FEED_URL_EN = "https://bearingpointag.teamtailor.com/en/jobs.json"
BEARINGPOINT_FEED_VERSION = "https://jsonfeed.org/version/1.1"
BEARINGPOINT_TEAMTAILOR_ORIGIN = "https://bearingpointag.teamtailor.com"
BEARINGPOINT_HEADERS = {
    "Accept": "text/html,application/feed+json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
CATALOG_COUNT_PATTERN = re.compile(
    r"(\d+)\s+Stellen\s+verf(?:ü|&uuml;)gbar", re.IGNORECASE
)
PUBLIC_JOB_PATH = "/de-ch/karriere/stellenangebote/agebote/"
TEAMTAILOR_JOB_PATH_PATTERN = re.compile(
    r"^(?:/en)?/jobs/(\d+)-[a-z0-9][a-z0-9-]*$", re.IGNORECASE
)


class BearingpointSwitzerlandParseError(DirectCompanyRequestError):
    pass


class BearingpointSwitzerlandJobsParser:
    """Collect all Swiss BearingPoint jobs from the official catalog and feeds."""

    parser_id = "bearingpoint_switzerland"

    def __init__(
        self,
        *,
        base_url: str = BEARINGPOINT_JOBS_BASE_URL,
        feed_url_de: str = BEARINGPOINT_JOBS_FEED_URL_DE,
        feed_url_en: str = BEARINGPOINT_JOBS_FEED_URL_EN,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        max_catalog_passes: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.feed_urls = (feed_url_de, feed_url_en)
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=BEARINGPOINT_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, requests_fetched, catalog_passes = self.collect_records(client)
        except BearingpointSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError(
                "BearingPoint Switzerland vacancy request failed"
            ) from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError(
                "BearingPoint Switzerland vacancy parsing failed"
            ) from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_bearingpoint_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} BearingPoint Switzerland vacancies from the "
                f"complete official catalog and 2 Teamtailor locale feeds in "
                f"{catalog_passes} catalog pass(es) across {requests_fetched} requests"
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
            listing_url = httpx.URL(self.base_url).copy_merge_params(
                {"_": cache_token}
            )
            listing_response = client.get(listing_url)
            listing_response.raise_for_status()
            requests_fetched += 1
            listing_records = parse_listing_html(
                listing_response.text,
                page_url=str(listing_response.url),
                expected_url=self.base_url,
                max_jobs=self.max_jobs,
            )

            records: list[dict[str, Any]] = []
            seen_feed_ids: set[str] = set()
            for feed_url in self.feed_urls:
                request_url = httpx.URL(feed_url).copy_merge_params(
                    {"country": "Switzerland", "_": cache_token}
                )
                response = client.get(
                    request_url,
                    headers={"Referer": self.base_url, "Accept": "application/feed+json"},
                )
                response.raise_for_status()
                requests_fetched += 1
                locale_records = parse_feed_payload(
                    response.json(),
                    page_url=str(response.url),
                    expected_url=feed_url,
                    listing_records=listing_records,
                    max_jobs=self.max_jobs,
                    catalog_pass=catalog_pass,
                )
                for record in locale_records:
                    job_id = str(record["job_id"])
                    if job_id in seen_feed_ids:
                        raise BearingpointSwitzerlandParseError(
                            "BearingPoint locale feeds contain duplicate vacancy IDs"
                        )
                    seen_feed_ids.add(job_id)
                    records.append(record)

            if len(records) > self.max_jobs:
                raise BearingpointSwitzerlandParseError(
                    f"BearingPoint feeds expose {len(records)} jobs, above the "
                    f"configured limit of {self.max_jobs}"
                )
            last_listing_ids = set(listing_records)
            last_feed_ids = seen_feed_ids
            if last_listing_ids == last_feed_ids:
                total = len(records)
                for record in records:
                    record["total_available"] = total
                return records, requests_fetched, catalog_pass

        raise BearingpointSwitzerlandParseError(
            "BearingPoint HTML catalog and locale feeds did not converge after "
            f"{self.max_catalog_passes} pass(es): {len(last_listing_ids)} listing IDs "
            f"versus {len(last_feed_ids)} feed IDs"
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> dict[str, dict[str, Any]]:
    if not matching_catalog_url(page_url, expected_url=expected_url):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint catalog redirected unexpectedly"
        )
    page = Selector(page_html)
    if not page.css('a.logo[aria-label*="BearingPoint"]'):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint catalog has an unexpected company identity"
        )
    count_matches = CATALOG_COUNT_PATTERN.findall(page_html)
    if len(count_matches) != 1:
        raise BearingpointSwitzerlandParseError(
            "BearingPoint catalog is missing its declared job count"
        )
    declared_count = int(count_matches[0])
    if declared_count > max_jobs:
        raise BearingpointSwitzerlandParseError(
            f"BearingPoint exposes {declared_count} jobs, above the configured limit "
            f"of {max_jobs}"
        )

    records: dict[str, dict[str, Any]] = {}
    for card in page.css("div.jobs > a.panel.one-click[href]"):
        href = optional_text(card.css("::attr(href)").get())
        title = selector_text(card, ".job-title .panel-header")
        location = selector_text(card, ".job-info")
        job_id = public_job_id(href)
        if not job_id or not title or not location:
            raise BearingpointSwitzerlandParseError(
                "BearingPoint catalog contains an incomplete vacancy"
            )
        if job_id in records:
            raise BearingpointSwitzerlandParseError(
                "BearingPoint catalog contains duplicate vacancy IDs"
            )
        records[job_id] = {
            "job_id": job_id,
            "title": title,
            "location": location,
            "public_url": canonical_public_job_url(href, expected_url=expected_url),
        }

    if len(records) != declared_count:
        raise BearingpointSwitzerlandParseError(
            f"BearingPoint catalog declared {declared_count} jobs but exposed "
            f"{len(records)}"
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
    if not matching_feed_url(page_url, expected_url=expected_url):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed redirected unexpectedly"
        )
    if not isinstance(payload, dict):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed response must be an object"
        )
    expected_home_url = expected_url.removesuffix(".json")
    items = payload.get("items")
    if (
        payload.get("version") != BEARINGPOINT_FEED_VERSION
        or payload.get("title") != "BearingPoint AG"
        or canonical_plain_url(payload.get("home_page_url"))
        != canonical_plain_url(expected_home_url)
        or canonical_plain_url(payload.get("feed_url"))
        != canonical_plain_url(expected_url)
        or not isinstance(items, list)
    ):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed has unexpected metadata"
        )
    if len(items) > max_jobs:
        raise BearingpointSwitzerlandParseError(
            f"BearingPoint Teamtailor feed exposes {len(items)} jobs, above the "
            f"configured limit of {max_jobs}"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        record = validate_feed_item(item, listing_records=listing_records)
        job_id = str(record["job_id"])
        if job_id in seen_ids:
            raise BearingpointSwitzerlandParseError(
                "BearingPoint Teamtailor feed contains duplicate vacancy IDs"
            )
        seen_ids.add(job_id)
        record["catalog_pass"] = catalog_pass
        records.append(record)
    return records


def validate_feed_item(
    item: Any,
    *,
    listing_records: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed contains an invalid vacancy"
        )
    schema = item.get("_jobposting")
    if not isinstance(schema, dict):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed contains an incomplete vacancy"
        )
    identifier = schema.get("identifier")
    organization = schema.get("hiringOrganization")
    locations = schema.get("jobLocation")
    if not isinstance(identifier, dict) or not isinstance(organization, dict):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed contains an incomplete vacancy"
        )

    feed_uuid = optional_text(item.get("id"))
    title = optional_text(item.get("title"))
    content_html = optional_text(item.get("content_html"))
    published_at = optional_text(item.get("date_published"))
    job_id = optional_text(identifier.get("value"))
    listing_id = f"T{job_id}" if job_id else ""
    listing = listing_records.get(listing_id)
    feed_url = canonical_teamtailor_job_url(item.get("url"))
    if (
        not valid_uuid(feed_uuid)
        or not job_id
        or not job_id.isdigit()
        or identifier.get("@type") != "PropertyValue"
        or optional_text(identifier.get("name")) != "BearingPoint AG"
        or organization.get("@type") != "Organization"
        or optional_text(organization.get("name")) != "BearingPoint AG"
        or canonical_organization_url(organization.get("sameAs"))
        != BEARINGPOINT_TEAMTAILOR_ORIGIN
        or schema.get("@type") != "JobPosting"
        or not title
        or comparable_text(title) != comparable_text(schema.get("title"))
        or not content_html
        or content_html != optional_text(schema.get("description"))
        or not published_at
        or published_at != optional_text(schema.get("datePosted"))
        or extract_teamtailor_job_id(feed_url) != job_id
        or (listing and comparable_text(listing.get("title")) != comparable_text(title))
        or not valid_swiss_locations(locations)
        or (
            listing
            and comparable_text(listing.get("location"))
            != comparable_text(extract_locations(locations))
        )
    ):
        raise BearingpointSwitzerlandParseError(
            "BearingPoint Teamtailor feed contains an incomplete, mismatched, or "
            "out-of-scope vacancy"
        )
    return {
        "job_id": listing_id,
        "teamtailor_job_id": job_id,
        "feed_uuid": feed_uuid,
        "title": title,
        "company": "BearingPoint AG",
        "location": extract_locations(locations),
        "public_url": str(listing["public_url"]) if listing else None,
        "apply_url": application_url(feed_url),
        "posted_at": published_at,
        "employment_type": optional_text(schema.get("employmentType")),
        "description": html_to_text(content_html),
        "listing": dict(listing or {}),
        "feed_item": dict(item),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    return ParsedJob(
        source="bearingpoint_switzerland",
        title=optional_text(record.get("title")),
        company=optional_text(record.get("company")) or "BearingPoint AG",
        location=optional_text(record.get("location")),
        url=optional_text(record.get("public_url")),
        apply_url=optional_text(record.get("apply_url")),
        posted_at=optional_text(record.get("posted_at")),
        employment_type=optional_text(record.get("employment_type")),
        description=optional_multiline_text(record.get("description")),
        raw=dict(record),
    )


def matching_catalog_url(value: Any, *, expected_url: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    expected = urlsplit(expected_url)
    params = parse_qs(parts.query, keep_blank_values=True)
    return bool(
        parts.scheme == expected.scheme == "https"
        and parts.hostname == expected.hostname
        and parts.path.rstrip("/") == expected.path.rstrip("/")
        and params.get("country") == ["CH"]
        and set(params) <= {"country", "_"}
        and not parts.fragment
    )


def matching_feed_url(value: Any, *, expected_url: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    expected = urlsplit(expected_url)
    params = parse_qs(parts.query, keep_blank_values=True)
    return bool(
        parts.scheme == expected.scheme == "https"
        and parts.hostname == expected.hostname
        and parts.path.rstrip("/") == expected.path.rstrip("/")
        and params.get("country") == ["Switzerland"]
        and set(params) <= {"country", "_"}
        and not parts.fragment
    )


def public_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(urljoin("https://www.bearingpoint.com", text))
    params = parse_qs(parts.query, keep_blank_values=True)
    job_ids = params.get("id", [])
    country = params.get("country")
    if (
        parts.scheme != "https"
        or parts.hostname != "www.bearingpoint.com"
        or parts.path.rstrip("/") != PUBLIC_JOB_PATH.rstrip("/")
        or parts.fragment
        or set(params) - {"id", "country"}
        or (country is not None and country != ["CH"])
        or len(job_ids) != 1
        or not re.fullmatch(r"T\d+", job_ids[0])
    ):
        return None
    return job_ids[0]


def canonical_public_job_url(value: Any, *, expected_url: str) -> str:
    job_id = public_job_id(value)
    if not job_id:
        raise BearingpointSwitzerlandParseError("BearingPoint vacancy URL is invalid")
    origin = urlsplit(expected_url)
    return urlunsplit(
        (
            "https",
            origin.hostname or "www.bearingpoint.com",
            PUBLIC_JOB_PATH,
            urlencode({"id": job_id, "country": "CH"}),
            "",
        )
    )


def canonical_teamtailor_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.hostname != "bearingpointag.teamtailor.com"
        or not TEAMTAILOR_JOB_PATH_PATTERN.fullmatch(parts.path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", parts.hostname, parts.path, "", ""))


def extract_teamtailor_job_id(value: Any) -> str | None:
    url = canonical_teamtailor_job_url(value)
    match = TEAMTAILOR_JOB_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1) if match else None


def canonical_plain_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment:
        return None
    return urlunsplit(("https", parts.hostname.casefold(), parts.path.rstrip("/"), "", ""))


def canonical_organization_url(value: Any) -> str | None:
    return canonical_plain_url(value)


def application_url(value: Any) -> str | None:
    url = canonical_teamtailor_job_url(value)
    return f"{url}/applications/new" if url else None


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
    localities: list[str] = []
    for location in value:
        address = location.get("address") if isinstance(location, dict) else None
        locality = (
            optional_text(address.get("addressLocality"))
            if isinstance(address, dict)
            else None
        )
        if locality:
            localities.append(locality)
    return "; ".join(dict.fromkeys(localities)) or None


def valid_uuid(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    try:
        return str(UUID(text)) == text.casefold()
    except ValueError:
        return False


def deduplicate_bearingpoint_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
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


def selector_text(node: Any, query: str) -> str | None:
    selected = node.css(query)
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
