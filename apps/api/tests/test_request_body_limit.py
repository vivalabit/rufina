import asyncio

from starlette.types import Message, Receive, Scope, Send

from app.core.request_body_limit import (
    APPLICATION_JSON_BODY_LIMIT,
    PROFILE_JSON_BODY_LIMIT,
    RequestBodyLimitMiddleware,
    request_body_limit,
)


def http_scope(
    *,
    path: str = "/upload",
    content_type: bytes = b"application/octet-stream",
    content_length: int | None = None,
) -> Scope:
    headers = [(b"content-type", content_type)]
    if content_length is not None:
        headers.append((b"content-length", str(content_length).encode("ascii")))
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "client": ("test", 1),
        "server": ("test", 80),
        "root_path": "",
    }


def run_middleware(
    messages: list[Message],
    *,
    scope: Scope,
    limit: int,
) -> tuple[list[Message], bool]:
    sent: list[Message] = []
    downstream_called = False

    async def downstream(_scope: Scope, receive: Receive, send: Send) -> None:
        nonlocal downstream_called
        downstream_called = True
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    queue = list(messages)

    async def receive() -> Message:
        return queue.pop(0)

    async def send(message: Message) -> None:
        sent.append(message)

    middleware = RequestBodyLimitMiddleware(downstream, default_limit=limit)
    asyncio.run(middleware(scope, receive, send))
    return sent, downstream_called


def test_request_body_limit_rejects_declared_and_streamed_oversize_bodies() -> None:
    declared, declared_called = run_middleware(
        [{"type": "http.request", "body": b"", "more_body": False}],
        scope=http_scope(content_length=11),
        limit=10,
    )
    streamed, streamed_called = run_middleware(
        [
            {"type": "http.request", "body": b"123456", "more_body": True},
            {"type": "http.request", "body": b"78901", "more_body": False},
        ],
        scope=http_scope(),
        limit=10,
    )

    assert declared[0]["status"] == 413
    assert streamed[0]["status"] == 413
    assert declared_called is False
    assert streamed_called is True


def test_request_body_limit_allows_bounded_stream_and_uses_json_path_limits() -> None:
    sent, downstream_called = run_middleware(
        [
            {"type": "http.request", "body": b"12345", "more_body": True},
            {"type": "http.request", "body": b"67890", "more_body": False},
        ],
        scope=http_scope(),
        limit=10,
    )

    assert sent[0]["status"] == 204
    assert downstream_called is True
    assert (
        request_body_limit(http_scope(path="/profile", content_type=b"application/json"))
        == PROFILE_JSON_BODY_LIMIT
    )
    assert (
        request_body_limit(http_scope(path="/applications/app-1", content_type=b"application/json"))
        == APPLICATION_JSON_BODY_LIMIT
    )
    assert (
        request_body_limit(
            http_scope(
                path="/profile",
                content_type=b"application/vnd.api+json; charset=utf-8",
            )
        )
        == PROFILE_JSON_BODY_LIMIT
    )
