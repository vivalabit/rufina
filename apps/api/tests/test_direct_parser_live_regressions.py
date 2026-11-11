"""Regressions observed on official career sites on 2026-11-03."""

import json
import re

import httpx
import pytest
import test_amag_group_parser as amag_fixture
import test_bayer_switzerland_parser as bayer_fixture
import test_bedag_parser as bedag_fixture
import test_bkw_switzerland_parser as bkw_fixture
import test_cudos_parser as cudos_fixture
import test_sharp_switzerland_parser as sharp_fixture
import test_smino_parser as smino_fixture
import test_snb_parser as snb_fixture
import test_tx_group_parser as tx_fixture
from scrapling import Selector

from app.models.parsers import LinkedInSearchRequest
from app.services.parsers.companies import (
    amag_group,
    artificialy,
    bayer_switzerland,
    bedag,
    bkw_switzerland,
    cudos,
    flughafen_zuerich,
    lonza_switzerland,
    manor,
    novartis_switzerland,
    rdm_switzerland,
    sharp_switzerland,
    smino,
    snb,
    sonova_switzerland,
    tx_group,
)
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient
from app.services.swiss_locations import is_swiss_postal_locality


def edit_schema(page, edit):
    pattern = r'(<script type="application/ld\+json">)(.*?)(</script>)'

    def replace(match):
        schema = json.loads(match[2])
        edit(schema)
        return match[1] + json.dumps(schema) + match[3]

    return re.sub(pattern, replace, page, flags=re.DOTALL)


def test_cudos_cms_plugin_id_is_discovered():
    page = cudos_fixture.listing_html(cudos_fixture.official_records()).replace("32118", "32200")
    records = cudos.parse_listing_html(
        page, page_url=cudos_fixture.BASE_URL, expected_base_url=cudos_fixture.BASE_URL
    )
    assert len(records) == 3


def test_tx_accepts_official_english_job_path():
    record = tx_fixture.listing_record(
        8635143, "Technical Lead CMS Backend", "Tamedia", "jobs.tamedia.ch", language_prefix="/en"
    )
    result = tx_group.parse_listing_html(
        tx_fixture.listing_html([record]),
        page_url=tx_group.TX_GROUP_JOBS_BASE_URL,
        expected_url=tx_group.TX_GROUP_JOBS_BASE_URL,
        max_jobs=500,
    )
    assert result["8635143"]["public_url"] == record["public_url"]


def test_bayer_optional_metadata_does_not_discard_a_valid_swiss_job():
    record = bayer_fixture.vacancy(562949978502580, "Chief of Staff WWM")
    for field in ("locale", "department", "business_unit"):
        record.pop(field, None)
    assert bayer_switzerland.is_valid_listing_record(
        record, base_url="https://talent.bayer.test/careers"
    )
    record["locations"] = ["Berlin,Berlin,Germany"]
    assert not bayer_switzerland.is_valid_listing_record(
        record, base_url="https://talent.bayer.test/careers"
    )


def test_smino_accepts_current_personio_zero_jobs_state():
    page = smino_fixture.listing_html([]).replace(
        '<div aria-label="Offene Positionen"></div>',
        '<main><p class="no-jobs-title">Derzeit keine offenen Positionen</p></main>',
    )
    kwargs = {
        "page_url": smino_fixture.BASE_URL,
        "expected_url": smino_fixture.BASE_URL,
        "max_jobs": 100,
    }
    assert smino.parse_listing_html(page, **kwargs) == []
    with pytest.raises(DirectCompanyRequestError):
        smino.parse_listing_html(
            page.replace("Derzeit keine offenen Positionen", "Loading..."), **kwargs
        )


def test_artificialy_reads_new_company_page_and_migrates_old_url():
    page = Selector("""<main><div class="container-base"><div><h2>Careers</h2></div>
        <p>Open Positions:</p><div><div><h3>AI Engineer</h3>
        <div class="rich-text"><p><strong>Lugano / Zurich · Full-time</strong></p><p>Build AI systems.</p></div>
        <a href="https://www.linkedin.com/jobs/view/4462149285/">View on LinkedIn</a></div></div></div></main>""")
    calls = []

    def fetch(url):
        calls.append(url)
        return page

    result = artificialy.ArtificialyJobsParser(
        base_url="https://www.artificialy.com/career", fetch_page=fetch
    ).search(LinkedInSearchRequest())
    assert calls == ["https://www.artificialy.com/company"]
    assert result.jobs[0].raw["id"] == "4462149285"
    assert result.jobs[0].location == "Lugano / Zurich"
    assert "Build AI systems." in result.jobs[0].description


def test_novartis_requests_fresh_catalog_pages():
    urls = []

    def handler(request):
        urls.append(request.url)
        return httpx.Response(200 if request.url.params.get("_") else 503, text="catalog")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        parser = novartis_switzerland.NovartisSwitzerlandJobsParser()
        parser.fetch_listing_page(client, page_number=1)
        parser.fetch_listing_page(client, page_number=2)
        parser.fetch_listing_page(client, page_number=1)
    assert len({u.params["_"] for u in urls}) == 3
    assert all(u.params["country[]"] == "LOC_CH" for u in urls)


def test_bedag_ignores_broken_responsive_workload_duplicate():
    url = "https://www.bedag.test/de/aktuelles/offene-stellen/job_1062.php"
    page = bedag_fixture.detail_html("1062", title="Senior Sourcing Manager (a)", workload="80%")
    page = page.replace("</main>", '<span class="jobPercentage">80 – %</span></main>')
    detail = bedag.parse_detail_html(
        page,
        page_url=url,
        expected_url=url,
        expected_job_id="1062",
        expected_title="Senior Sourcing Manager (a)",
        expected_workload="80%",
    )
    assert detail["workload"] == "80%"
    assert detail["description"]


def test_snb_normalizes_spacing_in_visible_job_title():
    title = "Leiterin/Leiter Notenverarbeitung Ost (80%-100%)"
    url = "https://careers.snb.test/job/Data-Platform-Engineer-3600/3600-de_DE/"
    page = snb_fixture.detail_html(3600, title=title, workload=None)
    page = page.replace(
        f"<strong>{title}</strong>", f"<strong>{title.replace('80%-100%', '80% - 100%')}</strong>"
    )
    detail = snb.parse_detail_html(
        page,
        page_url=url,
        expected_url=url,
        expected_job_id="3600",
        expected_title=title,
        expected_cities=["Zürich"],
        expected_employment_type="Festanstellung",
        expected_work_model="hybrid",
    )
    assert detail["description"]


def test_sharp_accepts_official_slug_redirect_only_when_role_matches():
    slug = "junior-account-manager-region-zug"
    url = f"https://www.sharp.ch/de/{slug}"
    page = sharp_fixture.detail_html(
        slug=slug,
        title="Junior Account Manager (w/m/d) 100%",
        metadata_title="Junior Account Manager | Zug",
        summary="Zug |100 % | ab sofort",
    )
    kwargs = {
        "page_url": url,
        "expected_url": "https://www.sharp.ch/de/account-manager-region-zug",
        "expected_title": "Junior Account Manager (m/w/d), 100%, Region Zug",
    }
    detail = sharp_switzerland.parse_detail_html(page, **kwargs)
    assert detail["url"] == url
    with pytest.raises(DirectCompanyRequestError):
        sharp_switzerland.parse_detail_html(
            page, **{**kwargs, "expected_title": "Software Engineer"}
        )


def test_amag_missing_optional_location_does_not_lose_description():
    record = amag_fixture.official_records()[0]
    page = edit_schema(amag_fixture.detail_html(record), lambda schema: schema.pop("jobLocation"))
    expected = {**record, "url": amag_fixture.public_url(record["id"], record["slug"])}
    detail = amag_group.parse_detail_html(
        page, page_url=expected["url"], expected_record=expected, base_url=amag_fixture.BASE_URL
    )
    assert detail["description"]
    assert detail["locations"] == []


@pytest.mark.parametrize("closed", [True, False])
def test_manor_only_omits_explicitly_removed_job(closed):
    record = {
        "url": "https://live.solique.ch/manor/job/details/4029409/",
        "title": "Role",
        "requisition_id": "8044",
    }
    body = "\ufeffThis job does not exist anymore" if closed else "Not Found"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, text=body))
    ) as client:
        records = [record]
        manor.ManorJobsParser().enrich_records(client, records)
    assert not records if closed else records[0]["detail_error"]


@pytest.mark.parametrize("correct_identity", [True, False])
def test_sonova_only_omits_filled_job_with_matching_identity(correct_identity):
    record = {
        "url": "https://jobs.sonova.com/job/Staefa-Engineer/1437852833/",
        "title": "Engineer DSP",
        "id": "165354",
        "location": "Staefa, Switzerland",
    }
    title = "Engineer DSP" if correct_identity else "Another Role"
    body = f"<title>{title} Job Details | Sonova AG</title><p>Sorry, this position has been filled.</p>"
    with CareerHttpClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))
    ) as client:
        records = [record]
        sonova_switzerland.SonovaSwitzerlandJobsParser().enrich_records(client, records)
    assert not records if correct_identity else records[0]["detail_error"]


def test_bkw_repairs_schema_country_only_with_independent_swiss_evidence():
    url = str(bkw_fixture.listing_record(0)["url"])
    kwargs = {
        "page_url": url,
        "expected_url": url,
        "expected_id": bkw_fixture.JOB_IDS[0],
        "expected_title": "Platform Engineer 0",
    }
    page = edit_schema(
        bkw_fixture.detail_html(0, country="Deutschland"),
        lambda s: s["jobLocation"]["address"].update(addressLocality="Urdorf", postalCode="8902"),
    )
    detail = bkw_switzerland.parse_detail_html(page, **kwargs)
    assert detail["location"] == "Urdorf, Switzerland"
    assert detail["schema"]["jobLocation"]["address"]["addressCountry"] == "Deutschland"
    page = edit_schema(
        page,
        lambda s: s["jobLocation"]["address"].update(
            addressLocality="Weiterstadt", postalCode="64331"
        ),
    )
    with pytest.raises(DirectCompanyRequestError):
        bkw_switzerland.parse_detail_html(page, **kwargs)
    detail = bkw_switzerland.parse_detail_html(
        page,
        **kwargs,
        listing_locations=[
            {"city": "Dresden", "country": "Schweiz"},
            {"city": "Wangen an der Aare", "country": "Schweiz"},
        ],
    )
    assert detail["location"] == "Wangen an der Aare, Switzerland"
    assert not is_swiss_postal_locality("Weiterstadt", "8902")


def test_flughafen_retries_tls_failure_for_only_failed_detail(monkeypatch):
    import test_flughafen_zuerich_parser as fixture

    monkeypatch.setattr("app.services.parsers.companies.http.time.sleep", lambda _: None)
    records = fixture.listing_payload()
    calls = []

    def handler(request):
        calls.append(str(request.url))
        record = next(r for r in records if r["jobLink"] == str(request.url))
        if record == records[0] and calls.count(str(request.url)) == 1:
            raise httpx.ConnectTimeout("TLS handshake timeout")
        return httpx.Response(
            200, text=fixture.detail_html(view_key=record["viewKey"], title=record["title"])
        )

    with CareerHttpClient(transport=httpx.MockTransport(handler)) as client:
        flughafen_zuerich.FlughafenZuerichJobsParser().enrich_records(client, records)
    assert all(r.get("detail") and not r.get("detail_error") for r in records)
    assert len(calls) == len(records) + 1


def test_lonza_retries_transient_forbidden_with_bounded_delays(monkeypatch):
    from types import SimpleNamespace

    calls, delays = [], []
    monkeypatch.setattr("app.services.parsers.companies.http.time.sleep", delays.append)

    def get(*args, **kwargs):
        calls.append(args[0])
        return SimpleNamespace(status=403 if len(calls) == 1 else 200)

    monkeypatch.setattr(lonza_switzerland.Fetcher, "get", get)
    parser = lonza_switzerland.LonzaSwitzerlandJobsParser()
    assert parser._get_with_scrapling("https://www.lonza.com/jobs/R78155").status == 200
    assert len(calls) == 2
    assert any(delay >= 1 for delay in delays)
    assert parser.detail_workers <= 2


def test_rdm_explicit_cloudflare_block_is_not_retried_or_reported_as_empty():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(403, text="Attention Required! Cloudflare")

    with pytest.raises(DirectCompanyRequestError, match="access blocked by Cloudflare"):
        rdm_switzerland.RdmSwitzerlandJobsParser(transport=httpx.MockTransport(handler)).search(
            LinkedInSearchRequest()
        )
    assert len(calls) == 1


def lonza_workday_postings(count):
    return [
        {"externalPath": f"/job/Visp/Engineer_R{1000 + i}", "title": f"Engineer {i}"}
        for i in range(count)
    ]


def lonza_workday_page(postings, total):
    return {
        "total": total,
        "jobPostings": postings,
        "facets": [
            {
                "facetParameter": "locationCountry",
                "values": [
                    {"id": "187134fccb084a0ea9b4b95f23890dbe", "count": total},
                ],
            }
        ],
    }


def lonza_workday_detail(posting):
    return {
        "jobPostingInfo": {
            "jobReqId": posting["externalPath"].rsplit("_", 1)[1],
            "title": posting["title"],
            "externalUrl": "https://lonza.wd3.myworkdayjobs.com/Lonza_Careers"
            + posting["externalPath"],
            "country": {"id": "187134fccb084a0ea9b4b95f23890dbe"},
            "location": "Visp",
            "jobDescription": "<p>Manufacture medicines in Visp.</p>",
        }
    }


@pytest.mark.parametrize("omit_later_metadata", [True, False])
def test_lonza_reconciles_all_workday_pages_before_removing_stale_cms_links(omit_later_metadata):
    postings = lonza_workday_postings(21)
    calls = []

    def handler(request):
        calls.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["appliedFacets"] == {
                "locationCountry": ["187134fccb084a0ea9b4b95f23890dbe"]
            }
            offset = body["offset"]
            payload = lonza_workday_page(postings[offset : offset + 20], 21)
            if offset and omit_later_metadata:
                payload.update(total=0, facets=[])
            return httpx.Response(200, json=payload)
        posting = next(p for p in postings if str(request.url).endswith(p["externalPath"]))
        return httpx.Response(200, json=lonza_workday_detail(posting))

    records = [
        {"id": "R9", "detail_error": "Lonza returned HTTP 404"},
        {"id": "R1000", "detail_error": "Lonza returned HTTP 404"},
        {"id": "R1001", "detail": {"description": "Verified CMS description"}},
        {"id": "R5000", "detail_error": "Lonza returned HTTP 503"},
    ]
    parser = lonza_switzerland.LonzaSwitzerlandJobsParser(
        workday_transport=httpx.MockTransport(handler)
    )
    parser.reconcile_workday_catalog(records)
    by_id = {r["id"]: r for r in records}
    assert len(records) == 22
    assert "R9" not in by_id
    assert by_id["R1000"]["detail"]["description"] == "Manufacture medicines in Visp."
    assert "detail_error" not in by_id["R1000"]
    assert by_id["R1001"]["detail"]["description"] == "Verified CMS description"
    assert by_id["R5000"]["detail_error"] == "Lonza returned HTTP 503"
    assert by_id["R1020"]["url"].startswith("https://lonza.wd3.myworkdayjobs.com/")
    assert [json.loads(r.content)["offset"] for r in calls if r.method == "POST"] == [0, 20]


@pytest.mark.parametrize("failure", ["count_changed", "missing_page", "wrong_country", "duplicate"])
def test_lonza_never_removes_cms_jobs_after_incomplete_workday_scan(failure):
    postings = lonza_workday_postings(21)

    def handler(request):
        offset = json.loads(request.content)["offset"]
        payload = lonza_workday_page(postings[offset : offset + 20], 21)
        if offset:
            if failure == "count_changed":
                payload["total"] = 22
            elif failure == "missing_page":
                payload["jobPostings"] = []
            elif failure == "wrong_country":
                payload["facets"][0]["values"][0]["id"] = "germany"
            else:
                payload["jobPostings"] = postings[:1]
        return httpx.Response(200, json=payload)

    records = [{"id": "R9", "detail_error": "Lonza returned HTTP 404"}]
    lonza_switzerland.LonzaSwitzerlandJobsParser(
        workday_transport=httpx.MockTransport(handler)
    ).reconcile_workday_catalog(records)
    assert [r["id"] for r in records] == ["R9"]
    assert "reconciliation unavailable" in records[0]["detail_error"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("jobReqId", "R9"),
        ("country", {"id": "germany"}),
        ("externalUrl", "https://example.org/job"),
    ],
)
def test_lonza_rejects_workday_detail_with_conflicting_identity(field, value):
    postings = lonza_workday_postings(1)

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json=lonza_workday_page(postings, 1))
        payload = lonza_workday_detail(postings[0])
        payload["jobPostingInfo"][field] = value
        return httpx.Response(200, json=payload)

    records = [{"id": "R1000", "detail_error": "Lonza returned HTTP 404"}]
    lonza_switzerland.LonzaSwitzerlandJobsParser(
        workday_transport=httpx.MockTransport(handler)
    ).reconcile_workday_catalog(records)
    assert len(records) == 1
    assert "detail" not in records[0]
    assert "invalid identity or country" in records[0]["detail_error"]


@pytest.mark.parametrize("closed", [True, False])
def test_bkw_only_omits_explicitly_closed_job(closed):
    record = {
        "url": str(bkw_fixture.listing_record(0)["url"]),
        "parsed_locations": [{"city": "Bern", "country": "Schweiz"}],
    }
    body = "<p>Wir bedauern, diese Ausschreibung ist nicht mehr online.</p>" if closed else "Gone"
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(410, text=body))
    ) as client:
        records = [record]
        bkw_switzerland.BkwSwitzerlandJobsParser().enrich_records(client, records)
    assert not records if closed else records[0]["detail_error"]
