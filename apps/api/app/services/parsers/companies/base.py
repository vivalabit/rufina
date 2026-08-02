from typing import Any, Protocol


class ScraplingResponse(Protocol):
    """Small response surface used by company parsers and their test fetchers."""

    def css(self, selector: str, *args: Any, **kwargs: Any) -> Any: ...

    def json(self) -> Any: ...


class DirectCompanyRequestError(RuntimeError):
    """A recoverable upstream or parsing failure for one company source."""
