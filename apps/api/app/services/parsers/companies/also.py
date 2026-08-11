from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

ALSO_JOBS_BASE_URL = (
    "https://www.also.com/ec/cms5/en_6000/6000/company/career/open-positions/index.jsp"
)
ALSO_JOBS_API_URL = (
    "https://www.also.com/ec/cms5/en_6000/6000/company/career/open-positions/jobs_json_4.json"
)
ALSO_HEADERS = {
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DETAIL_PATH_PATTERN = re.compile(
    r"^/ec/cms5/en_6000/6000/company/career/open-positions/"
    r"job_details_v2_2_(\d+)\.jsp$"
)
APPLY_PATH_PATTERN = re.compile(r"^/cvdropper/[a-f0-9]{32}/[A-Z]{2}$")
EXPECTED_COMPANY = "ALSO Holding AG"
EXPECTED_COUNTRY = "Switzerland"


class AlsoParseError(DirectCompanyRequestError):
    pass


class AlsoJobsParser:
    """Collect every Swiss vacancy from ALSO's official JSON catalog."""

    parser_id = "also"

    def __init__(
        self,
        *,
        base_url: str = ALSO_JOBS_BASE_URL,
        api_url: str = ALSO_JOBS_API_URL,
        timeout_seconds: float = 30.0,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**ALSO_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.api_url)
                response.raise_for_status()
                all_records = parse_catalog_payload(
                    response.json(),
                    expected_host=urlsplit(self.base_url).netloc.casefold(),
                )
                records = [record for record in all_records if is_swiss_record(record)]
                self.enrich_records(client, records)
        except AlsoParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("ALSO vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("ALSO vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_also_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} ALSO Switzerland vacancies from "
                f"{len(all_records)} official catalog records"
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
                    expected_url=record["url"],
                    expected_job_id=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, AlsoParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or optional_text(record.get("title")),
            company=EXPECTED_COMPANY,
            location=optional_text(detail.get("location")) or EXPECTED_COUNTRY,
            url=optional_text(record.get("url")),
            apply_url=optional_text(detail.get("apply_url")),
            posted_at=optional_text(detail.get("posted_at")),
            employment_type=None,
            seniority=optional_text(record.get("joblevel")),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_catalog_payload(payload: Any, *, expected_host: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise AlsoParseError("ALSO catalog response must be an object")
    jobs = payload.get("jobs")
    if not isinstance(jobs, list):
        raise AlsoParseError("ALSO catalog response has invalid jobs")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in jobs:
        if not isinstance(item, dict):
            raise AlsoParseError("ALSO catalog contains an invalid vacancy")
        job_id = normalize_job_id(item.get("id"))
        title = optional_text(item.get("title"))
        country = optional_text(item.get("country"))
        country_label = optional_text(item.get("country_lang"))
        public_url = optional_text(item.get("url"))
        if (
            not job_id
            or not title
            or not country
            or not country_label
            or not is_detail_url(
                public_url,
                expected_host=expected_host,
                expected_job_id=job_id,
            )
        ):
            raise AlsoParseError("ALSO catalog contains an incomplete vacancy")
        if job_id in seen_ids:
            raise AlsoParseError("ALSO catalog contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        records.append(
            {
                "id": job_id,
                "title": title,
                "country": country,
                "country_lang": country_label,
                "url": public_url,
                "department": optional_text(item.get("department")),
                "joblevel": optional_text(item.get("joblevel")),
                "catalog_record": dict(item),
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
    if not same_detail_url(page_url, expected_url):
        raise AlsoParseError("ALSO detail page returned a different vacancy")

    page = Selector(page_html)
    article = page.css("div.article.job_detail.job_detail_v2")
    if not article.get():
        raise AlsoParseError("ALSO detail page is missing its vacancy article")

    title = selector_text(article, "h1.separat")
    locality = selector_text(article, "h2")
    keywords = optional_text(page.css('meta[name="keywords"]::attr(content)').get())
    country_values = {part.casefold() for part in split_meta_values(keywords)}
    description_parts = article.css("p, ul").getall()
    description = html_to_text("\n".join(str(value) for value in description_parts))
    apply_urls = {
        urljoin(page_url, str(value))
        for value in article.css("a.btn::attr(href)").getall()
        if is_apply_url(urljoin(page_url, str(value)))
    }
    apply_url = next(iter(apply_urls)) if len(apply_urls) == 1 else None
    if (
        title != optional_text(expected_title)
        or not locality
        or EXPECTED_COUNTRY.casefold() not in country_values
        or not description
        or not apply_url
        or extract_job_id(page_url) != expected_job_id
    ):
        raise AlsoParseError("ALSO detail page contains an incomplete or non-Swiss vacancy")

    return {
        "id": expected_job_id,
        "title": title,
        "company": EXPECTED_COMPANY,
        "location": f"{locality}, {EXPECTED_COUNTRY}",
        "posted_at": normalize_date(page.css('meta[name="date"]::attr(content)').get()),
        "apply_url": apply_url,
        "description": description,
    }


def is_swiss_record(record: dict[str, Any]) -> bool:
    return (
        optional_text(record.get("country")) == EXPECTED_COUNTRY
        and optional_text(record.get("country_lang")) == EXPECTED_COUNTRY
    )


def normalize_job_id(value: Any) -> str | None:
    if isinstance(value, bool):
        return None
    text = optional_text(value)
    return text if text and text.isdigit() and int(text) > 0 else None


def extract_job_id(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    match = DETAIL_PATH_PATTERN.fullmatch(urlsplit(text).path)
    return match.group(1) if match else None


def is_detail_url(value: Any, *, expected_host: str, expected_job_id: str) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == expected_host
        and extract_job_id(text) == expected_job_id
        and not parts.query
        and not parts.fragment
    )


def same_detail_url(value: Any, expected: Any) -> bool:
    actual_text = optional_text(value)
    expected_text = optional_text(expected)
    if not actual_text or not expected_text:
        return False
    actual = urlsplit(actual_text)
    target = urlsplit(expected_text)
    return (
        actual.scheme == target.scheme == "https"
        and actual.netloc.casefold() == target.netloc.casefold()
        and actual.path == target.path
        and not actual.query
        and not actual.fragment
    )


def is_apply_url(value: Any) -> bool:
    text = optional_text(value)
    if not text:
        return False
    parts = urlsplit(text)
    return (
        parts.scheme == "https"
        and parts.netloc.casefold() == "link.ostendis.com"
        and APPLY_PATH_PATTERN.fullmatch(parts.path) is not None
        and not parts.fragment
    )


def split_meta_values(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def selector_text(selector: Any, css: str) -> str | None:
    value = selector.css(css).get()
    return html_to_text(str(value)) if value else None


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return (
            datetime.strptime(text, "%d.%m.%Y %H:%M:%S CEST")
            .replace(tzinfo=ZoneInfo("Europe/Zurich"))
            .date()
            .isoformat()
        )
    except ValueError:
        return None


def deduplicate_also_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.url) or job.url or ""
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
