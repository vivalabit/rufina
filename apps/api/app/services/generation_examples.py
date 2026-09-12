"""Explicit generator response examples for UI development and tests only."""

from __future__ import annotations

from typing import Literal

from app.models.documents import DocumentType
from app.models.generation import (
    GeneratedFile,
    GenerationDocumentResult,
    GenerationError,
    GenerationRequest,
    GenerationResult,
)

GenerationExampleScenario = Literal["running", "success", "error", "partial"]
GENERATION_EXAMPLE_SCENARIOS = ("running", "success", "error", "partial")


class ExampleDocumentGenerator:
    """Opt-in contract adapter returning one documented example scenario."""

    def __init__(
        self,
        scenario: GenerationExampleScenario,
        *,
        execution_id: str | None = None,
    ) -> None:
        if scenario not in GENERATION_EXAMPLE_SCENARIOS:
            raise ValueError(f"Unknown generation example scenario: {scenario}")
        self.scenario = scenario
        self.execution_id = execution_id or f"example-{scenario}"

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return generation_result_example(
            request,
            self.scenario,
            execution_id=self.execution_id,
        )


def generation_result_example(
    request: GenerationRequest,
    scenario: GenerationExampleScenario,
    *,
    execution_id: str | None = None,
) -> GenerationResult:
    """Return a valid response example without generating or storing files."""

    resolved_execution_id = execution_id or f"example-{scenario}"
    if scenario == "running":
        return GenerationResult(
            execution_id=resolved_execution_id,
            state="running",
            documents=tuple(
                GenerationDocumentResult(
                    document_type=document_type,
                    state="running" if index == 0 else "queued",
                )
                for index, document_type in enumerate(request.document_types)
            ),
        )
    if scenario == "success":
        return GenerationResult(
            execution_id=resolved_execution_id,
            state="completed",
            documents=tuple(
                _successful_document_example(resolved_execution_id, document_type)
                for document_type in request.document_types
            ),
        )

    error = GenerationError(
        code="example_generation_failed",
        message="Example: document generation failed.",
        retryable=True,
    )
    if scenario == "error":
        return GenerationResult(
            execution_id=resolved_execution_id,
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
    if len(request.document_types) < 2:
        raise ValueError("The partial generation example requires at least two documents")
    return GenerationResult(
        execution_id=resolved_execution_id,
        state="completed",
        documents=(
            _successful_document_example(
                resolved_execution_id,
                request.document_types[0],
            ),
            *(
                GenerationDocumentResult(
                    document_type=document_type,
                    state="failed",
                    error=error,
                )
                for document_type in request.document_types[1:]
            ),
        ),
    )


def _successful_document_example(
    execution_id: str,
    document_type: DocumentType,
) -> GenerationDocumentResult:
    file_stem = document_type.replace("_", "-")
    return GenerationDocumentResult(
        document_type=document_type,
        state="completed",
        files=(
            GeneratedFile(
                file_name=f"{file_stem}.pdf",
                content_type="application/pdf",
                download_url=(f"https://example.invalid/generation/{execution_id}/{file_stem}.pdf"),
            ),
        ),
    )


__all__ = [
    "GENERATION_EXAMPLE_SCENARIOS",
    "ExampleDocumentGenerator",
    "GenerationExampleScenario",
    "generation_result_example",
]
