from __future__ import annotations

import html
import json
import math
import re
from collections.abc import Iterable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

UBS_STUDENTS_GRADUATES_BASE_URL = (
    "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?"
    "partnerid=25008&siteid=5131&PageType=searchResults&"
    "SearchType=linkquery&LinkID=15232"
    "#keyWordSearch=&locationSearch=Switzerland"
)
UBS_SEARCH_API_URL = (
    "https://jobs.ubs.com/TgNewUI/Search/Ajax/ProcessSortAndShowMoreJobs"
)
UBS_HEADERS = {
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
DETAIL_DESCRIPTION_FIELDS = (
    "jobdescription",
    "formtext58",
    "formtext59",
    "formtext63",
)


class UbsStudentsGraduatesParseError(DirectCompanyRequestError):
    pass


class UbsStudentsGraduatesJobsParser:
    """Collect Swiss UBS student and graduate roles from Infinite Talent."""

    parser_id = "ubs_students_graduates"

    def __init__(
        self,
        *,
        base_url: str = UBS_STUDENTS_GRADUATES_BASE_URL,
        api_url: str = UBS_SEARCH_API_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 10,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_url = api_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.detail_workers = max(1, detail_workers)
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        request_url = self.base_url.split("#", maxsplit=1)[0]
        try:
            with httpx.Client(
                headers=UBS_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(request_url)
                response.raise_for_status()
                records, metadata = parse_listing_html(response.text)
                records.extend(
                    self.fetch_remaining_pages(
                        client,
                        metadata=metadata,
                        referer=request_url,
                    )
                )
                validate_complete_catalog(records, total_count=metadata["total_count"])
                records = [record for record in records if is_swiss_vacancy(record)]
                self.enrich_records(client, records, referer=request_url)
        except UbsStudentsGraduatesParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("UBS vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("UBS vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_ubs_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} UBS Students & Graduates vacancies "
                "in Switzerland"
            ),
        )

    def fetch_remaining_pages(
        self,
        client: httpx.Client,
        *,
        metadata: dict[str, Any],
        referer: str,
    ) -> list[dict[str, Any]]:
        total_pages = math.ceil(metadata["total_count"] / metadata["page_size"])
        if total_pages > self.max_pages:
            raise UbsStudentsGraduatesParseError(
                "UBS vacancy catalog exceeds the configured page limit"
            )

        records: list[dict[str, Any]] = []
        for page_number in range(2, total_pages + 1):
            response = client.post(
                self.api_url,
                json=build_page_payload(metadata, page_number=page_number),
                headers={"Referer": referer},
            )
            response.raise_for_status()
            page_records, page_total = parse_search_response(response.json())
            if page_total not in (None, metadata["total_count"]):
                raise UbsStudentsGraduatesParseError(
                    "UBS vacancy API changed its result count during pagination"
                )
            records.extend(page_records)
        return records

    def enrich_records(
        self,
        client: httpx.Client,
        records: list[dict[str, Any]],
        *,
        referer: str,
    ) -> None:
        if not records:
            return

        def fetch_detail(
            record: dict[str, Any],
        ) -> tuple[dict[str, Any], dict[str, Any] | None]:
            detail_url = optional_text(record.get("Link"))
            job_id = extract_job_id(record)
            if not detail_url or not job_id:
                return record, None
            try:
                response = client.get(detail_url, headers={"Referer": referer})
                response.raise_for_status()
                return record, parse_detail_html(response.text, expected_job_id=job_id)
            except (
                httpx.HTTPError,
                UbsStudentsGraduatesParseError,
                ValueError,
            ) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_html(page_html: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    preload = extract_preload_payload(page_html)
    search_response = preload.get("searchResultsResponse")
    smart_raw = preload.get("SmartSearchJSONValue")
    if not isinstance(search_response, dict) or not isinstance(smart_raw, str):
        raise UbsStudentsGraduatesParseError(
            "UBS listing page is missing its search contract"
        )
    smart_search = json.loads(smart_raw)
    if not isinstance(smart_search, dict):
        raise UbsStudentsGraduatesParseError(
            "UBS listing page contains invalid search metadata"
        )

    records, total_count = parse_search_response(search_response)
    if total_count is None:
        raise UbsStudentsGraduatesParseError(
            "UBS listing page is missing the vacancy count"
        )
    page_size = positive_int(search_response.get("PageSize")) or len(records)
    if total_count > 0 and page_size <= 0:
        raise UbsStudentsGraduatesParseError(
            "UBS listing page is missing its page size"
        )

    sort_fields = search_response.get("SortFields")
    sort_type = None
    if isinstance(sort_fields, list) and sort_fields and isinstance(sort_fields[0], dict):
        sort_type = optional_text(sort_fields[0].get("Name"))

    page = Selector(page_html)
    link_id = optional_text(page.css("#linkId::attr(value)").get())
    encrypted_session = optional_text(smart_search.get("EncryptedSessionValue"))
    keyword_fields = optional_text(smart_search.get("KeywordCustomSolrFields"))
    location_fields = optional_text(smart_search.get("LocationCustomSolrFields"))
    partner_id = positive_int(smart_search.get("PartnerId"))
    site_id = positive_int(smart_search.get("SiteId"))
    if (
        not link_id
        or not encrypted_session
        or not keyword_fields
        or not location_fields
        or not partner_id
        or not site_id
    ):
        raise UbsStudentsGraduatesParseError(
            "UBS listing page contains incomplete pagination metadata"
        )

    return records, {
        "total_count": total_count,
        "page_size": page_size,
        "partner_id": partner_id,
        "site_id": site_id,
        "link_id": link_id,
        "encrypted_session": encrypted_session,
        "keyword_fields": keyword_fields,
        "location_fields": location_fields,
        "sort_type": sort_type or "LastUpdated",
    }


def extract_preload_payload(page_html: str) -> dict[str, Any]:
    raw = Selector(page_html).css("#preLoadJSON::attr(value)").get()
    if not raw:
        raise UbsStudentsGraduatesParseError(
            "UBS page is missing the preloaded JSON payload"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise UbsStudentsGraduatesParseError(
            "UBS page contains an invalid preloaded JSON payload"
        )
    return payload


def parse_search_response(payload: Any) -> tuple[list[dict[str, Any]], int | None]:
    if not isinstance(payload, dict):
        raise UbsStudentsGraduatesParseError("UBS vacancy API returned invalid JSON")
    total_count = positive_int(payload.get("JobsCount"))
    jobs_container = payload.get("Jobs")
    if jobs_container is None and total_count == 0:
        return [], 0
    if not isinstance(jobs_container, dict) or not isinstance(
        jobs_container.get("Job"), list
    ):
        raise UbsStudentsGraduatesParseError(
            "UBS vacancy API returned an invalid jobs collection"
        )

    records: list[dict[str, Any]] = []
    for item in jobs_container["Job"]:
        if not isinstance(item, dict):
            raise UbsStudentsGraduatesParseError(
                "UBS vacancy API returned an invalid job record"
            )
        validate_listing_record(item)
        records.append(dict(item))
    return records, total_count


def validate_listing_record(record: dict[str, Any]) -> None:
    job_id = extract_job_id(record)
    title = question_value(record, "jobtitle")
    location = question_value(record, "formtext23")
    detail_url = optional_text(record.get("Link"))
    linked_job_id = extract_job_id_from_url(detail_url)
    if (
        not job_id
        or not title
        or not location
        or not detail_url
        or linked_job_id != job_id
    ):
        raise UbsStudentsGraduatesParseError(
            "UBS vacancy API returned an incomplete job record"
        )


def validate_complete_catalog(
    records: Sequence[dict[str, Any]],
    *,
    total_count: int,
) -> None:
    if len(records) != total_count:
        raise UbsStudentsGraduatesParseError(
            "UBS vacancy pagination did not return the complete catalog"
        )
    ids = [extract_job_id(record) for record in records]
    if len(set(ids)) != len(ids):
        raise UbsStudentsGraduatesParseError(
            "UBS vacancy catalog contains duplicate vacancy IDs"
        )


def build_page_payload(metadata: dict[str, Any], *, page_number: int) -> dict[str, Any]:
    return {
        "partnerId": metadata["partner_id"],
        "siteId": metadata["site_id"],
        "keyword": "",
        "location": "",
        "keywordCustomSolrFields": metadata["keyword_fields"],
        "locationCustomSolrFields": metadata["location_fields"],
        "facetFilterFields": None,
        "linkId": metadata["link_id"],
        "Latitude": 0,
        "Longitude": 0,
        "facetfilterfields": {"Facet": None},
        "powersearchoptions": {"PowerSearchOption": []},
        "SortType": metadata["sort_type"],
        "pageNumber": page_number,
        "encryptedSessionValue": metadata["encrypted_session"],
    }


def parse_detail_html(page_html: str, *, expected_job_id: str) -> dict[str, Any]:
    preload = extract_preload_payload(page_html)
    detail = preload.get("Jobdetails")
    if not isinstance(detail, dict):
        raise UbsStudentsGraduatesParseError(
            "UBS detail page is missing its vacancy payload"
        )
    job_id = detail_question_value(detail, "reqid")
    title = optional_text(detail.get("Title")) or detail_question_value(
        detail, "jobtitle"
    )
    location = detail_question_value(detail, "formtext23")
    if job_id != expected_job_id or not title or not location:
        raise UbsStudentsGraduatesParseError(
            "UBS detail page contains mismatched vacancy data"
        )

    description_parts: list[str] = []
    for field_name in DETAIL_DESCRIPTION_FIELDS:
        entry = detail_question(detail, field_name)
        value = optional_text(entry.get("AnswerValue")) if entry else None
        if not value:
            continue
        label = optional_text(entry.get("QuestionName")) or field_name
        description_parts.append(f"{label}\n\n{html_to_text(value)}")

    return {
        "job_id": job_id,
        "title": html.unescape(title),
        "location": html.unescape(location),
        "posted_at": normalize_date(detail_question_value(detail, "lastupdated")),
        "department": detail_question_value(detail, "department"),
        "function_category": detail_question_value(detail, "formtext21"),
        "city": detail_question_value(detail, "formtext2"),
        "reference": detail_question_value(detail, "autoreq"),
        "description": "\n\n".join(description_parts) or None,
        "questions": detail.get("JobDetailQuestions"),
    }


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    title = optional_text(detail.get("title")) or question_value(record, "jobtitle")
    location = optional_text(detail.get("location")) or question_value(
        record, "formtext23"
    )
    public_url = optional_text(record.get("Link"))
    listing_description = question_value(record, "jobdescription")
    posted_at = optional_text(detail.get("posted_at")) or normalize_date(
        question_value(record, "lastupdated", actual=True)
        or question_value(record, "lastupdated")
    )
    program_type = extract_program_type(title, optional_text(detail.get("description")))

    raw = dict(record)
    raw["detail"] = detail
    return ParsedJob(
        source="ubs_students_graduates",
        title=html.unescape(title) if title else None,
        company="UBS",
        location=html.unescape(location) if location else "Switzerland",
        url=public_url,
        apply_url=public_url,
        posted_at=posted_at,
        employment_type=program_type,
        seniority=program_type,
        description=(
            optional_multiline_text(detail.get("description"))
            or html_to_text(listing_description or "")
            or None
        ),
        raw=raw,
    )


def question_value(record: dict[str, Any], name: str, *, actual: bool = False) -> str | None:
    questions = record.get("Questions")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)):
        return None
    for question in questions:
        if not isinstance(question, dict):
            continue
        question_name = optional_text(question.get("QuestionName"))
        if question_name and question_name.casefold() == name.casefold():
            key = "ActualValueFromSolar" if actual else "Value"
            return optional_text(question.get(key))
    return None


def detail_question(detail: dict[str, Any], name: str) -> dict[str, Any] | None:
    questions = detail.get("JobDetailQuestions")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)):
        return None
    for question in questions:
        if not isinstance(question, dict):
            continue
        zone = optional_text(question.get("VerityZone"))
        if zone and zone.casefold() == name.casefold():
            return question
    return None


def detail_question_value(detail: dict[str, Any], name: str) -> str | None:
    question = detail_question(detail, name)
    return optional_text(question.get("AnswerValue")) if question else None


def extract_job_id(record: dict[str, Any]) -> str | None:
    value = question_value(record, "reqid")
    return value if value and value.isdigit() else None


def extract_job_id_from_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    values = parse_qs(urlsplit(text).query).get("jobid", [])
    job_id = optional_text(values[0]) if values else None
    return job_id if job_id and job_id.isdigit() else None


def is_swiss_vacancy(record: dict[str, Any]) -> bool:
    location = question_value(record, "formtext23")
    return bool(location and location.casefold().startswith("switzerland"))


def extract_program_type(title: str | None, description: str | None) -> str:
    text = f"{title or ''} {description or ''}".casefold()
    if "intern" in text or "praktikum" in text or "stage" in text:
        return "Internship"
    if "graduate" in text or "trainee" in text:
        return "Graduate program"
    return "Students & graduates"


def deduplicate_ubs_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        key = extract_job_id(job.raw) or extract_job_id_from_url(job.url) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T.*)?", text):
        return text[:10]
    try:
        return (
            datetime.strptime(text, "%d-%b-%Y")
            .replace(tzinfo=UTC)
            .date()
            .isoformat()
        )
    except ValueError:
        return text


def html_to_text(value: str) -> str:
    text = re.sub(r"(?i)<br\s*/?>", "\n", value)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def optional_multiline_text(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
