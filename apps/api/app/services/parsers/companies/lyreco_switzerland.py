from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

LYRECO_SWITZERLAND_JOBS_URL = (
    "https://www.lyreco.com/group/switzerland/de/jobs?f%5B0%5D=job_location%3Adietikon%20zh"
)
LYRECO_CANONICAL_JOBS_URL = "https://www.lyreco.com/group/switzerland/en/jobs"
LYRECO_COMPANY = "Lyreco Switzerland AG"
LYRECO_PAGE_TITLE = "Stelle finden | Lyreco Schweiz"
LYRECO_FILTER_VALUES = {"f[0]": ["job_location:dietikon zh"]}
LYRECO_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
LYRECO_JOB_PATH_PATTERN = re.compile(r"^/group/switzerland/de/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)$")
LYRECO_DETAIL_CANONICAL_PATTERN = re.compile(r"^/jobs/([a-z0-9]+(?:-[a-z0-9]+)*)$")
LYRECO_TOTAL_PATTERN = re.compile(r"^(\d+)\s+Resultate$")
LYRECO_IDENTIFIER_PATTERN = re.compile(r"^\d+$")
LYRECO_EXTERNAL_ID_PATTERN = re.compile(r"^JR-\d+(?:-\d+)*$")


class LyrecoSwitzerlandParseError(DirectCompanyRequestError):
    pass


class LyrecoLocationMissingError(LyrecoSwitzerlandParseError):
    """The global catalog provides no evidence to classify a vacancy's country."""


class LyrecoSwitzerlandJobsParser:
    """Collect the complete Lyreco Dietikon vacancy catalog."""

    parser_id = "lyreco_switzerland"

    def __init__(
        self,
        *,
        base_url: str = LYRECO_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 100,
        max_jobs: int = 1_000,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(20, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        warnings: list[str] = []
        try:
            with httpx.Client(
                headers=LYRECO_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records = self.collect_listing(client, warnings=warnings)
                self.enrich_records(client, records)
        except LyrecoSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Lyreco Switzerland vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Lyreco Switzerland vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_lyreco_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            warnings=warnings,
            message=(
                f"Scanned {len(jobs)} Lyreco Switzerland vacancies from the "
                "complete Dietikon careers catalog"
            ),
        )

    def collect_listing(
        self, client: httpx.Client, *, warnings: list[str] | None = None
    ) -> list[dict[str, Any]]:
        first_url = build_page_url(self.base_url, 0)
        first_response = client.get(first_url, headers={"Referer": LYRECO_CANONICAL_JOBS_URL})
        first_response.raise_for_status()
        records, total = parse_listing_html(
            first_response.text,
            page_url=str(first_response.url),
            expected_url=first_url,
            page_number=0,
        )
        if total > self.max_jobs:
            raise LyrecoSwitzerlandParseError(
                f"Lyreco exposes {total} jobs, above the configured limit of {self.max_jobs}"
            )
        if total == 0:
            return []
        if not records:
            raise LyrecoSwitzerlandParseError(
                "Lyreco careers catalog has a positive total but no vacancies"
            )

        page_count = math.ceil(total / len(records))
        if page_count > self.max_pages:
            raise LyrecoSwitzerlandParseError(
                f"Lyreco catalog requires {page_count} pages, above the configured "
                f"limit of {self.max_pages}"
            )
        for page_number in range(1, page_count):
            page_url = build_page_url(self.base_url, page_number)
            response = client.get(page_url, headers={"Referer": first_url})
            response.raise_for_status()
            page_records, page_total = parse_listing_html(
                response.text,
                page_url=str(response.url),
                expected_url=page_url,
                page_number=page_number,
            )
            if page_total != total:
                raise LyrecoSwitzerlandParseError("Lyreco catalog total changed during pagination")
            records.extend(page_records)

        internal_ids = [optional_text(record.get("internal_id")) for record in records]
        urls = [optional_text(record.get("url")) for record in records]
        if (
            len(records) != total
            or len(set(internal_ids)) != len(internal_ids)
            or len(set(urls)) != len(urls)
        ):
            raise LyrecoSwitzerlandParseError(
                "Lyreco catalog does not reconcile with its result total"
            )
        for record in records:
            if not record["location_raw"]:
                response = client.get(record["url"])
                response.raise_for_status()
                try:
                    detail = parse_detail_html(
                        response.text, page_url=str(response.url), expected_record=record
                    )
                except LyrecoLocationMissingError:
                    if warnings is None:
                        raise
                    warnings.append(
                        f"Skipped vacancy with unverified country/location: {record['url']}"
                    )
                    continue
                record.update(
                    location_raw="Dietikon ZH", location="Dietikon ZH, Switzerland", detail=detail
                )
        return [
            record for record in records if comparable_text(record["location_raw"]) == "dietikon zh"
        ]

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
                if record.get("detail"):
                    return record, record["detail"]
                response = client.get(record["url"], headers={"Referer": self.base_url})
                response.raise_for_status()
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
                return record, detail
            except (httpx.HTTPError, LyrecoSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["id"] = detail["id"]
                    record["detail"] = detail


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    page_number: int,
) -> tuple[list[dict[str, Any]], int]:
    if canonical_search_url(page_url) != canonical_search_url(expected_url):
        raise LyrecoSwitzerlandParseError("Lyreco catalog returned an unexpected page")
    if search_page_number(page_url) != page_number:
        raise LyrecoSwitzerlandParseError("Lyreco catalog returned a different page number")

    page = Selector(page_html)
    title = selector_text(page, "title")
    canonical = canonical_jobs_url(
        optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    )
    language = optional_text(page.css("html::attr(lang)").get())
    headings = {selector_text(node) for node in page.css("h1")}
    if (
        title != LYRECO_PAGE_TITLE
        or canonical != LYRECO_CANONICAL_JOBS_URL
        or language != "de"
        or headings != {"Stelle finden"}
    ):
        raise LyrecoSwitzerlandParseError("Lyreco careers page has an unexpected identity")

    total_values = {
        int(match.group(1))
        for node in page.css(".jobs-total-results")
        if (match := LYRECO_TOTAL_PATTERN.fullmatch(selector_text(node) or ""))
    }
    if len(total_values) != 1:
        raise LyrecoSwitzerlandParseError("Lyreco careers page is missing its result total")
    total = total_values.pop()

    legacy_facets = bool(page.css("a[data-drupal-facet-item-value]"))
    location_facets = page.css('a.is-active[data-drupal-facet-item-value="dietikon zh"]')
    if legacy_facets and (
        len(location_facets) != 1
        or not facet_matches(
            location_facets[0],
            value="dietikon zh",
            filter_value="job_location:dietikon zh",
            count=total,
        )
    ):
        raise LyrecoSwitzerlandParseError("Lyreco careers page has an unexpected Dietikon filter")

    country_facets = page.css('a[data-drupal-facet-item-value="switzerland"]')
    if legacy_facets and (
        len(country_facets) != 1
        or not facet_matches(
            country_facets[0],
            value="switzerland",
            filter_value="country:switzerland",
            count=total,
        )
    ):
        raise LyrecoSwitzerlandParseError(
            "Lyreco Switzerland facet does not match the result total"
        )

    records: list[dict[str, Any]] = []
    for card in page.css(".job.teaser.views-row"):
        title_links = card.css("h2 a[href]")
        title_value = selector_text(title_links[0]) if len(title_links) == 1 else None
        href = optional_text(title_links[0].css("::attr(href)").get()) if title_links else None
        detail_url = canonical_job_url(urljoin(page_url, href or ""))
        path_match = (
            LYRECO_JOB_PATH_PATTERN.fullmatch(urlsplit(detail_url).path) if detail_url else None
        )
        location = selector_text(card, ".job__info__location")
        family = selector_text(card, ".job__info__family")
        employment_type = selector_text(card, ".job__info__time")
        if (
            not title_value
            or not path_match
            or (legacy_facets and comparable_text(location) != "dietikon zh")
        ):
            raise LyrecoSwitzerlandParseError(
                "Lyreco catalog contains an incomplete or out-of-scope vacancy"
            )
        records.append(
            {
                "id": path_match.group(1),
                "internal_id": path_match.group(1),
                "title": title_value,
                "company": LYRECO_COMPANY,
                "location": swiss_location(location)
                if comparable_text(location) == "dietikon zh"
                else location,
                "location_raw": location,
                "family": family,
                "employment_type": employment_type,
                "url": detail_url,
                "page_number": page_number,
                "catalog_total": total,
            }
        )
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    if canonical_job_url(page_url) != expected_url:
        raise LyrecoSwitzerlandParseError("Lyreco detail page returned a different vacancy")
    page = Selector(page_html)
    language = optional_text(page.css("html::attr(lang)").get())
    title = selector_text(page, "h1")
    document_title = selector_text(page, "title")
    canonical = canonical_detail_url(
        optional_text(page.css('link[rel="canonical"]::attr(href)').get())
    )
    open_graph_url = canonical_job_url(
        optional_text(page.css('meta[property="og:url"]::attr(content)').get())
    )
    if (
        language != "de"
        or comparable_text(title) != comparable_text(expected_record.get("title"))
        or document_title != f"{title} | Lyreco Schweiz"
        or not canonical
        or open_graph_url != expected_url
    ):
        raise LyrecoSwitzerlandParseError("Lyreco detail page has invalid vacancy identity")

    postings: list[dict[str, Any]] = []
    for raw in page.css('script[type="application/ld+json"]::text').getall():
        try:
            candidate = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        postings.extend(job_postings(candidate))
    if len(postings) != 1:
        raise LyrecoSwitzerlandParseError("Lyreco detail page is missing its JobPosting metadata")

    posting = postings[0]
    identifier = optional_text(posting.get("identifier"))
    organization = posting.get("hiringOrganization")
    organization = organization if isinstance(organization, dict) else {}
    address = posting_address(posting)
    posting_description = optional_text(posting.get("description"))
    visible_description = selector_multiline_text(page, ".field--name-field-description")
    visible_location = selector_text(page, ".job__field-primary-location")
    visible_family = selector_text(page, ".field--name-field-family")
    visible_employment_type = selector_text(page, ".field--name-field-time-type")
    posted_at = optional_text(posting.get("datePosted"))
    explicit_dietikon = bool(
        re.search(r"Arbeitsort:\s*Dietikon\b", visible_description or "", re.IGNORECASE)
    )
    locality = comparable_text(address.get("addressLocality"))
    country = comparable_text(address.get("addressCountry"))
    verified_location = (locality == "dietikon zh" and country == "switzerland") or (
        not locality and not country and not visible_location and explicit_dietikon
    )
    if (
        not identifier
        or not LYRECO_IDENTIFIER_PATTERN.fullmatch(identifier)
        or comparable_text(posting.get("title")) != comparable_text(expected_record.get("title"))
        or optional_text(organization.get("name")) != "Lyreco"
        or canonical_group_url(organization.get("url"))
        != "https://www.lyreco.com/group/switzerland/de"
        or comparable_text(posting.get("industry"))
        != comparable_text(expected_record.get("family"))
        or (
            visible_location is not None
            and comparable_text(visible_location)
            != comparable_text(expected_record.get("location_raw"))
        )
        or comparable_text(visible_family) != comparable_text(expected_record.get("family"))
        or comparable_text(visible_employment_type)
        != comparable_text(expected_record.get("employment_type"))
        or not posting_description
        or len(posting_description) < 100
        or not visible_description
        or len(visible_description) < 100
        or (posted_at is not None and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", posted_at))
    ):
        raise LyrecoSwitzerlandParseError("Lyreco detail page has invalid JobPosting metadata")

    if not verified_location:
        if not locality and not country and not visible_location:
            raise LyrecoLocationMissingError("Lyreco vacancy has no verifiable location")
        raise LyrecoSwitzerlandParseError("Lyreco detail page has invalid JobPosting metadata")

    apply_urls = {
        value
        for raw in page.css("a.btn.btn-primary[href]::attr(href)").getall()
        if (value := canonical_apply_url(urljoin(page_url, raw)))
    }
    if len(apply_urls) != 1:
        raise LyrecoSwitzerlandParseError(
            "Lyreco detail page is missing its direct application URL"
        )
    apply_url = apply_urls.pop()
    external_id = external_id_from_apply_url(apply_url)
    if not external_id:
        raise LyrecoSwitzerlandParseError("Lyreco application URL has invalid vacancy identity")

    return {
        "id": external_id,
        "internal_id": identifier,
        "title": title,
        "company": LYRECO_COMPANY,
        "location": swiss_location(visible_location or "Dietikon ZH"),
        "employment_type": visible_employment_type,
        "family": visible_family,
        "description": visible_description,
        "canonical_url": canonical,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "job_posting": posting,
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="lyreco_switzerland",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=LYRECO_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=(
            optional_text(detail.get("employment_type"))
            or optional_text(record.get("employment_type"))
        ),
        seniority=None,
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def build_page_url(base_url: str, page_number: int) -> str:
    parts = urlsplit(base_url)
    query = parse_qs(parts.query, keep_blank_values=True)
    if page_number == 0:
        query.pop("page", None)
    else:
        query["page"] = [str(page_number)]
    pairs = [(key, item) for key, values in query.items() for item in values]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), ""))


def search_page_number(value: Any) -> int | None:
    text = optional_text(value)
    if not text:
        return None
    query = parse_qs(urlsplit(text).query, keep_blank_values=True)
    pages = query.get("page")
    if pages is None:
        return 0
    if len(pages) != 1 or not pages[0].isdigit():
        return None
    return int(pages[0])


def canonical_search_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query, keep_blank_values=True)
    pages = query.pop("page", None)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.lyreco.com"
        or parts.path.rstrip("/") != "/group/switzerland/de/jobs"
        or query != LYRECO_FILTER_VALUES
        or (pages is not None and (len(pages) != 1 or not pages[0].isdigit()))
        or parts.fragment
    ):
        return None
    page_number = int(pages[0]) if pages else 0
    return build_page_url(LYRECO_SWITZERLAND_JOBS_URL, page_number)


def canonical_jobs_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.lyreco.com"
        or parts.path.rstrip("/")
        not in {"/group/switzerland/en/jobs", "/group/switzerland/de/jobs"}
        or parts.query
        or parts.fragment
    ):
        return None
    return LYRECO_CANONICAL_JOBS_URL


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.lyreco.com"
        or not LYRECO_JOB_PATH_PATTERN.fullmatch(path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.lyreco.com", path, "", ""))


def canonical_detail_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    is_public_path = bool(LYRECO_JOB_PATH_PATTERN.fullmatch(path))
    is_short_path = bool(LYRECO_DETAIL_CANONICAL_PATTERN.fullmatch(path))
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.lyreco.com"
        or not (is_public_path or is_short_path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "www.lyreco.com", path, "", ""))


def canonical_group_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.lyreco.com"
        or parts.path.rstrip("/") != "/group/switzerland/de"
        or parts.query
        or parts.fragment
    ):
        return None
    return "https://www.lyreco.com/group/switzerland/de"


def canonical_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = unquote(parts.path).rstrip("/")
    match = re.fullmatch(
        r"/Lyreco_Careers/job/(?:Dietikon-ZH/)?[^/]+_(JR-\d+(?:-\d+)*)/apply",
        path,
    )
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "lyreco.wd3.myworkdayjobs.com"
        or not match
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "lyreco.wd3.myworkdayjobs.com", parts.path.rstrip("/"), "", ""))


def external_id_from_apply_url(value: Any) -> str | None:
    canonical = canonical_apply_url(value)
    if not canonical:
        return None
    match = re.search(r"_(JR-\d+(?:-\d+)*)/apply$", unquote(urlsplit(canonical).path))
    external_id = match.group(1) if match else None
    return (
        external_id if external_id and LYRECO_EXTERNAL_ID_PATTERN.fullmatch(external_id) else None
    )


def facet_matches(node: Any, *, value: str, filter_value: str, count: int) -> bool:
    facet_value = optional_text(node.css("::attr(data-drupal-facet-item-value)").get())
    facet_filter = optional_text(node.css("::attr(data-drupal-facet-filter-value)").get())
    facet_count = optional_text(node.css("::attr(data-drupal-facet-item-count)").get())
    visible_value = selector_text(node, ".facet-item__value")
    visible_count = parse_parenthesized_count(selector_text(node, ".facet-item__count"))
    return (
        comparable_text(facet_value) == comparable_text(value)
        and comparable_text(facet_filter) == comparable_text(filter_value)
        and facet_count == str(count)
        and comparable_text(visible_value) == comparable_text(value)
        and visible_count == count
    )


def job_postings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [posting for item in value for posting in job_postings(item)]
    if not isinstance(value, dict):
        return []
    postings = [value] if value.get("@type") == "JobPosting" else []
    graph = value.get("@graph")
    if isinstance(graph, (dict, list)):
        postings.extend(job_postings(graph))
    return postings


def posting_address(posting: dict[str, Any]) -> dict[str, Any]:
    location = posting.get("jobLocation")
    if not isinstance(location, dict):
        return {}
    address = location.get("address")
    return address if isinstance(address, dict) else {}


def parse_parenthesized_count(value: Any) -> int | None:
    match = re.fullmatch(r"\((\d+)\)", optional_text(value) or "")
    return int(match.group(1)) if match else None


def swiss_location(value: Any) -> str | None:
    location = optional_text(value)
    if not location:
        return None
    if comparable_text(location).endswith("switzerland"):
        return location
    return f"{location}, Switzerland"


def deduplicate_lyreco_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, query: str | None = None) -> str | None:
    selected = node.css(query) if query else [node]
    if not selected:
        return None
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


def selector_multiline_text(node: Any, query: str) -> str | None:
    selected = node.css(query)
    if not selected:
        return None
    return optional_multiline_text("\n".join(selected[0].css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


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
    return re.sub(r"\s+", " ", text).strip() or None
