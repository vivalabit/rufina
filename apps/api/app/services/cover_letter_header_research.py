import ipaddress
import json
import re
import socket
from dataclasses import asdict, dataclass
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from lxml import html


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
LEGAL_LINK_MARKERS = (
    "career",
    "contact",
    "imprint",
    "impressum",
    "legal",
    "privacy",
    "about",
    "company",
)
LEGAL_SUFFIX_PATTERN = (
    r"(?:AG|GmbH|SA|S\.A\.|Ltd\.?|Limited|Inc\.?|Corporation|Corp\.?|"
    r"LLC|N\.V\.|B\.V\.|SE|SAS|Sàrl|SpA)"
)
COUNTRY_PATTERN = (
    r"Switzerland|Schweiz|Suisse|Svizzera|Germany|Deutschland|Austria|"
    r"Österreich|France|Italy|Italia|Netherlands|Nederland|Belgium|"
    r"United Kingdom|UK|United States|USA"
)
STREET_WORD_PATTERN = (
    r"strasse|straße|street|road|avenue|lane|drive|platz|weg|gasse|quai|"
    r"rue|route|via|viale|boulevard"
)
ADDRESS_PATTERN = re.compile(
    rf"(?P<street>(?:[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ.'’\-]*\s+){{0,3}}"
    rf"[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ.'’\-]*?(?i:{STREET_WORD_PATTERN})"
    rf"\s+\d+[A-Za-z]?)"
    rf"\s*,?\s*(?:CH-)?(?P<postal>\d{{4,6}})"
    rf"\s+(?P<city>[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ.'’\-\s]{{1,45}}?)"
    rf"\s*,\s*(?P<country>(?i:{COUNTRY_PATTERN}))\b",
)
COMPANY_PATTERN = re.compile(
    rf"\b(?P<name>[A-ZÀ-ÖØ-Þ][\wÀ-ÖØ-öø-ÿ&.'’+\-\s]{{1,80}}\s"
    rf"{LEGAL_SUFFIX_PATTERN})\b"
)


@dataclass(frozen=True)
class CoverLetterHeaderResearch:
    official_name: str
    address_line: str
    source_url: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def research_cover_letter_header(
    vacancy: dict[str, Any],
) -> CoverLetterHeaderResearch | None:
    source_urls = [
        str(vacancy.get(field) or "").strip()
        for field in ("applyUrl", "apply_url", "sourceUrl", "source_url")
    ]
    visited: set[str] = set()
    for source_url in source_urls:
        normalized = normalize_url(source_url)
        if not source_url or normalized in visited:
            continue
        visited.add(normalized)
        result = _research_cover_letter_header_from_url(source_url)
        if result is not None:
            return result
    return None


def _research_cover_letter_header_from_url(
    source_url: str,
) -> CoverLetterHeaderResearch | None:
    try:
        job_html, final_job_url = fetch_public_html(source_url)
    except (ValueError, httpx.HTTPError, OSError):
        return None

    official_name, address_line = extract_company_header(job_html)
    if official_name and address_line:
        return CoverLetterHeaderResearch(
            official_name=official_name,
            address_line=address_line,
            source_url=final_job_url,
        )

    official_hosts = official_company_hosts(job_html, final_job_url)
    candidate_urls = official_company_links(
        job_html,
        final_job_url,
        allowed_hosts=official_hosts,
    )
    visited = {normalize_url(final_job_url)}
    for candidate_url in candidate_urls[:3]:
        normalized = normalize_url(candidate_url)
        if normalized in visited:
            continue
        visited.add(normalized)
        try:
            candidate_html, final_candidate_url = fetch_public_html(candidate_url)
        except (ValueError, httpx.HTTPError, OSError):
            continue
        candidate_name, candidate_address = extract_company_header(candidate_html)
        official_name = official_name or candidate_name
        if candidate_address:
            return CoverLetterHeaderResearch(
                official_name=official_name,
                address_line=candidate_address,
                source_url=final_candidate_url,
            )
        legal_urls = legal_information_links(
            candidate_html,
            final_candidate_url,
            allowed_hosts=official_hosts,
        )
        for legal_url in legal_urls[:4]:
            normalized = normalize_url(legal_url)
            if normalized in visited:
                continue
            visited.add(normalized)
            try:
                legal_html, final_legal_url = fetch_public_html(legal_url)
            except (ValueError, httpx.HTTPError, OSError):
                continue
            legal_name, legal_address = extract_company_header(legal_html)
            official_name = official_name or legal_name
            if legal_address:
                return CoverLetterHeaderResearch(
                    official_name=official_name,
                    address_line=legal_address,
                    source_url=final_legal_url,
                )
    return None


def fetch_public_html(url: str) -> tuple[str, str]:
    current_url = url
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
        follow_redirects=False,
        timeout=5.0,
        trust_env=False,
    ) as client:
        for _ in range(4):
            validate_public_url(current_url)
            response = client.get(current_url)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location", "").strip()
                if not location:
                    response.raise_for_status()
                current_url = urljoin(current_url, location)
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").casefold()
            if content_type and "html" not in content_type:
                raise ValueError("Company research URL did not return HTML")
            return response.text, str(response.url)
    raise ValueError("Company research URL redirected too many times")


def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError("Company research URL is not a public HTTP URL")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    for result in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM):
        address = ipaddress.ip_address(result[4][0])
        if not address.is_global:
            raise ValueError("Company research URL resolves to a non-public address")


def extract_company_header(page_html: str) -> tuple[str, str]:
    try:
        tree = html.fromstring(page_html)
    except (TypeError, ValueError):
        return "", ""

    official_name = ""
    address_line = ""
    for payload in json_ld_payloads(tree):
        for item in nested_dicts(payload):
            item_type = normalized_schema_type(item.get("@type"))
            if item_type in {"jobposting", "organization", "corporation"}:
                organization = item.get("hiringOrganization")
                if isinstance(organization, dict):
                    official_name = clean_text(organization.get("name")) or official_name
                elif item_type in {"organization", "corporation"}:
                    official_name = clean_text(item.get("legalName") or item.get("name")) or official_name
                address = (
                    organization.get("address")
                    if isinstance(organization, dict)
                    else item.get("address")
                )
                address_line = format_schema_address(address) or address_line
            if item_type in {"place", "postaladdress"}:
                address_line = format_schema_address(
                    item.get("address") if item_type == "place" else item
                ) or address_line

    hiring_names = tree.xpath(
        '//*[@itemprop="hiringOrganization"]/@content'
        ' | //*[@itemprop="hiringOrganization"]//*[@itemprop="name"]/@content'
        ' | //*[@itemprop="hiringOrganization"]//*[@itemprop="name"]/text()'
    )
    official_name = first_clean(hiring_names) or official_name

    microdata_address = {
        field: first_clean(
            tree.xpath(
                f'//*[@itemprop="{field}"]/@content'
                f' | //*[@itemprop="{field}"]/text()'
            )
        )
        for field in (
            "streetAddress",
            "postalCode",
            "addressLocality",
            "addressRegion",
            "addressCountry",
        )
    }
    address_line = format_schema_address(microdata_address) or address_line

    page_text = clean_text(" ".join(tree.xpath("//body//text()")))
    company_match = COMPANY_PATTERN.search(page_text)
    if company_match:
        official_name = clean_text(company_match.group("name"))
    address_match = ADDRESS_PATTERN.search(page_text)
    if address_match:
        address_line = ", ".join(
            (
                clean_text(address_match.group("street")),
                " ".join(
                    (
                        clean_text(address_match.group("postal")),
                        clean_text(address_match.group("city")),
                    )
                ),
                clean_text(address_match.group("country")),
            )
        )
    return official_name, address_line


def format_schema_address(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    street = clean_text(value.get("streetAddress"))
    postal = clean_text(value.get("postalCode"))
    city = clean_text(value.get("addressLocality"))
    region = clean_text(value.get("addressRegion"))
    country_value = value.get("addressCountry")
    country = (
        clean_text(country_value.get("name"))
        if isinstance(country_value, dict)
        else clean_text(country_value)
    )
    if not street or not re.search(r"\d", street) or not postal:
        return ""
    locality = " ".join(part for part in (postal, city) if part)
    parts = [street, locality]
    if region and region.casefold() not in {city.casefold(), country.casefold()}:
        parts.append(region)
    if country:
        parts.append(country)
    return ", ".join(part for part in parts if part)


def official_company_hosts(page_html: str, base_url: str) -> set[str]:
    base_host = (urlparse(base_url).hostname or "").casefold()
    hosts = {base_host}
    base_domain = registrable_domain(base_host)
    try:
        tree = html.fromstring(page_html)
    except (TypeError, ValueError):
        return hosts
    for href in tree.xpath("//a[@href]/@href"):
        absolute = urljoin(base_url, str(href))
        host = (urlparse(absolute).hostname or "").casefold()
        if host and registrable_domain(host) == base_domain:
            hosts.add(host)
    return hosts


def official_company_links(
    page_html: str,
    base_url: str,
    *,
    allowed_hosts: set[str],
) -> list[str]:
    links = ranked_links(page_html, base_url, allowed_hosts=allowed_hosts)
    base_host = (urlparse(base_url).hostname or "").casefold()
    return sorted(
        links,
        key=lambda url: (
            (urlparse(url).hostname or "").casefold() == base_host,
            not any(marker in url.casefold() for marker in ("career", "about", "company")),
        ),
    )


def legal_information_links(
    page_html: str,
    base_url: str,
    *,
    allowed_hosts: set[str],
) -> list[str]:
    links = [
        url
        for url in ranked_links(page_html, base_url, allowed_hosts=allowed_hosts)
        if any(marker in url.casefold() for marker in LEGAL_LINK_MARKERS)
    ]
    priority_markers = ("global-privacy", "privacy", "imprint", "impressum", "legal", "contact")
    return sorted(
        links,
        key=lambda url: next(
            (
                index
                for index, marker in enumerate(priority_markers)
                if marker in url.casefold()
            ),
            len(priority_markers),
        ),
    )


def ranked_links(
    page_html: str,
    base_url: str,
    *,
    allowed_hosts: set[str],
) -> list[str]:
    try:
        tree = html.fromstring(page_html)
    except (TypeError, ValueError):
        return []
    links: list[tuple[int, str]] = []
    seen: set[str] = set()
    for anchor in tree.xpath("//a[@href]"):
        href = str(anchor.get("href") or "").strip()
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"http", "https"} or host not in allowed_hosts:
            continue
        normalized = normalize_url(absolute)
        if normalized in seen:
            continue
        seen.add(normalized)
        label = clean_text(" ".join(anchor.itertext())).casefold()
        haystack = f"{absolute.casefold()} {label}"
        score = sum(marker in haystack for marker in LEGAL_LINK_MARKERS)
        if score:
            links.append((-score, absolute))
    return [url for _, url in sorted(links)]


def json_ld_payloads(tree: Any) -> Iterable[Any]:
    for raw in tree.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            yield json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue


def nested_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from nested_dicts(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from nested_dicts(nested)


def normalized_schema_type(value: Any) -> str:
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, str)), "")
    return re.sub(r"[^a-z]", "", str(value or "").casefold())


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def first_clean(values: Iterable[Any]) -> str:
    return next((cleaned for value in values if (cleaned := clean_text(value))), "")


def registrable_domain(host: str) -> str:
    parts = [part for part in host.casefold().split(".") if part]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host.casefold()


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return parsed._replace(fragment="").geturl()
