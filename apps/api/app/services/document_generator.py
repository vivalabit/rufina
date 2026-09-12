"""Document generator integration point and the default unavailable adapter."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable
from uuid import uuid4

from app.models.generation import (
    GenerationDocumentResult,
    GenerationError,
    GenerationRequest,
    GenerationResult,
)


@runtime_checkable
class DocumentGenerator(Protocol):
    """Boundary implemented by the document-generation subsystem."""

    def generate(self, request: GenerationRequest) -> GenerationResult: ...


class UnavailableDocumentGenerator:
    """Safe placeholder used until a real generator adapter is configured."""

    def __init__(self, *, execution_id_factory: Callable[[], str] | None = None) -> None:
        self._execution_id_factory = execution_id_factory or (lambda: uuid4().hex)

    def generate(self, request: GenerationRequest) -> GenerationResult:
        error = GenerationError(
            code="generator_unavailable",
            message="Document generation is not configured yet.",
            retryable=False,
        )
        return GenerationResult(
            execution_id=self._execution_id_factory(),
            state="failed",
            documents=tuple(
                GenerationDocumentResult(
                    document_type=document_type,
                    state="failed",
                    error=error,
                )
                for document_type in request.document_types
            ),
            error=error,
        )


def get_document_generator() -> DocumentGenerator:
    """Return the configured integration adapter.

    The unavailable adapter is the production-safe default. Applications can
    replace this dependency with a real adapter without changing callers.
    """

    return UnavailableDocumentGenerator()


__all__ = [
    "DocumentGenerator",
    "UnavailableDocumentGenerator",
    "get_document_generator",
]
