import socket

import pytest

from app.services.cover_letter_header_research import (
    extract_company_header,
    official_company_hosts,
    research_cover_letter_header,
    validate_public_url,
)


JOB_HTML = """
<html>
  <body>
    <div itemscope itemtype="https://schema.org/JobPosting">
      <meta itemprop="hiringOrganization" content="Sonova AG">
      <span itemprop="jobLocation">
        <meta itemprop="streetAddress" content="Staefa, Switzerland">
      </span>
    </div>
    <a href="https://www.sonova.com/en/careers">Careers</a>
  </body>
</html>
"""

CAREERS_HTML = """
<html>
  <body>
    <a href="/canada/en/global-privacy-policy">Global Privacy Policy</a>
  </body>
</html>
"""

PRIVACY_HTML = """
<html>
  <body>
    Sonova AG is incorporated under the laws of Switzerland, with its registered
    address at Laubisrütistrasse 28, 8712 Stäfa, Switzerland.
  </body>
</html>
"""


def test_research_follows_only_official_links_to_find_legal_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        "https://jobs.sonova.com/job/1418735133": (
            JOB_HTML,
            "https://jobs.sonova.com/job/1418735133",
        ),
        "https://www.sonova.com/en/careers": (
            CAREERS_HTML,
            "https://www.sonova.com/en/careers",
        ),
        "https://www.sonova.com/canada/en/global-privacy-policy": (
            PRIVACY_HTML,
            "https://www.sonova.com/canada/en/global-privacy-policy",
        ),
    }

    monkeypatch.setattr(
        "app.services.cover_letter_header_research.fetch_public_html",
        lambda url: pages[url],
    )

    result = research_cover_letter_header(
        {"sourceUrl": "https://jobs.sonova.com/job/1418735133"}
    )

    assert result is not None
    assert result.official_name == "Sonova AG"
    assert result.address_line == (
        "Laubisrütistrasse 28, 8712 Stäfa, Switzerland"
    )
    assert result.source_url.endswith("/global-privacy-policy")


def test_json_ld_company_and_full_address_are_extracted() -> None:
    page = """
    <script type="application/ld+json">
    {
      "@type": "JobPosting",
      "hiringOrganization": {"@type": "Organization", "name": "Example Holding AG"},
      "jobLocation": {
        "@type": "Place",
        "address": {
          "@type": "PostalAddress",
          "streetAddress": "Exampleweg 7",
          "postalCode": "8000",
          "addressLocality": "Zürich",
          "addressCountry": "Switzerland"
        }
      }
    }
    </script>
    """

    assert extract_company_header(page) == (
        "Example Holding AG",
        "Exampleweg 7, 8000 Zürich, Switzerland",
    )


def test_official_hosts_exclude_unrelated_domains() -> None:
    hosts = official_company_hosts(
        JOB_HTML + '<a href="https://attacker.example/privacy">Privacy</a>',
        "https://jobs.sonova.com/job/1",
    )

    assert hosts == {"jobs.sonova.com", "www.sonova.com"}


def test_public_url_validation_rejects_private_dns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )

    with pytest.raises(ValueError, match="non-public"):
        validate_public_url("https://example.com/private")
