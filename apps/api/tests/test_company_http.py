import httpx
import pytest

from app.services.parsers.companies.http import CareerHttpClient, fetch_with_retry


@pytest.fixture
def delays(monkeypatch):
    values = []
    monkeypatch.setattr("app.services.parsers.companies.http.time.sleep", values.append)
    return values


def test_retry_only_failed_detail_preserves_successful_requests(delays):
    calls = []

    def handle(request):
        calls.append(request.url.path)
        if request.url.path == "/failed" and calls.count("/failed") < 3:
            return httpx.Response(503, headers={"Retry-After": "2"})
        return httpx.Response(200, text="description")

    with CareerHttpClient(transport=httpx.MockTransport(handle)) as client:
        assert client.get("https://jobs.test/catalog").status_code == 200
        assert client.get("https://jobs.test/healthy").text == "description"
        assert client.get("https://jobs.test/failed").text == "description"
    assert calls == ["/catalog", "/healthy", "/failed", "/failed", "/failed"]
    assert delays == [2, 2]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 410, 422])
def test_permanent_responses_are_not_retried(status, delays):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status)

    with CareerHttpClient(transport=httpx.MockTransport(handle)) as client:
        assert client.get("https://jobs.test/detail").status_code == status
    assert len(calls) == 1
    assert delays == []


def test_exhausted_retries_return_original_http_failure(delays):
    with (
        CareerHttpClient(transport=httpx.MockTransport(lambda _: httpx.Response(503))) as client,
        pytest.raises(httpx.HTTPStatusError, match="503"),
    ):
        client.get("https://jobs.test/detail").raise_for_status()
    assert delays == [1, 2]


def test_timeout_is_retried_and_retry_after_is_capped(delays):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(429, headers={"Retry-After": "3600"})

    with CareerHttpClient(transport=httpx.MockTransport(handle)) as client:
        assert client.get("https://jobs.test/detail").status_code == 429
    assert calls == 3
    assert delays == [1, 30]


def test_only_explicit_read_only_posts_are_retried(delays):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(503)

    with CareerHttpClient(transport=httpx.MockTransport(handle)) as client:
        client.post("https://jobs.test/apply", json={"value": "never retry"})
        client.post_catalog("https://jobs.test/catalog", data={"offset": "12"})
    assert len(calls) == 4
    assert [r.content for r in calls[1:]] == [b"offset=12"] * 3


def test_parsing_errors_are_not_retried(delays):
    def fetch():
        raise ValueError("wrong identity")

    with pytest.raises(ValueError, match="wrong identity"):
        fetch_with_retry(fetch)
    assert delays == []


def test_scrapling_timeout_is_retried(delays):
    from curl_cffi.requests.exceptions import Timeout

    calls = 0

    def fetch():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise Timeout("read timed out")
        return httpx.Response(200)

    assert fetch_with_retry(fetch).status_code == 200
    assert calls == 2
    assert delays == [1]
