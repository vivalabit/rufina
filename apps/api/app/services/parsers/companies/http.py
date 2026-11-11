"""Bounded retries for read-only career catalogs and vacancy details."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import BoundedSemaphore, Lock
from typing import Any

import httpx
from curl_cffi.requests.exceptions import Timeout as CurlTimeout

RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3
MAX_RETRY_DELAY = 30.0


class _HostRequestGate:
    def __init__(self) -> None:
        self.slots = BoundedSemaphore(2)
        self.lock = Lock()
        self.next_start = 0.0

    def send(self, fetch: Callable[[], Any], interval: float) -> Any:
        # Shared by clients in overlapping searches, not just one parser instance.
        with self.slots:
            with self.lock:
                time.sleep(max(0.0, self.next_start - time.monotonic()))
                self.next_start = time.monotonic() + interval
            return fetch()


_host_gates: dict[str, _HostRequestGate] = {}
_host_gates_lock = Lock()


def retry_delay(headers: Any, attempt: int) -> float:
    value = headers.get("Retry-After") if headers else None
    if value is not None:
        try:
            delay = float(value)
        except (TypeError, ValueError):
            try:
                delay = (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
            except (TypeError, ValueError, OverflowError):
                delay = 0.0
        if delay > 0:
            return min(delay, MAX_RETRY_DELAY)
    return min(2 ** (attempt - 1), MAX_RETRY_DELAY)


def fetch_with_retry[T](fetch: Callable[[], T], *, retryable_statuses: set[int] | None = None) -> T:
    """Retry transport failures and temporary HTTP responses, never parsing errors.

    The final response is returned for the parser's existing status checks. In
    particular 404/410 are not retried or treated as proof that a job was deleted.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = fetch()
        except (httpx.TimeoutException, httpx.NetworkError, TimeoutError, CurlTimeout):
            if attempt == MAX_ATTEMPTS:
                raise
            time.sleep(retry_delay(None, attempt))
            continue
        status = getattr(response, "status_code", None)
        if status is None:
            status = getattr(response, "status", 0)
        statuses = RETRYABLE_STATUSES if retryable_statuses is None else retryable_statuses
        if int(status or 0) not in statuses or attempt == MAX_ATTEMPTS:
            return response
        delay = retry_delay(getattr(response, "headers", None), attempt)
        if isinstance(response, httpx.Response):
            response.close()
        time.sleep(delay)
    raise AssertionError("Retry loop exhausted without a response")


class CareerHttpClient(httpx.Client):
    """Retry GET/HEAD; explicitly opt in read-only catalog POSTs per call."""

    def __init__(self, *args: Any, request_interval_seconds: float = 0.0, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.request_interval_seconds = max(0.0, request_interval_seconds)

    def _send_paced(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:
        send = super().request
        if not self.request_interval_seconds:
            return send(method, url, **kwargs)
        host = self.base_url.join(url).host
        with _host_gates_lock:
            gate = _host_gates.setdefault(host, _HostRequestGate())
        return gate.send(lambda: send(method, url, **kwargs), self.request_interval_seconds)

    def request(self, method: str, url: Any, **kwargs: Any) -> httpx.Response:
        if method.upper() in {"GET", "HEAD"}:
            return fetch_with_retry(lambda: self._send_paced(method, url, **kwargs))
        return self._send_paced(method, url, **kwargs)

    def post_catalog(self, url: Any, **kwargs: Any) -> httpx.Response:
        return fetch_with_retry(lambda: self._send_paced("POST", url, **kwargs))
