from __future__ import annotations

import html
import json
import re
import ssl
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CSL_SWITZERLAND_JOBS_BASE_URL = (
    "https://jobs.csl.com/en/jobs?"
    "filterrific%5Bsearch_by_title_and_description%5D=&"
    "filterrific%5Bwith_location3%5D=switzerland&"
    "filterrific%5Bwith_location2%5D=&"
    "filterrific%5Bwith_location1%5D=&"
    "filterrific%5Bwith_multiple_employment_types%5D%5B%5D=&"
    "filterrific%5Bwith_remote%5D=0&"
    "filterrific%5Bsorted_by%5D=newest"
)
CSL_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CH,en;q=0.9,de-CH;q=0.8,de;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    ),
}
RESULT_RANGE_PATTERN = re.compile(
    r"Showing\s+(\d[\d,]*)\s+to\s+(\d[\d,]*)\s+of\s+(\d[\d,]*)\s+results",
    re.IGNORECASE,
)
JOB_PATH_PATTERN = re.compile(
    r"^/en/jobs/[a-z0-9-]+-en-r-(\d+)(?:-[a-z0-9-]+)?$",
    re.IGNORECASE,
)
REFERENCE_PATTERN = re.compile(r"^R-(\d+)$", re.IGNORECASE)
WORKDAY_APPLY_PATH = re.compile(
    r"^/CSL_External/job/.+_R-(\d+)(?:-\d+)?/apply$",
    re.IGNORECASE,
)
EXPECTED_COUNTRY = "Switzerland"
# jobs.csl.com currently serves unrelated GlobalSign certificates after its DigiCert
# leaf certificate. Supplying the public intermediate named by the leaf preserves full
# hostname and chain validation without disabling TLS verification.
GEOTRUST_TLS_RSA_CA_G1 = """-----BEGIN CERTIFICATE-----
MIIEjTCCA3WgAwIBAgIQDQd4KhM/xvmlcpbhMf/ReTANBgkqhkiG9w0BAQsFADBh
MQswCQYDVQQGEwJVUzEVMBMGA1UEChMMRGlnaUNlcnQgSW5jMRkwFwYDVQQLExB3
d3cuZGlnaWNlcnQuY29tMSAwHgYDVQQDExdEaWdpQ2VydCBHbG9iYWwgUm9vdCBH
MjAeFw0xNzExMDIxMjIzMzdaFw0yNzExMDIxMjIzMzdaMGAxCzAJBgNVBAYTAlVT
MRUwEwYDVQQKEwxEaWdpQ2VydCBJbmMxGTAXBgNVBAsTEHd3dy5kaWdpY2VydC5j
b20xHzAdBgNVBAMTFkdlb1RydXN0IFRMUyBSU0EgQ0EgRzEwggEiMA0GCSqGSIb3
DQEBAQUAA4IBDwAwggEKAoIBAQC+F+jsvikKy/65LWEx/TMkCDIuWegh1Ngwvm4Q
yISgP7oU5d79eoySG3vOhC3w/3jEMuipoH1fBtp7m0tTpsYbAhch4XA7rfuD6whU
gajeErLVxoiWMPkC/DnUvbgi74BJmdBiuGHQSd7LwsuXpTEGG9fYXcbTVN5SATYq
DfbexbYxTMwVJWoVb6lrBEgM3gBBqiiAiy800xu1Nq07JdCIQkBsNpFtZbIZhsDS
fzlGWP4wEmBQ3O67c+ZXkFr2DcrXBEtHam80Gp2SNhou2U5U7UesDL/xgLK6/0d7
6TnEVMSUVJkZ8VeZr+IUIlvoLrtjLbqugb0T3OYXW+CQU0kBAgMBAAGjggFAMIIB
PDAdBgNVHQ4EFgQUlE/UXYvkpOKmgP792PkA76O+AlcwHwYDVR0jBBgwFoAUTiJU
IBiV5uNu5g/6+rkS7QYXjzkwDgYDVR0PAQH/BAQDAgGGMB0GA1UdJQQWMBQGCCsG
AQUFBwMBBggrBgEFBQcDAjASBgNVHRMBAf8ECDAGAQH/AgEAMDQGCCsGAQUFBwEB
BCgwJjAkBggrBgEFBQcwAYYYaHR0cDovL29jc3AuZGlnaWNlcnQuY29tMEIGA1Ud
HwQ7MDkwN6A1oDOGMWh0dHA6Ly9jcmwzLmRpZ2ljZXJ0LmNvbS9EaWdpQ2VydEds
b2JhbFJvb3RHMi5jcmwwPQYDVR0gBDYwNDAyBgRVHSAAMCowKAYIKwYBBQUHAgEW
HGh0dHBzOi8vd3d3LmRpZ2ljZXJ0LmNvbS9DUFMwDQYJKoZIhvcNAQELBQADggEB
AIIcBDqC6cWpyGUSXAjjAcYwsK4iiGF7KweG97i1RJz1kwZhRoo6orU1JtBYnjzB
c4+/sXmnHJk3mlPyL1xuIAt9sMeC7+vreRIF5wFBC0MCN5sbHwhNN1JzKbifNeP5
ozpZdQFmkCo+neBiKR6HqIA+LMTMCMMuv2khGGuPHmtDze4GmEGZtYLyF8EQpa5Y
jPuV6k2Cr/N3XxFpT3hRpt/3usU/Zb9wfKPtWpoznZ4/44c1p9rzFcZYrWkj3A+7
TNBJE0GmP2fhXhP1D/XVfIW/h0yCJGEiV9Glm/uGOa3DXHlmbAcxSyCRraG+ZBkA
7h4SeM6Y8l/7MBRpPCz6l8Y=
-----END CERTIFICATE-----"""


class CslSwitzerlandParseError(DirectCompanyRequestError):
    pass


class CslSwitzerlandJobsParser:
    """Collect CSL's complete country-filtered Swiss vacancy catalog."""

    parser_id = "csl_switzerland"

    def __init__(
        self,
        *,
        base_url: str = CSL_SWITZERLAND_JOBS_BASE_URL,
        timeout_seconds: float = 30.0,
        max_pages: int = 50,
        max_catalog_passes: int = 3,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_pages = max(1, max_pages)
        self.max_catalog_passes = max(1, max_catalog_passes)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**CSL_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                verify=csl_ssl_context(),
                transport=self.transport,
            ) as client:
                records, pages_fetched, total = self.collect_listing_records(client)
                self.enrich_records(client, records)
        except CslSwitzerlandParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("CSL vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("CSL vacancy parsing failed") from exc

        jobs = [self.normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_jobs(jobs)
        request_label = "request" if pages_fetched == 1 else "requests"
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} CSL Switzerland vacancies from {total} catalog "
                f"records across {pages_fetched} page {request_label}"
            ),
        )

    def listing_url(self, *, page: int) -> str:
        params: list[tuple[str, str]] = [
            ("filterrific[search_by_title_and_description]", ""),
            ("filterrific[with_location3]", "switzerland"),
            ("filterrific[with_location2]", ""),
            ("filterrific[with_location1]", ""),
            ("filterrific[with_multiple_employment_types][]", ""),
            ("filterrific[with_remote]", "0"),
            ("filterrific[sorted_by]", "newest"),
        ]
        if page > 1:
            params.append(("page", str(page)))
        base = httpx.URL(self.base_url).copy_with(query=None)
        return str(base.copy_with(params=httpx.QueryParams(params)))

    def fetch_listing_page(
        self,
        client: httpx.Client,
        *,
        page: int,
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        response = client.get(self.listing_url(page=page))
        response.raise_for_status()
        records, metadata = parse_listing_html(response.text, page_url=str(response.url))
        return records, metadata

    def collect_listing_records(
        self,
        client: httpx.Client,
    ) -> tuple[list[dict[str, Any]], int, int]:
        records_by_id: dict[str, dict[str, Any]] = {}
        expected_total: int | None = None
        pages_fetched = 0

        for catalog_pass in range(1, self.max_catalog_passes + 1):
            first_records, first_metadata = self.fetch_listing_page(client, page=1)
            pages_fetched += 1
            total = first_metadata["total"]
            page_size = first_metadata["end"] - first_metadata["start"] + 1
            if first_metadata["start"] != 1 or page_size <= 0:
                raise CslSwitzerlandParseError("CSL pagination returned an invalid first page")
            if expected_total is None:
                expected_total = total
            elif total != expected_total:
                raise CslSwitzerlandParseError(
                    "CSL catalog changed its result count during pagination"
                )

            required_pages = max(1, ceil(total / page_size))
            if required_pages > self.max_pages:
                raise CslSwitzerlandParseError(
                    f"CSL exposes {required_pages} pages, above the configured limit of "
                    f"{self.max_pages}"
                )

            page_results = [first_records]
            for page in range(2, required_pages + 1):
                records, metadata = self.fetch_listing_page(client, page=page)
                pages_fetched += 1
                expected_start = (page - 1) * page_size + 1
                expected_end = min(page * page_size, total)
                if (
                    metadata["total"] != expected_total
                    or metadata["start"] != expected_start
                    or metadata["end"] != expected_end
                ):
                    raise CslSwitzerlandParseError(
                        "CSL pagination returned an unexpected result range"
                    )
                page_results.append(records)

            for page_records in page_results:
                for record in page_records:
                    normalized = dict(record)
                    normalized["listing_pass"] = catalog_pass
                    normalized["total_available"] = expected_total
                    records_by_id.setdefault(record["url"], normalized)

            if len(records_by_id) == expected_total:
                return list(records_by_id.values()), pages_fetched, expected_total
            if len(records_by_id) > expected_total:
                raise CslSwitzerlandParseError(
                    "CSL catalog changed while pages were collected"
                )

        raise CslSwitzerlandParseError(
            f"CSL returned {len(records_by_id)} unique vacancies but declared "
            f"{expected_total or 0}"
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
                    expected_reference=record["reference"],
                    expected_title=record["title"],
                    expected_company=record["company"],
                    expected_location=record["location"],
                    expected_employment_type=record["employment_type"],
                    expected_posted_at=record["posted_at"],
                )
                return record, detail
            except (httpx.HTTPError, CslSwitzerlandParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records) or 1)) as pool:
            futures = [pool.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail

    def normalize_job(self, record: dict[str, Any]) -> ParsedJob:
        detail = record.get("detail")
        detail = detail if isinstance(detail, dict) else {}
        return ParsedJob(
            source=self.parser_id,
            title=optional_text(detail.get("title")) or record["title"],
            company=optional_text(detail.get("company")) or record["company"],
            location=optional_text(detail.get("location")) or record["location"],
            url=record["url"],
            apply_url=optional_text(detail.get("apply_url")),
            posted_at=optional_text(detail.get("posted_at")) or record["posted_at"],
            employment_type=(
                optional_text(detail.get("employment_type")) or record["employment_type"]
            ),
            seniority=None,
            description=optional_multiline_text(detail.get("description")),
            raw=dict(record),
        )


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    page = Selector(page_html)
    result_range = html_to_text(page.css("#results-count p").get())
    range_match = RESULT_RANGE_PATTERN.fullmatch(result_range or "")
    results = page.css("#results")
    cards = page.css("#results > ul[role='list'] > li").getall()
    if not results.get() or not range_match or not cards:
        raise CslSwitzerlandParseError("CSL listing page is missing its search results")

    metadata = {
        "start": parse_count(range_match.group(1)),
        "end": parse_count(range_match.group(2)),
        "total": parse_count(range_match.group(3)),
    }
    if (
        metadata["start"] < 1
        or metadata["end"] < metadata["start"]
        or metadata["total"] < metadata["end"]
        or len(cards) != metadata["end"] - metadata["start"] + 1
    ):
        raise CslSwitzerlandParseError("CSL listing returned inconsistent result metadata")

    records: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for card_html in cards:
        card = Selector(card_html)
        links = [optional_text(value) for value in card.css("a::attr(href)").getall()]
        links = [value for value in links if value]
        values = [html_to_text(value) for value in card.css("p").getall()]
        time_values = [
            optional_text(value) for value in card.css("time::attr(datetime)").getall()
        ]
        time_values = [value for value in time_values if value]
        if len(links) != 1 or len(values) != 8 or len(time_values) != 1:
            raise CslSwitzerlandParseError("CSL listing contains an incomplete vacancy")
        title, employment_type, category, family, company, location, reference, posted_label = (
            values
        )
        job_id = job_id_from_url(links[0])
        reference_match = REFERENCE_PATTERN.fullmatch(reference or "")
        posted_at = normalize_date(time_values[0])
        if (
            not job_id
            or not reference_match
            or reference_match.group(1) != job_id
            or not title
            or not employment_type
            or not category
            or not family
            or not company
            or not company.casefold().startswith("csl")
            or not location
            or not location.casefold().endswith(f", {EXPECTED_COUNTRY}".casefold())
            or not posted_at
            or not posted_label
            or not posted_label.casefold().startswith("posted on ")
            or links[0] in seen_urls
        ):
            raise CslSwitzerlandParseError(
                "CSL listing contains a malformed or non-Swiss vacancy"
            )
        seen_urls.add(links[0])
        records.append(
            {
                "id": job_id,
                "reference": f"R-{job_id}",
                "title": title,
                "company": company,
                "location": location,
                "employment_type": employment_type,
                "category": category,
                "family": family,
                "posted_at": posted_at,
                "url": links[0],
                "listing_page_url": page_url,
            }
        )
    return records, metadata


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_reference: str,
    expected_title: str,
    expected_company: str,
    expected_location: str,
    expected_employment_type: str,
    expected_posted_at: str,
) -> dict[str, Any]:
    page = Selector(page_html)
    canonical_values = [
        optional_text(value) for value in page.css('link[rel="canonical"]::attr(href)').getall()
    ]
    canonical_values = [value for value in canonical_values if value]
    title_values = [html_to_text(value) for value in page.css("main h1").getall()]
    title_values = [value for value in title_values if value]
    structured_values = page.css('script[type="application/ld+json"]::text').getall()
    apply_values = [
        optional_text(value) for value in page.css("a.apply-button::attr(href)").getall()
    ]
    apply_values = sorted({value for value in apply_values if value})
    descriptions = [html_to_text(value) for value in page.css("main .description").getall()]
    descriptions = [value for value in descriptions if value]
    if (
        len(canonical_values) != 1
        or expected_title not in title_values
        or len(structured_values) != 1
        or len(apply_values) != 1
        or len(descriptions) != 1
    ):
        raise CslSwitzerlandParseError("CSL detail page is missing required vacancy data")

    try:
        posting = json.loads(str(structured_values[0]), strict=False)
    except json.JSONDecodeError as exc:
        raise CslSwitzerlandParseError("CSL detail page has invalid JobPosting data") from exc
    if not isinstance(posting, dict) or posting.get("@type") != "JobPosting":
        raise CslSwitzerlandParseError("CSL detail page has invalid JobPosting data")

    identifier = posting.get("identifier")
    organization = posting.get("hiringOrganization")
    location = posting.get("jobLocation")
    address = location.get("address") if isinstance(location, dict) else None
    company = optional_text(identifier.get("name")) if isinstance(identifier, dict) else None
    reference = optional_text(identifier.get("value")) if isinstance(identifier, dict) else None
    detail_location = structured_location(address)
    employment_type = structured_employment_type(posting.get("employmentType"))
    description = html_to_text(posting.get("description"))
    apply_url = valid_apply_url(apply_values[0], expected_reference=expected_reference)
    canonical = canonical_values[0]
    posted_at = normalize_date(posting.get("datePosted"))
    if (
        canonical != expected_url
        or normalize_job_url(page_url) != expected_url
        or optional_text(html.unescape(str(posting.get("title", "")))) != expected_title
        or reference != expected_reference
        or company != expected_company
        or not isinstance(organization, dict)
        or optional_text(organization.get("name")) != "CSL"
        or detail_location != expected_location
        or employment_type != expected_employment_type
        or posted_at != expected_posted_at
        or not description
        or description != descriptions[0]
        or not apply_url
    ):
        raise CslSwitzerlandParseError("CSL detail page is incomplete or inconsistent")
    return {
        "id": expected_reference,
        "title": expected_title,
        "company": company,
        "location": detail_location,
        "url": canonical,
        "apply_url": apply_url,
        "posted_at": posted_at,
        "employment_type": employment_type,
        "description": description,
    }


def job_id_from_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = JOB_PATH_PATTERN.fullmatch(parts.path)
    if (
        parts.scheme == "https"
        and parts.netloc.casefold() == "jobs.csl.com"
        and match
        and not parts.query
        and not parts.fragment
    ):
        return match.group(1)
    return None


def normalize_job_url(value: Any) -> str | None:
    text = optional_text(value)
    return text if job_id_from_url(text) else None


def valid_apply_url(value: Any, *, expected_reference: str) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    query = parse_qs(parts.query)
    job_ids = query.get("job_id", [])
    if (
        parts.scheme == "https"
        and parts.netloc.casefold() == "olivia.paradox.ai"
        and parts.path == "/co/CSL17/Job"
        and len(job_ids) == 1
        and optional_text(job_ids[0])
        and query.get("posting_type") == ["1"]
        and set(query) == {"job_id", "posting_type"}
        and not parts.fragment
    ):
        return text
    workday_match = WORKDAY_APPLY_PATH.fullmatch(parts.path)
    reference_match = REFERENCE_PATTERN.fullmatch(expected_reference)
    if (
        parts.scheme == "https"
        and parts.netloc.casefold() == "csl.wd1.myworkdayjobs.com"
        and workday_match
        and reference_match
        and workday_match.group(1) == reference_match.group(1)
        and not parts.query
        and not parts.fragment
    ):
        return text
    return None


def structured_location(value: Any) -> str | None:
    if not isinstance(value, dict) or optional_text(value.get("addressCountry")) != "CH":
        return None
    city = optional_text(value.get("addressLocality"))
    region = optional_text(value.get("addressRegion"))
    if not city:
        return None
    return ", ".join(part for part in (city, region, EXPECTED_COUNTRY) if part)


def structured_employment_type(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not re.fullmatch(r"[A-Z]+(?:_[A-Z]+)*", text):
        return None
    return text.replace("_", " ").title()


def parse_count(value: str) -> int:
    return int(value.replace(",", ""))


def csl_ssl_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=GEOTRUST_TLS_RSA_CA_G1)
    return context


def normalize_date(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).date().isoformat()
    except ValueError:
        return None


def deduplicate_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        job_id = optional_text(job.url)
        if not job_id or job_id in seen:
            continue
        seen.add(job_id)
        unique.append(job)
    return unique


def html_to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"(?is)<(style|script)(?:\s[^>]*)?>.*?</\1>", "", text)
    text = re.sub(r"(?i)<li(?:\s[^>]*)?>", "- ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|h1|h2|h3|h4|h5|h6|li|ul|ol)>", "\n", text)
    return optional_multiline_text(html.unescape(re.sub(r"<[^>]+>", "", text)))


def optional_multiline_text(value: Any) -> str | None:
    if value is None:
        return None
    text = (
        str(value)
        .replace("\u200b", "")
        .replace("\xa0", " ")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() or None


def optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return re.sub(r"[\s\u200b]+", " ", str(value)).strip() or None
