from __future__ import annotations

import html
import re
from collections import defaultdict
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

CLAVIS_IT_JOBS_URL = "https://www.clavisit.com/karriere/jobs"
CLAVIS_IT_COMPANY = "clavis IT ag"
CLAVIS_IT_PAGE_TITLE = "Jobs - clavis IT ag"
CLAVIS_IT_APPLY_EMAIL = "bewerbung@clavisit.com"
CLAVIS_IT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en-CH;q=0.8,en;q=0.7",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0 Safari/537.36"
    ),
}
REGULAR_JOB_PATH_PATTERN = re.compile(r"^/(?:karriere/jobs|jobs)/([a-z0-9]+(?:-[a-z0-9]+)*)$")
SMARTRECRUITERS_APPLY_PATH_PATTERN = re.compile(
    r"^/oneclick-ui/company/ClavisITAg/publication/"
    r"([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$",
    re.IGNORECASE,
)
WORKLOAD_PATTERN = re.compile(r"^(\d{1,3})\s*[-–]\s*(\d{1,3})\s*%$")
TRAINING_DURATION_PATTERN = re.compile(r"^\d+\s+Tage?$", re.IGNORECASE)
GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


class ClavisItParseError(DirectCompanyRequestError):
    pass


class ClavisItJobsParser:
    """Collect Clavis IT's complete visible Liferay vacancy catalog."""

    parser_id = "clavis_it"

    def __init__(
        self,
        *,
        base_url: str = CLAVIS_IT_JOBS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 6,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers=CLAVIS_IT_HEADERS,
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                records = parse_listing_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except ClavisItParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Clavis IT vacancy request failed") from exc
        except (TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Clavis IT vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_clavis_it_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(
                f"Scanned {len(jobs)} Clavis IT vacancies from the complete "
                "visible official careers catalog"
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
                detail = parse_detail_html(
                    response.text,
                    page_url=str(response.url),
                    expected_record=record,
                )
                return record, detail
            except (httpx.HTTPError, ClavisItParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_listing_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    expected = canonical_listing_url(expected_url)
    if not expected or canonical_listing_url(page_url) != expected:
        raise ClavisItParseError("Clavis IT careers page returned an unexpected page")

    page = Selector(page_html)
    canonical_urls = {
        canonical_listing_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    logo_alts = {
        value
        for raw in page.css(".header__logo img::attr(alt)").getall()
        if (value := optional_text(raw))
    }
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de-DE"
        or selector_text(page, "title") != CLAVIS_IT_PAGE_TITLE
        or optional_text(page.css('meta[property="og:title"]::attr(content)').get())
        != CLAVIS_IT_PAGE_TITLE
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != CLAVIS_IT_COMPANY
        or canonical_urls != {expected}
        or logo_alts != {"clavis IT ag Logo"}
    ):
        raise ClavisItParseError("Clavis IT careers page has an unexpected identity")

    catalogs = page.css("#content .lfr-layout-structure-item-jobs .jobs")
    headings = {value for node in page.css("#content h1") if (value := selector_text(node))}
    if len(catalogs) != 1 or "Offene Stellen" not in headings:
        raise ClavisItParseError("Clavis IT careers page is missing its vacancy catalog")
    catalog = catalogs[0]
    cards = catalog.css(":scope > .job")
    if len(cards) > max_jobs:
        raise ClavisItParseError(
            f"Clavis IT exposes {len(cards)} jobs, above the configured limit of {max_jobs}"
        )
    if not cards and not re.search(
        r"keine\s+(?:aktuellen\s+)?(?:offenen\s+)?stellen",
        selector_text(catalog) or "",
        re.IGNORECASE,
    ):
        raise ClavisItParseError("Clavis IT careers page has no recognizable vacancy state")

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for index, card in enumerate(cards):
        titles = card.css(".job__title")
        descriptions = card.css(".job__description")
        locations = card.css(".job__location")
        workloads = card.css(".job__workload")
        actions = card.css("a.job__action[href]")
        if not all(
            len(values) == 1 for values in (titles, descriptions, locations, workloads, actions)
        ):
            raise ClavisItParseError("Clavis IT catalog contains an incomplete vacancy card")

        title = selector_text(titles[0])
        description = selector_text(descriptions[0])
        location = normalize_location(selector_text(locations[0]))
        workload = normalize_workload(selector_text(workloads[0]))
        url = canonical_job_url(
            urljoin(page_url, optional_text(actions[0].css("::attr(href)").get()) or "")
        )
        job_id = job_id_from_url(url)
        kind = "training" if url and urlsplit(url).path == "/schnupperlehre" else "vacancy"
        if (
            not title
            or not description
            or len(description) < 40
            or not location
            or not workload
            or not url
            or not job_id
            or selector_text(actions[0]) != "Mehr erfahren"
            or (kind == "training" and not title.startswith("Schnupperlehre"))
            or (kind == "vacancy" and not WORKLOAD_PATTERN.fullmatch(workload))
        ):
            raise ClavisItParseError("Clavis IT catalog contains an invalid vacancy card")
        if job_id in seen_ids or url in seen_urls:
            raise ClavisItParseError("Clavis IT catalog contains duplicate vacancies")
        seen_ids.add(job_id)
        seen_urls.add(url)
        records.append(
            {
                "id": job_id,
                "kind": kind,
                "title": title,
                "company": CLAVIS_IT_COMPANY,
                "location": location,
                "employment_type": workload,
                "listing_description": description,
                "url": url,
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
    expected_title = optional_text(expected_record.get("title"))
    kind = optional_text(expected_record.get("kind"))
    if (
        not expected_url
        or not expected_title
        or kind not in {"vacancy", "training"}
        or canonical_job_url(page_url) != expected_url
    ):
        raise ClavisItParseError("Clavis IT detail page returned a different vacancy")

    page = Selector(page_html)
    canonical_urls = {
        canonical_job_url(urljoin(page_url, raw))
        for raw in page.css('link[rel="canonical"]::attr(href)').getall()
    }
    document_title = selector_text(page, "title")
    og_title = optional_text(page.css('meta[property="og:title"]::attr(content)').get())
    og_url = canonical_job_url(page.css('meta[property="og:url"]::attr(content)').get())
    if (
        optional_text(page.css("html::attr(lang)").get()) != "de-DE"
        or not document_title
        or og_title != document_title
        or optional_text(page.css('meta[property="og:site_name"]::attr(content)').get())
        != CLAVIS_IT_COMPANY
        or canonical_urls != {expected_url}
        or og_url != expected_url
        or not detail_title_matches(document_title, expected_title, kind=kind)
    ):
        raise ClavisItParseError("Clavis IT detail page has an unexpected identity")

    descriptions = [
        node
        for node in page.css('#content .component-paragraph[data-lfr-editable-id="element-text"]')
        if len(node.css("li")) >= 5 and len(selector_text(node) or "") >= 500
    ]
    if len(descriptions) != 1:
        raise ClavisItParseError("Clavis IT detail page is missing its vacancy description")
    description = extract_description(descriptions[0], kind=kind)

    if kind == "training":
        apply_urls = {
            value
            for raw in page.css('#content a[href^="mailto:"]::attr(href)').getall()
            if (value := normalize_training_apply_url(raw))
        }
        if apply_urls != {f"mailto:{CLAVIS_IT_APPLY_EMAIL}"}:
            raise ClavisItParseError(
                "Clavis IT training page is missing its official application email"
            )
        return {
            "id": expected_record["id"],
            "kind": kind,
            "title": expected_title,
            "company": CLAVIS_IT_COMPANY,
            "location": expected_record.get("location"),
            "employment_type": expected_record.get("employment_type"),
            "description": description,
            "url": expected_url,
            "apply_url": apply_urls.pop(),
        }

    metadata = parse_vacancy_metadata(page)
    detail_workload = normalize_workload(metadata["Pensum"])
    detail_location = normalize_location(metadata["Arbeitsort"])
    if (
        detail_workload != expected_record.get("employment_type")
        or not detail_location
        or not locations_overlap(detail_location, expected_record.get("location"))
        or metadata["Vertrag"].casefold() != "festanstellung"
        or "deutsch" not in metadata["Sprache"].casefold()
    ):
        raise ClavisItParseError("Clavis IT detail page has inconsistent vacancy metadata")

    apply_urls = {
        value
        for raw in page.css(
            '#content a[href*="jobs.smartrecruiters.com/oneclick-ui/"]::attr(href)'
        ).getall()
        if (value := canonical_smartrecruiters_apply_url(raw))
    }
    if len(apply_urls) != 1:
        raise ClavisItParseError(
            "Clavis IT detail page is missing its direct SmartRecruiters application"
        )
    apply_url = apply_urls.pop()
    return {
        "id": expected_record["id"],
        "kind": kind,
        "application_id": smartrecruiters_application_id(apply_url),
        "title": expected_title,
        "company": CLAVIS_IT_COMPANY,
        "location": expected_record.get("location"),
        "employment_type": detail_workload,
        "posted_at": parse_german_date(metadata["Veröffentlicht"]),
        "contract": metadata["Vertrag"],
        "languages": metadata["Sprache"],
        "starts_at": metadata["Start"],
        "description": description,
        "url": expected_url,
        "apply_url": apply_url,
    }


def parse_vacancy_metadata(page: Any) -> dict[str, str]:
    required = {"Veröffentlicht", "Pensum", "Vertrag", "Sprache", "Arbeitsort", "Start"}
    values: defaultdict[str, set[str]] = defaultdict(set)
    for paragraph in page.css("#content p"):
        strong = paragraph.css("strong")
        label = (selector_text(strong[0]) or "").rstrip(": ") if len(strong) == 1 else None
        text = selector_text(paragraph)
        if not label or label not in required or not text:
            continue
        value = optional_text(re.sub(rf"^{re.escape(label)}\s*:\s*", "", text))
        if value:
            values[label].add(value)
    if set(values) != required or any(len(items) != 1 for items in values.values()):
        raise ClavisItParseError("Clavis IT detail page has incomplete vacancy metadata")
    metadata = {label: next(iter(items)) for label, items in values.items()}
    if not parse_german_date(metadata["Veröffentlicht"]):
        raise ClavisItParseError("Clavis IT detail page has an invalid publication date")
    return metadata


def extract_description(node: Any, *, kind: str) -> str:
    strong_values = {
        (selector_text(item) or "").rstrip(": ").casefold() for item in node.css("strong, b")
    }
    if kind == "training":
        required = {"was dich erwartet", "was du mitbringen solltest"}
    else:
        required = {"das ist deine aufgabe", "was du mitbringen solltest"}
    if not required.issubset(strong_values):
        raise ClavisItParseError("Clavis IT detail page has incomplete vacancy sections")

    blocks: list[str] = []
    for child in node.css(":scope > p, :scope > ul, :scope > strong, :scope > b"):
        tag = optional_text(getattr(child, "tag", None))
        if tag == "ul":
            items = [value for item in child.css("li") if (value := selector_text(item))]
            if items:
                blocks.append("\n".join(f"- {item}" for item in items))
        else:
            text = selector_text(child)
            if text:
                blocks.append(text)
    description = "\n\n".join(blocks)
    if len(description) < 500 or description.count("- ") < 5:
        raise ClavisItParseError("Clavis IT detail page has an incomplete vacancy description")
    return description


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    public_url = optional_text(record.get("url"))
    return ParsedJob(
        source="clavis_it",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company=CLAVIS_IT_COMPANY,
        location=optional_text(detail.get("location")) or optional_text(record.get("location")),
        url=public_url,
        apply_url=optional_text(detail.get("apply_url")) or public_url,
        posted_at=optional_text(detail.get("posted_at")),
        employment_type=optional_text(detail.get("employment_type"))
        or optional_text(record.get("employment_type")),
        description=optional_multiline_text(detail.get("description"))
        or optional_multiline_text(record.get("listing_description")),
        raw=dict(record),
    )


def normalize_location(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = [optional_text(part) for part in re.split(r"\s*[/,]\s*", text)]
    values = [part for part in parts if part]
    allowed = {"herisau", "herisau ar", "winterthur", "remote"}
    if not values or any(item.casefold() not in allowed for item in values):
        return None
    if not any(item.casefold() in {"herisau", "herisau ar", "winterthur"} for item in values):
        return None
    normalized = ["Remote" if item.casefold() == "remote" else item for item in values]
    return f"{' / '.join(normalized)}, Switzerland"


def locations_overlap(first: Any, second: Any) -> bool:
    def physical(value: Any) -> set[str]:
        text = optional_text(value) or ""
        return {item for item in ("herisau", "winterthur") if item in text.casefold()}

    return bool(physical(first) & physical(second))


def normalize_workload(value: Any) -> str | None:
    text = optional_text(value)
    match = WORKLOAD_PATTERN.fullmatch(text or "")
    if match:
        lower = int(match.group(1))
        upper = int(match.group(2))
        return f"{lower}–{upper}%" if 1 <= lower <= upper <= 100 else None
    return text if text and TRAINING_DURATION_PATTERN.fullmatch(text) else None


def parse_german_date(value: Any) -> str | None:
    text = optional_text(value)
    match = re.fullmatch(r"(\d{1,2})\.\s+([A-Za-zÄÖÜäöü]+)\s+(\d{4})", text or "")
    if not match:
        return None
    month = GERMAN_MONTHS.get(match.group(2).casefold())
    day = int(match.group(1))
    year = int(match.group(3))
    if not month or not 1 <= day <= 31:
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def detail_title_matches(document_title: str, listing_title: str, *, kind: str) -> bool:
    title = re.sub(r"\s+-\s+clavis IT ag$", "", document_title, flags=re.IGNORECASE)
    if kind == "training":
        return "schnupperlehre" in title.casefold() and "schnupperlehre" in listing_title.casefold()
    return role_signature(title) == role_signature(listing_title)


def role_signature(value: Any) -> str:
    text = optional_text(value) or ""
    text = re.sub(r"\((?:[mwd]/){2}[mwd]\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\s*%", "", text)
    return re.sub(r"[^a-z0-9]+", "", text.casefold())


def canonical_listing_url(value: Any) -> str | None:
    url = canonical_content_url(value)
    return url if url and urlsplit(url).path == "/karriere/jobs" else None


def canonical_job_url(value: Any) -> str | None:
    url = canonical_content_url(value)
    if not url:
        return None
    path = urlsplit(url).path
    return url if path == "/schnupperlehre" or REGULAR_JOB_PATH_PATTERN.fullmatch(path) else None


def canonical_content_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "www.clavisit.com"
        or parts.query
        or parts.fragment
    ):
        return None
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", "www.clavisit.com", path, "", ""))


def job_id_from_url(value: Any) -> str | None:
    url = canonical_job_url(value)
    if not url:
        return None
    path = urlsplit(url).path
    if path == "/schnupperlehre":
        return "schnupperlehre"
    match = REGULAR_JOB_PATH_PATTERN.fullmatch(path)
    return match.group(1) if match else None


def canonical_smartrecruiters_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text:
        return None
    parts = urlsplit(text)
    match = SMARTRECRUITERS_APPLY_PATH_PATTERN.fullmatch(parts.path)
    query = parse_qs(parts.query, keep_blank_values=True)
    if (
        parts.scheme != "https"
        or parts.netloc.casefold() != "jobs.smartrecruiters.com"
        or not match
        or query != {"dcr_ci": ["ClavisITAg"]}
        or parts.fragment
    ):
        return None
    return text


def smartrecruiters_application_id(value: Any) -> str | None:
    url = canonical_smartrecruiters_apply_url(value)
    match = SMARTRECRUITERS_APPLY_PATH_PATTERN.fullmatch(urlsplit(url).path) if url else None
    return match.group(1).lower() if match else None


def normalize_training_apply_url(value: Any) -> str | None:
    text = optional_text(value)
    if not text or not text.casefold().startswith("mailto:"):
        return None
    email = text.split(":", 1)[1].split("?", 1)[0].strip().casefold()
    return f"mailto:{email}" if email == CLAVIS_IT_APPLY_EMAIL else None


def deduplicate_clavis_it_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    seen: set[str] = set()
    unique: list[ParsedJob] = []
    for job in jobs:
        detail = job.raw.get("detail")
        application_id = (
            optional_text(detail.get("application_id")) if isinstance(detail, dict) else None
        )
        key = application_id or optional_text(job.raw.get("id")) or job.url or ""
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(job)
    return unique


def selector_text(node: Any, selector: str | None = None) -> str | None:
    selected = node.css(selector) if selector else [node]
    if not selected:
        return None
    return optional_text(" ".join(str(value) for value in selected[0].css("::text").getall()))


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
