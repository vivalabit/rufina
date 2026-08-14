from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from app.core.settings import Settings
from app.models.job_search import JobSearchManualRunRequest
from app.models.parsers import LinkedInSearchRequest
from app.services.job_search_execution import parsed_job_to_stored_job
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.isolutions import (
    IsolutionsJobsParser,
    parse_breezy_html,
    parse_detail_html,
)
from app.services.vacancy_search import create_vacancy_search_runner

BASE_URL = "https://www.isolutions.test/en/career/#module-1396"
SITE_URL = "https://www.isolutions.ch/en/"


def organization_schema() -> str:
    payload = {
        "@context": "http://schema.org",
        "@type": "Organization",
        "url": SITE_URL,
        "logo": "https://www.isolutions.ch/media/bwpp3qmx/power_gradient.svg",
        "contactPoint": [
            {
                "@type": "ContactPoint",
                "telephone": "0041 31 560 88 88",
                "contactType": "customer service",
            }
        ],
    }
    return json.dumps(payload)


def page_head(
    page_url: str,
    *,
    language: str = "en-US",
    title: str | None = None,
) -> str:
    title_meta = f'<meta property="og:title" content="{title}">' if title else ""
    return f"""
    <head>
      <meta name="msapplication-starturl" content="{page_url}">
      <meta property="og:url" content="{page_url}">
      {title_meta}
      <link rel="alternate" hreflang="en-us" href="{page_url}">
      <script type="application/ld+json">{organization_schema()}</script>
    </head>
    """


def footer(*, zurich_postcode: str = "8058 Zürich") -> str:
    return f"""
    <section class="c-footer">
      <div class="c-footer__address-block">Schanzenstrasse 4c 3008 Bern</div>
      <div class="c-footer__address-block">Güterstrasse 144 4053 Basel</div>
      <div class="c-footer__address-block">The Circle 38 {zurich_postcode}</div>
    </section>
    """


def filters(*, consulting_name: str = "Consulting") -> str:
    departments = {
        "1501": "Sales",
        "1502": "Development",
        "1618": "Infrastructure",
        "6250": "Managed Cloud Services",
        "1619": consulting_name,
    }
    locations = {"1257": "Bern", "1258": "Basel", "1259": "Zürich"}

    def fieldset(name: str, options: dict[str, str]) -> str:
        buttons = "".join(
            f'<button class="c-select__option" data-toggle=".filter-{key}">{value}</button>'
            for key, value in options.items()
        )
        return f"""
        <fieldset class="js-multi-filter">
          <span class="c-select__value">{name}</span>{buttons}
        </fieldset>
        """

    return fieldset("Fields", departments) + fieldset("Locations", locations)


def listing_card(
    slug: str,
    *,
    title: str,
    department: str,
    department_id: str,
    location_ids: tuple[str, ...] = ("1257", "1259", "1258"),
    locations: str = "Bern, Zürich, Basel",
) -> str:
    filter_classes = " ".join(f"filter-{value}" for value in (*location_ids, department_id))
    return f"""
    <a href="/en/career/{slug}/" title="{title}"
       class="c-layout c-job-list__row__container c-section js-load-more-item
              filter-departments filter-locations {filter_classes}">
      <div class="c-layout--md row">
        <div class="col-12 col-md-8">
          <h4 class="h4">{title}</h4><p class="c-text">{department}</p>
        </div>
        <div class="col-auto">
          <p class="c-text">Location</p><p class="c-text">{locations}</p>
        </div>
      </div>
    </a>
    """


def listing_html(
    cards: list[str],
    *,
    consulting_name: str = "Consulting",
    zurich_postcode: str = "8058 Zürich",
) -> str:
    page_url = "https://www.isolutions.test/en/career/"
    return f"""
    <html lang="en-US">
      {page_head(page_url)}
      <body>
        <main>
          <section id="module-1396" class="c-job-list" data-load-more-increase="6">
            <h3 class="c-section-heading">Jobs</h3>
            <h2 class="h2">Vacancies for you</h2>
            <form class="c-filter">{filters(consulting_name=consulting_name)}</form>
            <div class="c-job-list__table">{"".join(cards)}</div>
          </section>
        </main>
        {footer(zurich_postcode=zurich_postcode)}
      </body>
    </html>
    """


def detail_html(
    slug: str,
    *,
    title: str,
    personio_id: str,
    apply_url: str | None = None,
) -> str:
    page_url = f"https://www.isolutions.test/en/career/{slug}/"
    application_url = apply_url or (
        f"https://isolutions.jobs.personio.com/job/{personio_id}/apply?_pc=3114117#apply"
    )
    return f"""
    <html lang="en-US">
      {page_head(page_url, title=title)}
      <body>
        <main>
          <section class="c-headline">
            <div class="c-headline__title"><h1>{title}</h1></div>
            <div class="c-headline__text-container">
              <div class="c-link__group">
                <a href="#module-2001" title="Job Description">Job Description</a>
              </div>
              <a class="c-button c-button--brand" title="Apply now"
                 href="{application_url}">Apply now</a>
            </div>
          </section>
          <section id="module-2001">
            <h3>Job Description</h3>
            <h2>Shape the digital future with us.</h2>
            <div class="c-rte"><p>Join a team that openly shares knowledge.</p></div>
          </section>
          <section class="requirements">
            <div class="c-text__col"><div class="c-rte">
              <h2>This is what you get up for in the morning:</h2>
              <ul><li>Build modern Microsoft solutions.</li></ul>
            </div></div>
            <div class="c-text__col"><div class="c-rte">
              <h2>We would like you to:</h2>
              <ul><li>Bring excellent German and good English.</li></ul>
            </div></div>
          </section>
          <section><a title="Apply now" href="{application_url}">Apply now</a></section>
        </main>
        {footer()}
      </body>
    </html>
    """


def personio_html(
    *,
    personio_id: str,
    title: str,
    posted_at: str = "2026-08-03",
    employment_type: list[str] | None = None,
) -> str:
    payload = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "identifier": {
            "@type": "PropertyValue",
            "name": "isolutions",
            "value": f"{personio_id}-303401",
        },
        "hiringOrganization": {"@type": "Organization", "name": "isolutions"},
        "jobLocation": [
            {
                "@type": "Place",
                "address": {"addressRegion": region, "addressCountry": "CH"},
            }
            for region in ("Zürich", "Basel", "Bern")
        ],
        "datePosted": posted_at,
        "employmentType": employment_type or ["FULL_TIME"],
    }
    return f"""
    <html><body>
      <script type="application/ld+json">{json.dumps(payload)}</script>
    </body></html>
    """


def breezy_html(*, title: str = "Enterprise M365 Engineer") -> str:
    payload = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": title,
        "hiringOrganization": {"@type": "Organization", "name": "isolutions"},
        "jobLocation": {
            "@type": "Place",
            "address": {"@type": "PostalAddress", "addressCountry": "CH"},
        },
        "datePosted": "2022-11-01",
        "employmentType": "FULL_TIME",
    }
    return f'<script type="application/ld+json">{json.dumps(payload)}</script>'


def catalog_fixture() -> list[str]:
    return [
        listing_card(
            "junior-technical-consultant-digital-workplace",
            title="Junior Technical Consultant - Digital Workplace",
            department="Consulting",
            department_id="1619",
        ),
        listing_card(
            "software-engineer-customer-experience",
            title="Software Engineer – Customer Experience",
            department="Development",
            department_id="1502",
            location_ids=("1257", "1258", "1259"),
            locations="Bern, Basel, Zürich",
        ),
    ]


def test_isolutions_collects_complete_catalog_and_enriches_personio_data() -> None:
    calls: list[str] = []
    details = {
        "/en/career/junior-technical-consultant-digital-workplace/": (
            "Junior Technical Consultant - Digital Workplace",
            "2738670",
        ),
        "/en/career/software-engineer-customer-experience/": (
            "Software Engineer – Customer Experience",
            "2716981",
        ),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.url.host}{request.url.path}")
        if request.url.path == "/en/career/":
            return httpx.Response(200, text=listing_html(catalog_fixture()), request=request)
        if request.url.host == "www.isolutions.test":
            title, personio_id = details[request.url.path]
            return httpx.Response(
                200,
                text=detail_html(
                    request.url.path.rstrip("/").split("/")[-1],
                    title=title,
                    personio_id=personio_id,
                ),
                request=request,
            )
        personio_id = request.url.path.split("/")[-1]
        title = next(value[0] for value in details.values() if value[1] == personio_id)
        return httpx.Response(
            200,
            text=personio_html(personio_id=personio_id, title=title),
            request=request,
        )

    result = IsolutionsJobsParser(
        base_url=BASE_URL,
        detail_workers=1,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest(results_limit=1))

    assert calls == [
        "www.isolutions.test/en/career/",
        "www.isolutions.test/en/career/junior-technical-consultant-digital-workplace/",
        "isolutions.jobs.personio.com/job/2738670",
        "www.isolutions.test/en/career/software-engineer-customer-experience/",
        "isolutions.jobs.personio.com/job/2716981",
    ]
    assert result.status == "completed"
    assert result.message == (
        "Scanned 2 isolutions Switzerland vacancies from the official catalog"
    )
    assert len(result.jobs) == 2

    first = result.jobs[0]
    assert first.source == "isolutions"
    assert first.title == "Junior Technical Consultant - Digital Workplace"
    assert first.company == "isolutions AG"
    assert first.location == "Bern, Zürich, Basel"
    assert first.url == (
        "https://www.isolutions.test/en/career/"
        "junior-technical-consultant-digital-workplace/"
    )
    assert first.apply_url == (
        "https://isolutions.jobs.personio.com/job/2738670/apply?_pc=3114117#apply"
    )
    assert first.posted_at == "2026-08-03"
    assert first.employment_type == "Full-time"
    assert first.description and "Build modern Microsoft solutions" in first.description
    assert first.raw["department"] == "Consulting"
    assert first.raw["detail"]["ats"]["job_id"] == "2738670"


def test_isolutions_keeps_detail_when_personio_enrichment_fails() -> None:
    card = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career/":
            return httpx.Response(200, text=listing_html([card]), request=request)
        if request.url.host == "www.isolutions.test":
            return httpx.Response(
                200,
                text=detail_html(
                    "junior-technical-consultant-digital-workplace",
                    title="Junior Technical Consultant - Digital Workplace",
                    personio_id="2738670",
                ),
                request=request,
            )
        return httpx.Response(503, request=request)

    job = IsolutionsJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]

    assert job.description and "Build modern Microsoft solutions" in job.description
    assert job.apply_url and "2738670" in job.apply_url
    assert job.posted_at is None
    assert job.employment_type is None
    assert "503 Service Unavailable" in str(job.raw["ats_error"])


def test_isolutions_accepts_live_breezy_and_template_variants() -> None:
    title = "Enterprise Engineer M365"
    page = detail_html(
        "enterprise-engineer-m365",
        title=title,
        personio_id="unused",
        apply_url=(
            "https://isolutions.breezy.hr/"
            "p/b8db561ce9f901-enterprise-m365-engineer-in"
        ),
    )
    page = page.replace(
        '<meta property="og:title" content="Enterprise Engineer M365">',
        '<meta property="og:title" content="Enterprise Engineer M365 (m/f/d)">',
    ).replace(
        'title="Job Description">Job Description',
        'title="Does your heart burn for cloud engineering?">Cloud engineering',
    ).replace("We would like you to:", "We would like you to bring:")
    detail_url = "https://www.isolutions.test/en/career/enterprise-engineer-m365/"

    detail = parse_detail_html(
        page,
        page_url=detail_url,
        expected_url=detail_url,
        expected_job_id="enterprise-engineer-m365",
        expected_title=title,
    )

    assert detail["ats_kind"] == "breezy"
    assert detail["ats_job_id"] == "b8db561ce9f901"
    assert detail["ats_url"] == "https://isolutions.breezy.hr/p/b8db561ce9f901"
    assert parse_breezy_html(
        breezy_html(),
        expected_job_id="b8db561ce9f901",
        expected_title=title,
    ) == {
        "job_id": "b8db561ce9f901",
        "posted_at": "2022-11-01",
        "employment_type": "Full-time",
    }


def test_isolutions_preserves_listing_when_detail_fails() -> None:
    card = catalog_fixture()[0]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/en/career/":
            return httpx.Response(200, text=listing_html([card]), request=request)
        return httpx.Response(503, request=request)

    job = IsolutionsJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(handler),
    ).search(LinkedInSearchRequest()).jobs[0]

    assert job.title == "Junior Technical Consultant - Digital Workplace"
    assert job.apply_url == job.url
    assert job.description is None
    assert "503 Service Unavailable" in str(job.raw["detail_error"])


def test_isolutions_rejects_incomplete_duplicate_or_changed_catalog() -> None:
    card = catalog_fixture()[0]

    def run(page: str) -> None:
        IsolutionsJobsParser(
            base_url=BASE_URL,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=page, request=request)
            ),
        ).search(LinkedInSearchRequest())

    with pytest.raises(DirectCompanyRequestError, match="vacancy catalog"):
        run(listing_html([]))
    with pytest.raises(DirectCompanyRequestError, match="invalid vacancy"):
        run(listing_html([card, card]))
    with pytest.raises(DirectCompanyRequestError, match="catalog filters"):
        run(listing_html([card], consulting_name="Advisory"))
    with pytest.raises(DirectCompanyRequestError, match="Swiss office identity"):
        run(listing_html([card], zurich_postcode="10115 Berlin"))


def test_isolutions_rejects_wrong_identity_or_detail_contract() -> None:
    wrong_identity = listing_html(catalog_fixture()).replace(
        '<html lang="en-US">',
        '<html lang="de-DE">',
    )
    parser = IsolutionsJobsParser(
        base_url=BASE_URL,
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, text=wrong_identity, request=request)
        ),
    )
    with pytest.raises(DirectCompanyRequestError, match="unexpected identity"):
        parser.search(LinkedInSearchRequest())

    detail_url = (
        "https://www.isolutions.test/en/career/"
        "junior-technical-consultant-digital-workplace/"
    )
    with pytest.raises(DirectCompanyRequestError, match="incomplete vacancy"):
        parse_detail_html(
            detail_html(
                "junior-technical-consultant-digital-workplace",
                title="Junior Technical Consultant - Digital Workplace",
                personio_id="2738670",
                apply_url="https://attacker.example/job/2738670/apply",
            ),
            page_url=detail_url,
            expected_url=detail_url,
            expected_job_id="junior-technical-consultant-digital-workplace",
            expected_title="Junior Technical Consultant - Digital Workplace",
        )


def test_isolutions_wraps_listing_request_failures() -> None:
    parser = IsolutionsJobsParser(
        transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    )
    with pytest.raises(DirectCompanyRequestError, match="vacancy request failed"):
        parser.search(LinkedInSearchRequest())


def test_isolutions_is_registered_and_renders_as_direct_company_source() -> None:
    settings = Settings(_env_file=None)
    runner = create_vacancy_search_runner(settings)
    parser = runner.parsers["isolutions"]
    assert isinstance(parser, IsolutionsJobsParser)
    assert parser.base_url == settings.isolutions_jobs_base_url
    assert parser.detail_workers == settings.isolutions_jobs_detail_workers

    request = JobSearchManualRunRequest.model_validate(
        {
            "config": {"name": "isolutions", "filters": {}},
            "sources": ["isolutions", "isolutions"],
        }
    )
    assert request.sources == ["isolutions"]

    job = parser.normalize_job(
        {
            "id": "junior-technical-consultant-digital-workplace",
            "title": "Junior Technical Consultant - Digital Workplace",
            "location": "Bern, Zürich, Basel",
            "url": (
                "https://www.isolutions.ch/en/career/"
                "junior-technical-consultant-digital-workplace/"
            ),
        }
    )
    stored = parsed_job_to_stored_job(
        job,
        job_id="isolutions-junior-technical-consultant-digital-workplace",
        added_at=datetime.now(UTC),
    )
    assert stored["logo"] == "company"
    assert stored["department"] == "isolutions AG import"
    assert stored["id"] == "isolutions-junior-technical-consultant-digital-workplace"
