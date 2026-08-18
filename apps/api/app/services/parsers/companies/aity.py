from __future__ import annotations

import html
import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

AITY_JOBS_URL = "https://aity.ch/jobs"
AITY_CAREER_CENTER_URL = "https://jobs.aity.ch/"
AITY_COMPANY = "aity AG"
AITY_CAREER_CENTER_ID = "1005606"
AITY_PAGE_TITLE = "Finde deinen Traumjob bei aity"
AITY_CAREER_CENTER_TITLE = "aity AG: Career Center"
AITY_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
    ),
}
UUID_PATTERN = r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}"
JOB_PATH_PATTERN = re.compile(
    rf"^/offene-stellen/([a-z0-9]+(?:-[a-z0-9]+)*)/({UUID_PATTERN})$",
    re.IGNORECASE,
)
APPLY_PATH_PATTERN = re.compile(
    rf"^/public/v1/redirect/({UUID_PATTERN})/ats/$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"^\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*%$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class AityParseError(DirectCompanyRequestError):
    pass


class AityJobsParser:
    """Collect Aity's complete official Career Center catalog."""

    parser_id = "aity"

    def __init__(
        self,
        *,
        base_url: str = AITY_JOBS_URL,
        career_center_url: str = AITY_CAREER_CENTER_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.career_center_url = career_center_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(20, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=AITY_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                corporate_response = client.get(self.base_url)
                corporate_response.raise_for_status()
                iframe_url = parse_corporate_html(
                    corporate_response.text,
                    page_url=str(corporate_response.url),
                    expected_url=self.base_url,
                    expected_career_center_url=self.career_center_url,
                )

                listing_response = client.get(
                    iframe_url,
                    headers={"Referer": self.base_url},
                )
                listing_response.raise_for_status()
                records = parse_listing_html(
                    listing_response.text,
                    page_url=str(listing_response.url),
                    expected_url=self.career_center_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except AityParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Aity vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Aity vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_aity_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} aity vacancies from the complete official "
                "Career Center catalog"
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
                response = client.get(
                    record["url"],
                    headers={"Referer": self.career_center_url},
                )
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
            except (httpx.HTTPError, AityParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_corporate_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_career_center_url: str,
) -> str:
    expected = canonical_corporate_url(expected_url)
    career_center = canonical_career_center_url(expected_career_center_url)
    if not expected or not career_center or canonical_corporate_url(page_url) != expected:
        raise AityParseError("Aity careers page returned an unexpected page")

    page = Selector(page_html)
    title = selector_text(page, "title")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    og_url = canonical_corporate_url(page.css('meta[property="og:url"]::attr(content)').get())
    base_href = canonical_site_root(page.css("base::attr(href)").get())
    heading = selector_text(page, "main h1")
    address = selector_text(page, "footer address")
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de-CH"
        or title != AITY_PAGE_TITLE
        or og_title != AITY_PAGE_TITLE
        or og_url != expected
        or base_href != "https://aity.ch/"
        or heading != "Finde deinen Traumjob"
        or not address
        or not all(
            value in address
            for value in (
                AITY_COMPANY,
                "Schwarzenburgstrasse 160",
                "3097 Liebefeld",
                "Schweiz",
            )
        )
    ):
        raise AityParseError("Aity careers page has an unexpected identity")

    iframes = page.css("iframe#careercenter-pms")
    iframe_url = (
        canonical_career_center_url(
            urljoin(page_url, optional_text(iframes[0].css("::attr(src)").get()) or "")
        )
        if len(iframes) == 1
        else None
    )
    resizer_scripts = {
        canonical_resizer_url(urljoin(page_url, raw))
        for raw in page.css("script[src]::attr(src)").getall()
    }
    expected_resizer = (
        "https://jobs.aity.ch/careercenter/"
        f"{AITY_CAREER_CENTER_ID}/assets/js/iframe-resizer.parent.js"
    )
    if (
        iframe_url != career_center
        or expected_resizer not in resizer_scripts
        or "checkOrigin: ['https://jobs.aity.ch']" not in page_html
        or "'#careercenter-pms'" not in page_html
    ):
        raise AityParseError("Aity careers page is missing its official Career Center")
    return iframe_url


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    expected = canonical_career_center_url(expected_url)
    if not expected or canonical_career_center_url(page_url) != expected:
        raise AityParseError("Aity Career Center returned an unexpected page")

    page = Selector(page_html)
    stylesheet_urls = {
        canonical_career_asset_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="stylesheet"]::attr(href)').getall()
    }
    expected_stylesheet = (
        "https://jobs.aity.ch/careercenter/"
        f"{AITY_CAREER_CENTER_ID}/assets/css/aity-careercenter.css?v=1"
    )
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de"
        or optional_text(page.css('meta[http-equiv="content-language"]::attr(content)').get())
        != "de"
        or selector_text(page, "title") != AITY_CAREER_CENTER_TITLE
        or expected_stylesheet not in stylesheet_urls
    ):
        raise AityParseError("Aity Career Center has an unexpected identity")

    wrappers = page.css("div#jobs.jobWrapper")
    if len(wrappers) != 1:
        raise AityParseError("Aity Career Center is missing its vacancy catalog")
    wrapper = wrappers[0]
    cards = wrapper.css(":scope > a.jobItem")
    if len(cards) > max_jobs:
        raise AityParseError(
            f"Aity exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )

    newsletter_links = wrapper.css(":scope > a.infoItem.abo")
    newsletter_url = (
        canonical_newsletter_url(
            urljoin(page_url, optional_text(newsletter_links[0].css("::attr(href)").get()) or "")
        )
        if len(newsletter_links) == 1
        else None
    )
    if (
        newsletter_url != "https://jobs.aity.ch/jobabo?lang=de"
        or selector_text(newsletter_links[0], "h2") != "Nichts verpassen"
    ):
        raise AityParseError("Aity Career Center has an invalid newsletter marker")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        title = optional_text(card.css("::attr(aria-label)").get())
        detail_url = canonical_job_url(
            urljoin(page_url, optional_text(card.css("::attr(href)").get()) or "")
        )
        job_id = job_id_from_url(detail_url)
        workload_nodes = card.css("h2 span")
        workload = selector_text(workload_nodes[0]) if len(workload_nodes) == 1 else None
        heading = selector_text(card, "h2")
        rel = set((optional_text(card.css("::attr(rel)").get()) or "").split())
        if (
            not title
            or not detail_url
            or not job_id
            or not workload
            or not WORKLOAD_PATTERN.fullmatch(workload)
            or comparable_text(heading) != comparable_text(f"{title} {workload}")
            or optional_text(card.css("::attr(id)").get()) != f"job-{index}"
            or optional_text(card.css("::attr(target)").get()) != "_blank"
            or rel != {"noopener", "noreferrer"}
        ):
            raise AityParseError("Aity Career Center contains an invalid vacancy card")
        if job_id in seen_ids or detail_url in seen_urls:
            raise AityParseError("Aity Career Center contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(detail_url)
        records.append(
            {
                "id": job_id,
                "title": title,
                "company": AITY_COMPANY,
                "location": "Liebefeld, Switzerland",
                "employment_type": normalize_workload(workload),
                "url": detail_url,
                "catalog_index": index,
            }
        )
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_record: dict[str, Any],
) -> dict[str, Any]:
    expected_url = canonical_job_url(expected_record.get("url"))
    expected_id = optional_text(expected_record.get("id"))
    expected_title = optional_text(expected_record.get("title"))
    expected_workload = optional_text(expected_record.get("employment_type"))
    if (
        not expected_url
        or not expected_id
        or not expected_title
        or not expected_workload
        or canonical_job_url(page_url) != expected_url
    ):
        raise AityParseError("Aity detail page returned a different vacancy")

    page = Selector(page_html)
    document_title = f"{expected_title} - {AITY_COMPANY}"
    canonical_urls = {
        canonical_job_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de"
        or selector_text(page, "title") != document_title
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != document_title
        or optional_text(page.css('meta[name="author"]::attr(content)').get()) != AITY_COMPANY
        or optional_text(page.css('meta[name="copyright"]::attr(content)').get()) != AITY_COMPANY
        or canonical_urls != {expected_url}
    ):
        raise AityParseError("Aity detail page has an unexpected identity")

    postings = extract_job_postings(page_html)
    if len(postings) != 1:
        raise AityParseError("Aity detail page is missing its JobPosting data")
    posting = postings[0]
    organization = posting.get("hiringOrganization")
    job_location = posting.get("jobLocation")
    address = job_location.get("address") if isinstance(job_location, dict) else None
    title = optional_text(posting.get("title"))
    description = html_to_text(optional_text(posting.get("description")))
    qualifications = html_to_text(optional_text(posting.get("qualifications")))
    responsibilities = html_to_text(optional_text(posting.get("responsibilities")))
    locality = optional_text(address.get("addressLocality")) if isinstance(address, dict) else None
    region = optional_text(address.get("addressRegion")) if isinstance(address, dict) else None
    street = optional_text(address.get("streetAddress")) if isinstance(address, dict) else None
    postal_code = optional_text(address.get("postalCode")) if isinstance(address, dict) else None
    country = optional_text(address.get("addressCountry")) if isinstance(address, dict) else None
    posted_at = optional_text(posting.get("datePosted"))
    valid_through = optional_text(posting.get("validThrough"))
    industry = optional_text(posting.get("industry"))
    schema_employment_type = optional_text(posting.get("employmentType"))
    company = optional_text(organization.get("name")) if isinstance(organization, dict) else None
    if (
        title != expected_title
        or company != AITY_COMPANY
        or country != "Schweiz"
        or not all((locality, region, street, postal_code, industry))
        or not description
        or len(description) < 100
        or not qualifications
        or len(qualifications) < 50
        or not responsibilities
        or len(responsibilities) < 50
        or schema_employment_type != "FULL_TIME"
        or not posted_at
        or not DATE_PATTERN.fullmatch(posted_at)
        or (valid_through is not None and not DATE_PATTERN.fullmatch(valid_through))
    ):
        raise AityParseError("Aity detail page contains incomplete JobPosting data")

    visible_title = selector_text(page, ".stellenTitel h1")
    subtitle = selector_text(page, ".subTitle h3")
    visible_workload = (
        normalize_workload(visible_title[len(expected_title) :])
        if visible_title and visible_title.startswith(expected_title)
        else None
    )
    if visible_workload != expected_workload or comparable_text(locality) not in comparable_text(
        subtitle
    ):
        raise AityParseError("Aity detail page does not match its visible vacancy")

    apply_urls = {
        value
        for raw in page.css("a.applyButton::attr(href)").getall()
        if (value := canonical_apply_url(raw, expected_id=expected_id))
    }
    if len(apply_urls) != 1:
        raise AityParseError("Aity detail page is missing its direct application link")

    return {
        "id": expected_id,
        "title": title,
        "company": company,
        "location": swiss_location(locality),
        "employment_type": expected_workload,
        "schema_employment_type": schema_employment_type,
        "description": description,
        "qualifications": qualifications,
        "responsibilities": responsibilities,
        "posted_at": posted_at,
        "valid_through": valid_through,
        "industry": industry,
        "url": expected_url,
        "apply_url": apply_urls.pop(),
        "job_posting": posting,
    }


def extract_job_postings(page_html: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    scripts = re.findall(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    for raw in scripts:
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                postings.append(item)
    return postings


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="aity",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=AITY_COMPANY,
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


def canonical_corporate_url(value: Any) -> str | None:
    return canonical_url(value, host="aity.ch", path="/jobs")


def canonical_site_root(value: Any) -> str | None:
    return canonical_url(value, host="aity.ch", path="/", keep_trailing_slash=True)


def canonical_career_center_url(value: Any) -> str | None:
    return canonical_url(
        value,
        host="jobs.aity.ch",
        path="/",
        keep_trailing_slash=True,
    )


def canonical_url(
    value: Any,
    *,
    host: str,
    path: str,
    keep_trailing_slash: bool = False,
) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    actual_path = parts.path if keep_trailing_slash else parts.path.rstrip("/")
    expected_path = path if keep_trailing_slash else path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != host
        or actual_path != expected_path
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", host, path, "", ""))


def canonical_resizer_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    expected_path = f"/careercenter/{AITY_CAREER_CENTER_ID}/assets/js/iframe-resizer.parent.js"
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.aity.ch"
        or parts.path != expected_path
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.aity.ch", expected_path, "", ""))


def canonical_career_asset_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    expected_path = f"/careercenter/{AITY_CAREER_CENTER_ID}/assets/css/aity-careercenter.css"
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.aity.ch"
        or parts.path != expected_path
        or parse_qs(parts.query, keep_blank_values=True) != {"v": ["1"]}
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.aity.ch", expected_path, "v=1", ""))


def canonical_newsletter_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.aity.ch"
        or parts.path.rstrip("/") != "/jobabo"
        or parse_qs(parts.query, keep_blank_values=True) != {"lang": ["de"]}
        or parts.fragment
    ):
        return None
    return "https://jobs.aity.ch/jobabo?lang=de"


def canonical_job_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    path = parts.path.rstrip("/")
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.aity.ch"
        or not JOB_PATH_PATTERN.fullmatch(path)
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "jobs.aity.ch", path, "", ""))


def canonical_apply_url(value: Any, *, expected_id: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = APPLY_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "ohws.prospective.ch"
        or not match
        or match.group(1).casefold() != expected_id.casefold()
        or parts.query
        or parts.fragment
    ):
        return None
    return urlunsplit(("https", "ohws.prospective.ch", parts.path, "", ""))


def job_id_from_url(value: Any) -> str | None:
    url = canonical_job_url(value)
    if not url or not (match := JOB_PATH_PATTERN.fullmatch(urlsplit(url).path)):
        return None
    return match.group(2).casefold()


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not WORKLOAD_PATTERN.fullmatch(text):
        return None
    return re.sub(r"\s*[-–]\s*", "–", re.sub(r"\s+%", "%", text))


def swiss_location(value: Any) -> str | None:
    locality = optional_text(value)
    if not locality:
        return None
    if locality.casefold() == "bern-liebefeld":
        locality = "Bern-Liebefeld"
    return f"{locality}, Switzerland"


def deduplicate_aity_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = job_id_from_url(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def html_to_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", value)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return optional_multiline_text(html.unescape(text).replace("\xa0", " "))


def selector_text(node: Any, selector: str | None = None) -> str | None:
    target = node.css(selector) if selector else node
    return optional_text(" ".join(target.css("::text").getall()))


def comparable_text(value: Any) -> str:
    return (optional_text(value) or "").casefold()


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).replace("\u200b", "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return re.sub(r"[\s\u200b]+", " ", value).strip() or None
