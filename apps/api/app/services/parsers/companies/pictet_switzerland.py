from __future__ import annotations

import html
import json
import re
import secrets
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

PICTET_SWITZERLAND_JOBS_URL = (
    "https://career012.successfactors.eu/career?company=banquepict"
    "&career_ns=job_listing_summary&navBarLevel=JOB_SEARCH"
)
PICTET_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,fr-CH;q=0.8,fr;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
DWR_PATH = "/xi/ajax/remoting/call/plaincall/careerJobSearchControllerProxy.search.dwr"
VIEW_ID = "/ui/rcmcareer/pages/careersite/career.jsp.xhtml"
CSRF_PATTERN = re.compile(r'var\s+ajaxSecKey="([^"]+)"')
TOTAL_PATTERN = re.compile(r"\.totalCount=(\d+);")
PAGE_SIZE_PATTERN = re.compile(r"\.pageSize=(\d+);")
POSTING_COUNT_PATTERN = re.compile(r"\.postingCount=(\d+);")
JOB_PATTERN = re.compile(
    r"(?P<var>s\d+)\.corporatePosting=.*?"
    r"(?P=var)\.id=(?P<id>\d+);"
    r"(?P=var)\.jobReqSecKey=\"(?P<key>(?:\\.|[^\"])*)\";"
    r".*?(?P=var)\.otherValues=(?P<values>s\d+);"
    r".*?(?P=var)\.postingDate=\"(?P<date>(?:\\.|[^\"])*)\";"
    r".*?(?P=var)\.title=\"(?P<title>(?:\\.|[^\"])*)\";",
    re.DOTALL,
)
FIELD_PATTERN = re.compile(
    r"s\d+\.fieldId=\"(?P<field>filter[123])\";"
    r".*?s\d+\.shortVal=\"(?P<value>(?:\\.|[^\"])*)\";",
    re.DOTALL,
)


class PictetSwitzerlandParseError(DirectCompanyRequestError):
    pass


class PictetSwitzerlandJobsParser:
    """Collect every Pictet vacancy whose official country is Switzerland."""

    parser_id = "pictet_switzerland"

    def __init__(
        self,
        *,
        base_url: str = PICTET_SWITZERLAND_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 1000,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(8, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=PICTET_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                records, catalog_passes, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except PictetSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Pictet vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Pictet vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_pictet_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Pictet Switzerland vacancies from {total} global "
                f"postings in {catalog_passes} catalog pass(es)"
            ),
        )

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        last_count = 0
        last_total = 0
        last_error: Exception | None = None
        for catalog_pass in range(1, self.max_catalog_passes + 1):
            try:
                landing = client.get(self.base_url)
                landing.raise_for_status()
                token = extract_csrf_token(landing.text)
                response = client.post(
                    origin_for(self.base_url) + DWR_PATH,
                    params={"_s.crb": token},
                    content=build_search_body(self.base_url, page_size=self.max_jobs),
                    headers={
                        "Accept": "*/*",
                        "Content-Type": "text/plain",
                        "Origin": origin_for(self.base_url),
                        "Referer": self.base_url,
                        "Sec-Fetch-Dest": "empty",
                        "Sec-Fetch-Mode": "cors",
                        "Sec-Fetch-Site": "same-origin",
                        "X-Requested-With": "XMLHttpRequest",
                        "viewId": VIEW_ID,
                    },
                )
                response.raise_for_status()
                records, total = parse_catalog_response(
                    response.text,
                    base_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
            except (httpx.HTTPError, PictetSwitzerlandParseError) as exc:
                last_error = exc
                continue
            last_count = len(records)
            last_total = total
            return records, catalog_pass, total

        raise PictetSwitzerlandParseError(
            "Pictet catalog did not stabilize after "
            f"{self.max_catalog_passes} passes (collected {last_count} Swiss jobs "
            f"from {last_total} global postings)"
        ) from last_error

    def enrich_records(self, client: httpx.Client, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        def fetch(record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
            try:
                response = client.get(str(record["url"]), headers={"Referer": self.base_url})
                response.raise_for_status()
                return record, parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_id=str(record["id"]),
                    expected_title=str(record["title"]),
                )
            except (httpx.HTTPError, PictetSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        title = optional_text(detail.get("title")) or optional_text(record.get("title"))
        public_url = optional_text(record.get("url"))
        return ParsedJob(
            source=self.parser_id,
            title=title,
            company="Pictet",
            location=optional_text(detail.get("location")) or optional_text(record.get("location")),
            url=public_url,
            apply_url=public_url,
            posted_at=optional_text(detail.get("posted_at"))
            or optional_text(record.get("posted_at")),
            seniority=extract_seniority(title),
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def extract_csrf_token(page_html: str) -> str:
    match = CSRF_PATTERN.search(page_html)
    if not match:
        raise PictetSwitzerlandParseError("Pictet career page is missing its request token")
    return unquote(match.group(1))


def origin_for(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def build_search_body(base_url: str, *, page_size: int) -> str:
    parts = urlsplit(base_url)
    page = parts.path + (f"?{parts.query}" if parts.query else "")
    session_id = secrets.token_hex(16).upper() + "123"
    values = [
        "callCount=1",
        f"page={page}",
        "httpSessionId=",
        f"scriptSessionId={session_id}",
        "c0-scriptName=careerJobSearchControllerProxy",
        "c0-methodName=search",
        "c0-id=0",
        (
            "c0-param0=Object_Object:{pagination:reference:c0-e1, "
            "sortByColumn:reference:c0-e2, sortOrder:reference:c0-e3}"
        ),
        (
            "c0-e1=Object_Object:{currentPage:reference:c0-e4, "
            "endRow:reference:c0-e5, increaseCandSummaryPagination:reference:c0-e6, "
            "pageSize:reference:c0-e7, startRow:reference:c0-e8, "
            "totalCount:reference:c0-e9}"
        ),
        "c0-e2=string:JOB_POSTING_DATE",
        "c0-e3=string:DESC",
        "c0-e4=number:1",
        f"c0-e5=number:{page_size}",
        "c0-e6=boolean:false",
        f"c0-e7=number:{page_size}",
        "c0-e8=number:1",
        f"c0-e9=number:{page_size}",
        "batchId=0",
        "",
    ]
    return "\n".join(values)


def parse_catalog_response(
    payload: str,
    *,
    base_url: str,
    max_jobs: int,
) -> tuple[list[dict[str, Any]], int]:
    if "dwr.engine._remoteHandleCallback" not in payload:
        raise PictetSwitzerlandParseError("Pictet catalog returned a non-DWR response")
    totals = [int(value) for value in TOTAL_PATTERN.findall(payload)]
    counts = [int(value) for value in POSTING_COUNT_PATTERN.findall(payload)]
    page_sizes = [int(value) for value in PAGE_SIZE_PATTERN.findall(payload)]
    if not totals or not counts or not page_sizes or totals[-1] != counts[-1]:
        raise PictetSwitzerlandParseError("Pictet catalog returned inconsistent totals")
    total = totals[-1]
    if total > max_jobs or page_sizes[-1] < total:
        raise PictetSwitzerlandParseError(
            f"Pictet catalog exceeds the configured limit of {max_jobs} jobs"
        )

    matches = list(JOB_PATTERN.finditer(payload))
    if len(matches) != total:
        raise PictetSwitzerlandParseError(
            f"Pictet catalog returned {len(matches)} of {total} global postings"
        )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, match in enumerate(matches):
        job_id = match.group("id")
        if job_id in seen_ids:
            raise PictetSwitzerlandParseError("Pictet catalog contains duplicate vacancy IDs")
        seen_ids.add(job_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(payload)
        fields = {
            field.group("field"): decode_js_string(field.group("value"))
            for field in FIELD_PATTERN.finditer(payload[match.end() : end])
        }
        country = optional_text(fields.get("filter1"))
        city = optional_text(fields.get("filter2"))
        title = optional_text(decode_js_string(match.group("title")))
        posted_at = normalize_date(decode_js_string(match.group("date")))
        if not country or not city or not title or not posted_at:
            raise PictetSwitzerlandParseError("Pictet catalog contains an incomplete vacancy")
        if comparable_text(country) != "switzerland":
            continue
        detail_url = (
            f"{origin_for(base_url)}/career?career_ns=job_listing&company=banquepict"
            f"&navBarLevel=JOB_SEARCH&rcm_site_locale=en_GB&career_job_req_id={job_id}"
            "&selected_lang=en_GB"
        )
        records.append(
            {
                "id": job_id,
                "title": title,
                "country": country,
                "city": city,
                "location": f"{city}, Switzerland",
                "posted_at": posted_at,
                "url": detail_url,
                "job_req_sec_key": decode_js_string(match.group("key")),
                "total_available": total,
            }
        )
    return records, total


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_id: str,
    expected_title: str,
) -> dict[str, Any]:
    parts = urlsplit(page_url)
    if (
        parts.hostname != "career012.successfactors.eu"
        or f"career_job_req_id={expected_id}" not in parts.query
    ):
        raise PictetSwitzerlandParseError("Pictet detail page returned a different vacancy")
    page = Selector(page_html)
    heading = selector_text(page, "#candidateProfileTitle")
    if (
        not heading
        or expected_id not in heading
        or comparable_text(expected_title) not in comparable_text(heading)
    ):
        raise PictetSwitzerlandParseError("Pictet detail page is missing its vacancy heading")

    metadata = next(
        (
            item
            for item in page.css('div[tabindex="0"]')
            if "Requisition ID" in html_to_text(item.get())
            and expected_id in html_to_text(item.get())
        ),
        None,
    )
    values = (
        [optional_text(html_to_text(item.get())) for item in metadata.css("b")] if metadata else []
    )
    values = [value for value in values if value]
    if len(values) < 3 or comparable_text(values[1]) != "switzerland":
        raise PictetSwitzerlandParseError("Pictet detail page is not a Swiss vacancy")
    city = values[2]
    description_html = page.css(".joqReqDescription .externalPosting").get()
    description = html_to_text(description_html) if description_html else None
    if not description:
        raise PictetSwitzerlandParseError("Pictet detail page is missing its description")
    posted_ms = optional_text(page.css("#postedOnFastDate::attr(value)").get())
    posted_at = (
        datetime.fromtimestamp(int(posted_ms) / 1000, tz=UTC).date().isoformat()
        if posted_ms and posted_ms.isdigit()
        else None
    )
    return {
        "title": expected_title,
        "location": f"{city}, Switzerland",
        "posted_at": posted_at,
        "description": description,
    }


def decode_js_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError as exc:
        raise PictetSwitzerlandParseError("Pictet catalog contains an invalid string") from exc


def normalize_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%d/%m/%Y").replace(tzinfo=UTC).date().isoformat()
    except ValueError as exc:
        raise PictetSwitzerlandParseError(
            "Pictet catalog contains an invalid posting date"
        ) from exc


def deduplicate_pictet_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = optional_text(job.raw.get("id"))
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def extract_seniority(title: Any) -> str | None:
    text = comparable_text(title)
    if re.search(r"\b(head|lead|principal|director)\b", text):
        return "Lead"
    if re.search(r"\b(senior|sr\.)\b", text):
        return "Senior"
    if re.search(r"\b(junior|jr\.)\b", text):
        return "Junior"
    return None


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h[1-6]|li|ul|ol)>", "\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    text = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+|[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def selector_text(node: Any, selector: str) -> str | None:
    selected = node.css(selector).get()
    return optional_text(html_to_text(selected)) if selected else None


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    return re.sub(r"\n{3,}", "\n\n", text).strip() if text else None


def comparable_text(value: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip().casefold()


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = html.unescape(str(value)).strip()
    return normalized or None
