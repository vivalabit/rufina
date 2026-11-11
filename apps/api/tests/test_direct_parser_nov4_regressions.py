"""Failures observed in overlapping complete company searches on 2026-11-04."""

import time
from concurrent.futures import ThreadPoolExecutor
from itertools import pairwise
from threading import Lock

import httpx
import pytest
import test_m_s_software_engineering_parser as ms_fixture

from app.models.parsers import LinkedInSearchRequest
from app.services.parsers.companies.base import DirectCompanyRequestError
from app.services.parsers.companies.http import CareerHttpClient
from app.services.parsers.companies.iwf import IwfJobsParser
from app.services.parsers.companies.schindler_switzerland import SchindlerSwitzerlandJobsParser


def test_live_onlyfy_feed_survives_empty_or_stale_baked_catalog():
    first = ms_fixture.job_record()
    second = ms_fixture.job_record(
        feed_handle=ms_fixture.SECOND_FEED_HANDLE,
        public_handle=ms_fixture.SECOND_PUBLIC_HANDLE,
        title="Site Reliability Engineer",
    )
    for live, baked in [([first], []), ([first, second], [first]), ([second], [first])]:
        result = ms_fixture.parser_for(live, page_records=baked, apprenticeships=[]).search(
            LinkedInSearchRequest()
        )
        assert len(result.jobs) == len(live)
        assert all(job.description for job in result.jobs)


@pytest.mark.parametrize("correct_identity,closed", [(True, True), (False, True), (True, False)])
def test_schindler_closed_job_requires_explicit_notice_and_matching_identity(
    correct_identity, closed
):
    record = {
        "id": "1254185401",
        "title": "Schnupperlehre als Polymechaniker",
        "location": "Steinach, CH",
        "url": "https://job.schindler.com/SBB_AS/job/Role/1254185401/",
    }
    title = record["title"] if correct_identity else "Another job"
    body = f'<meta property="og:title" content="{title}"><p>'
    body += "Diese Stelle wurde leider bereits besetzt." if closed else "Temporarily unavailable"
    body += "</p>"
    with CareerHttpClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body))
    ) as client:
        records = [record]
        SchindlerSwitzerlandJobsParser().enrich_records(client, records)
    assert not records if correct_identity and closed else records[0]["detail_error"]


def test_removed_iwf_catalog_keeps_http_status_in_diagnostic():
    with pytest.raises(DirectCompanyRequestError, match="HTTP 404.*iwf.ch/web-solutions/jobs"):
        IwfJobsParser(transport=httpx.MockTransport(lambda _: httpx.Response(404))).search(
            LinkedInSearchRequest()
        )


def test_host_pacing_is_shared_between_overlapping_search_clients():
    active, maximum = 0, 0
    starts = []
    lock = Lock()

    def handler(_):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            starts.append(time.monotonic())
        time.sleep(0.05)
        with lock:
            active -= 1
        return httpx.Response(200)

    kwargs = {"transport": httpx.MockTransport(handler), "request_interval_seconds": 0.02}
    with (
        CareerHttpClient(**kwargs) as first,
        CareerHttpClient(**kwargs) as second,
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        responses = list(
            pool.map(
                lambda i: (first if i % 2 else second).get(f"https://paced-career.test/job/{i}"),
                range(8),
            )
        )
    assert all(response.status_code == 200 for response in responses)
    assert maximum == 2
    assert all(right - left >= 0.015 for left, right in pairwise(starts))


def test_paced_client_retries_only_failed_request_and_releases_host_slots(monkeypatch):
    monkeypatch.setattr("app.services.parsers.companies.http.time.sleep", lambda _: None)
    calls = []

    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/retry" and calls.count("/retry") == 1:
            raise httpx.ConnectTimeout("TLS handshake timed out")
        return httpx.Response(200)

    with CareerHttpClient(
        transport=httpx.MockTransport(handler),
        request_interval_seconds=0.001,
    ) as client:
        client.get("https://paced-retry.test/ok")
        client.get("https://paced-retry.test/retry")
        client.get("https://paced-retry.test/next")
    assert calls == ["/ok", "/retry", "/retry", "/next"]
