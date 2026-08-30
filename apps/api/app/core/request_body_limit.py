from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

DEFAULT_REQUEST_BODY_LIMIT = 16_000_000
PROFILE_JSON_BODY_LIMIT = 1_000_000
APPLICATION_JSON_BODY_LIMIT = 5_000_000


class RequestBodyTooLarge(RuntimeError):
    pass


class RequestBodyLimitMiddleware:
    """Reject oversized bodies before JSON parsing and while streaming uploads."""

    def __init__(
        self,
        app: Callable[[Scope, Receive, Send], Awaitable[None]],
        *,
        default_limit: int = DEFAULT_REQUEST_BODY_LIMIT,
    ) -> None:
        self.app = app
        self.default_limit = default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        limit = request_body_limit(scope, default_limit=self.default_limit)
        declared_length = header_value(scope, b"content-length")
        if declared_length is not None:
            try:
                parsed_length = int(declared_length)
            except ValueError:
                await self._error(scope, receive, send, 400, "Invalid Content-Length header")
                return
            if parsed_length < 0:
                await self._error(scope, receive, send, 400, "Invalid Content-Length header")
                return
            if parsed_length > limit:
                await self._error(scope, receive, send, 413, "Request body is too large")
                return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._error(scope, receive, send, 413, "Request body is too large")

    async def _error(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        status_code: int,
        detail: str,
    ) -> None:
        response = JSONResponse({"detail": detail}, status_code=status_code)
        await response(scope, receive, send)


def request_body_limit(
    scope: Scope,
    *,
    default_limit: int = DEFAULT_REQUEST_BODY_LIMIT,
) -> int:
    path = str(scope.get("path") or "")
    method = str(scope.get("method") or "GET").upper()
    content_type = (header_value(scope, b"content-type") or "").partition(";")[0].strip().casefold()
    is_json = content_type == "application/json" or (
        content_type.startswith("application/") and content_type.endswith("+json")
    )
    if is_json and method in {"POST", "PUT", "PATCH"}:
        if path == "/profile":
            return PROFILE_JSON_BODY_LIMIT
        if path == "/applications" or path.startswith("/applications/"):
            return APPLICATION_JSON_BODY_LIMIT
    return default_limit


def header_value(scope: Scope, name: bytes) -> str | None:
    for raw_name, raw_value in scope.get("headers", []):
        if raw_name.lower() == name:
            return raw_value.decode("latin-1")
    return None


__all__ = [
    "APPLICATION_JSON_BODY_LIMIT",
    "DEFAULT_REQUEST_BODY_LIMIT",
    "PROFILE_JSON_BODY_LIMIT",
    "RequestBodyLimitMiddleware",
    "request_body_limit",
]
