from __future__ import annotations

import json
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest, ParsedJob, ParserSearchResponse
from app.services.parsers.companies.base import DirectCompanyRequestError

WEBTOUCH_CAREERS_URL = "https://www.webtouch.ch/karriere"
WEBTOUCH_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-CH,de;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0 Safari/537.36"
    ),
}
WEBTOUCH_COLLECTION_ID = "785ffcb3-5518-43b8-bdca-466fd59a652e"
WEBTOUCH_FIELDS = {
    "title": "zOsEvNQTi",
    "intro": "aBacXVXtF",
    "location": "fREawOuR4",
    "employment_type": "piAkN6KRo",
    "description": "pK8IqAeG0",
    "apply_url": "J8bgVqu4U",
}
EMPLOYMENT_TYPES = {"pzCRQk_30": "Full-time"}
DETAIL_PATH_PATTERN = re.compile(r"^/karriere/([a-z0-9]+(?:-[a-z0-9]+)*)$")
SEARCH_INDEX_PATH_PATTERN = re.compile(r"^/sites/[A-Za-z0-9_-]+/searchIndex-[A-Za-z0-9_-]+\.json$")
JOIN_PATH_PATTERN = re.compile(r"^/companies/webtouchch/[0-9]+$")


class WebtouchParseError(DirectCompanyRequestError):
    pass


class WebtouchJobsParser:
    """Collect Webtouch's complete Framer CMS vacancy catalog."""

    parser_id = "webtouch"

    def __init__(
        self,
        *,
        base_url: str = WEBTOUCH_CAREERS_URL,
        timeout_seconds: float = 30.0,
        max_jobs: int = 100,
        detail_workers: int = 8,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_jobs = max(1, max_jobs)
        self.detail_workers = min(12, max(1, detail_workers))
        self.transport = transport

    def search(self, request: LinkedInSearchRequest) -> ParserSearchResponse:
        try:
            with httpx.Client(
                headers={**WEBTOUCH_HEADERS, "Referer": self.base_url},
                timeout=self.timeout_seconds,
                follow_redirects=True,
                transport=self.transport,
            ) as client:
                response = client.get(self.base_url)
                response.raise_for_status()
                search_index_url = parse_careers_html(
                    response.text,
                    page_url=str(response.url),
                    expected_url=self.base_url,
                )
                index_response = client.get(search_index_url)
                index_response.raise_for_status()
                records = parse_search_index(
                    index_response.json(),
                    base_url=self.base_url,
                    max_jobs=self.max_jobs,
                )
                self.enrich_records(client, records)
        except WebtouchParseError:
            raise
        except httpx.HTTPError as exc:
            raise DirectCompanyRequestError("Webtouch vacancy request failed") from exc
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise DirectCompanyRequestError("Webtouch vacancy parsing failed") from exc

        jobs = [normalize_job(record) for record in records]
        if request.deduplicate:
            jobs = deduplicate_webtouch_jobs(jobs)
        return ParserSearchResponse(
            parser=self.parser_id,
            status="completed",
            search_url=self.base_url,
            jobs=jobs,
            message=(f"Scanned {len(jobs)} Webtouch vacancies from the official Framer catalog"),
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
                    expected_slug=record["id"],
                    expected_title=record["title"],
                )
            except (httpx.HTTPError, WebtouchParseError, ValueError) as exc:
                record["detail_error"] = str(exc)
                return record, None

        with ThreadPoolExecutor(max_workers=min(self.detail_workers, len(records))) as executor:
            futures = [executor.submit(fetch_detail, record) for record in records]
            for future in as_completed(futures):
                record, detail = future.result()
                if detail is not None:
                    record["detail"] = detail


def parse_careers_html(page_html: str, *, page_url: str, expected_url: str) -> str:
    if not same_url(page_url, expected_url):
        raise WebtouchParseError("Webtouch career page returned unexpected content")
    page = Selector(page_html)
    canonicals = set(page.css('link[rel="canonical"]::attr(href)').getall())
    languages = set(page.css("html::attr(lang)").getall())
    titles = set(page.css('meta[property="og:title"]::attr(content)').getall())
    index_urls = set(page.css('meta[name="framer-search-index"]::attr(content)').getall())
    if (
        canonicals != {expected_url}
        or languages != {"de-CH"}
        or titles != {"Jobs im B2B Sales | Webtouch"}
        or len(index_urls) != 1
    ):
        raise WebtouchParseError("Webtouch career page has an unexpected identity")
    index_url = next(iter(index_urls))
    parts = urlsplit(index_url)
    if (
        parts.scheme != "https"
        or parts.hostname != "framerusercontent.com"
        or parts.query
        or parts.fragment
        or not SEARCH_INDEX_PATH_PATTERN.fullmatch(parts.path)
    ):
        raise WebtouchParseError("Webtouch career page has an invalid search index")
    return index_url


def parse_search_index(
    payload: Any,
    *,
    base_url: str,
    max_jobs: int,
) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise WebtouchParseError("Webtouch search index must be an object")
    base_path = urlsplit(base_url).path
    base_entry = payload.get(base_path)
    if (
        not isinstance(base_entry, dict)
        or optional_text(base_entry.get("title")) != "Jobs im B2B Sales | Webtouch"
        or base_entry.get("h1") != ["Werde Teil von Webtouch"]
    ):
        raise WebtouchParseError("Webtouch search index has an unexpected identity")

    records: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for path, entry in payload.items():
        if not isinstance(path, str):
            raise WebtouchParseError("Webtouch search index contains an invalid path")
        match = DETAIL_PATH_PATTERN.fullmatch(path)
        if not match:
            continue
        if not isinstance(entry, dict):
            raise WebtouchParseError("Webtouch search index contains an invalid vacancy")
        slug = match.group(1)
        headings = entry.get("h1")
        title = (
            optional_text(headings[0])
            if isinstance(headings, list) and len(headings) == 1
            else None
        )
        if not title or slug in seen_slugs:
            raise WebtouchParseError("Webtouch search index contains an incomplete vacancy")
        seen_slugs.add(slug)
        records.append(
            {
                "id": slug,
                "title": title,
                "url": urljoin(f"{site_origin(base_url)}/", path.lstrip("/")),
                "search_index_entry": dict(entry),
            }
        )

    if len(records) > max_jobs:
        raise WebtouchParseError(
            f"Webtouch catalog exceeds the configured limit of {max_jobs} vacancies"
        )
    records.sort(key=lambda item: item["id"])
    return records


def parse_detail_html(
    page_html: str,
    *,
    page_url: str,
    expected_url: str,
    expected_slug: str,
    expected_title: str,
) -> dict[str, Any]:
    if not same_url(page_url, expected_url):
        raise WebtouchParseError("Webtouch vacancy returned unexpected content")
    page = Selector(page_html)
    canonicals = set(page.css('link[rel="canonical"]::attr(href)').getall())
    languages = set(page.css("html::attr(lang)").getall())
    handovers = page.css('script[type="framer/handover"]#__framer__handoverData::text').getall()
    if canonicals != {expected_url} or languages != {"de-CH"} or len(handovers) != 1:
        raise WebtouchParseError("Webtouch vacancy has an unexpected identity")
    try:
        data = json.loads(handovers[0])
    except json.JSONDecodeError as exc:
        raise WebtouchParseError("Webtouch vacancy has invalid Framer data") from exc
    record = extract_cms_record(data, expected_slug=expected_slug)

    title = cms_scalar(record, "title", "string")
    location = cms_scalar(record, "location", "string")
    employment_code = cms_scalar(record, "employment_type", "enum")
    apply_url = normalize_apply_url(cms_scalar(record, "apply_url", "link"))
    intro = cms_richtext(record, "intro")
    body = cms_richtext(record, "description")
    employment_type = EMPLOYMENT_TYPES.get(employment_code)
    if (
        title != expected_title
        or not location
        or not employment_type
        or not apply_url
        or not intro
        or not body
    ):
        raise WebtouchParseError("Webtouch vacancy contains incomplete CMS data")
    return {
        "title": title,
        "location": location,
        "employment_type": employment_type,
        "apply_url": apply_url,
        "description": f"{intro}\n\n{body}",
        "cms_slug": expected_slug,
    }


def extract_cms_record(data: Any, *, expected_slug: str) -> dict[str, Any]:
    if not isinstance(data, list):
        raise WebtouchParseError("Webtouch vacancy has invalid Framer data")
    for value in data:
        if not isinstance(value, list) or not value or value[0] != "Map":
            continue
        pairs = value[1:]
        if len(pairs) % 2:
            continue
        for query_index, result_index in zip(pairs[::2], pairs[1::2], strict=True):
            query = indexed(data, query_index, str)
            results = indexed(data, result_index, list)
            parsed_query = parse_framer_query(query)
            if parsed_query.get("from") != WEBTOUCH_COLLECTION_ID:
                continue
            validate_framer_query(parsed_query, expected_slug=expected_slug)
            if len(results) != 1:
                raise WebtouchParseError("Webtouch vacancy has an unexpected CMS result")
            record = indexed(data, results[0], dict)
            expected_fields = set(WEBTOUCH_FIELDS.values())
            if set(record) != expected_fields:
                raise WebtouchParseError("Webtouch vacancy CMS fields changed")
            return {"data": data, "record": record}
    raise WebtouchParseError("Webtouch vacancy CMS record was not found")


def validate_framer_query(query: dict[str, Any], *, expected_slug: str) -> None:
    selections = query.get("select")
    selected_fields = (
        {
            item.get("name")
            for item in selections
            if isinstance(item, dict) and item.get("collection") == "vq0ovXxlM"
        }
        if isinstance(selections, list)
        else set()
    )
    where = query.get("where")
    slug = None
    if isinstance(where, dict):
        right = where.get("right")
        if isinstance(right, dict):
            slug = optional_text(right.get("value"))
    if selected_fields != set(WEBTOUCH_FIELDS.values()) or slug != expected_slug:
        raise WebtouchParseError("Webtouch vacancy has an unexpected CMS query")


def parse_framer_query(value: str) -> dict[str, Any]:
    try:
        parsed, _ = json.JSONDecoder().raw_decode(value)
    except json.JSONDecodeError as exc:
        raise WebtouchParseError("Webtouch vacancy has an invalid CMS query") from exc
    if not isinstance(parsed, dict):
        raise WebtouchParseError("Webtouch vacancy has an invalid CMS query")
    return parsed


def cms_scalar(record_wrapper: dict[str, Any], name: str, expected_type: str) -> str:
    data = record_wrapper["data"]
    record = record_wrapper["record"]
    descriptor = indexed(data, record[WEBTOUCH_FIELDS[name]], dict)
    value_type = indexed(data, descriptor.get("type"), str)
    value = indexed(data, descriptor.get("value"), str)
    if value_type != expected_type or not optional_text(value):
        raise WebtouchParseError("Webtouch vacancy has an invalid CMS value")
    return value.strip()


def cms_richtext(record_wrapper: dict[str, Any], name: str) -> str:
    data = record_wrapper["data"]
    record = record_wrapper["record"]
    descriptor = indexed(data, record[WEBTOUCH_FIELDS[name]], dict)
    value_type = indexed(data, descriptor.get("type"), str)
    pointer = indexed(data, descriptor.get("value"), dict)
    raw = indexed(data, pointer.get("pointer"), str)
    if value_type != "richtext":
        raise WebtouchParseError("Webtouch vacancy has an invalid rich-text value")
    try:
        tree = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WebtouchParseError("Webtouch vacancy has invalid rich-text data") from exc
    return framer_richtext_to_text(tree)


def indexed(data: list[Any], index: Any, expected_type: type[Any]) -> Any:
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(data):
        raise WebtouchParseError("Webtouch vacancy has an invalid Framer pointer")
    value = data[index]
    if not isinstance(value, expected_type):
        raise WebtouchParseError("Webtouch vacancy has an invalid Framer value")
    return value


def framer_richtext_to_text(tree: Any) -> str:
    def render(node: Any) -> str:
        if not isinstance(node, list) or not node:
            return ""
        if node[0] == 5:
            return node[1] if len(node) > 1 and isinstance(node[1], str) else ""
        if node[0] == 1:
            return "".join(render(child) for child in node[1:])
        if node[0] != 4 or len(node) < 2 or not isinstance(node[1], str):
            return ""
        tag = node[1]
        content = "".join(render(child) for child in node[3:])
        if tag == "br":
            return "\n"
        if tag == "li":
            return f"- {content.strip()}\n"
        if tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"}:
            return f"{content.strip()}\n"
        return content

    rendered = render(tree)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in rendered.splitlines()]
    compact: list[str] = []
    for line in lines:
        if line or (compact and compact[-1]):
            compact.append(line)
    return "\n".join(compact).strip()


def normalize_apply_url(value: str) -> str | None:
    parts = urlsplit(value)
    if (
        parts.scheme != "https"
        or parts.hostname != "join.com"
        or not JOIN_PATH_PATTERN.fullmatch(parts.path.rstrip("/"))
    ):
        return None
    return urlunsplit(("https", "join.com", parts.path.rstrip("/"), "", ""))


def normalize_job(record: dict[str, Any]) -> ParsedJob:
    detail = record.get("detail")
    detail = detail if isinstance(detail, dict) else {}
    return ParsedJob(
        source="webtouch",
        title=optional_text(detail.get("title")) or optional_text(record.get("title")),
        company="Webtouch GmbH",
        location=optional_text(detail.get("location")),
        url=optional_text(record.get("url")),
        apply_url=(optional_text(detail.get("apply_url")) or optional_text(record.get("url"))),
        employment_type=optional_text(detail.get("employment_type")),
        description=optional_multiline_text(detail.get("description")),
        raw=dict(record),
    )


def deduplicate_webtouch_jobs(jobs: Iterable[ParsedJob]) -> list[ParsedJob]:
    output: list[ParsedJob] = []
    seen: set[str] = set()
    for job in jobs:
        key = optional_text(job.url) or f"{job.title}|{job.company}"
        if key in seen:
            continue
        seen.add(key)
        output.append(job)
    return output


def optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    return normalized or None


def optional_multiline_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def site_origin(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def same_url(left: Any, right: Any) -> bool:
    if not isinstance(left, str) or not isinstance(right, str):
        return False
    left_parts = urlsplit(left)
    right_parts = urlsplit(right)
    return (
        left_parts.scheme.lower(),
        left_parts.netloc.lower(),
        left_parts.path.rstrip("/"),
        left_parts.query,
    ) == (
        right_parts.scheme.lower(),
        right_parts.netloc.lower(),
        right_parts.path.rstrip("/"),
        right_parts.query,
    )
