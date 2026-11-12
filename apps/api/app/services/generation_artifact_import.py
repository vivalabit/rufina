"""Store rendered documents of a run as application documents and run artifacts."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import (
    DocumentAttachmentRecord,
    DocumentFileRecord,
    DocumentRecord,
    DocumentVersionRecord,
)
from app.models.generation_runs import (
    ApplicationGenerationRunRecord,
    GenerationRunArtifactRecord,
)
from app.services.document_docx import DOCX_CONTENT_TYPE
from app.services.document_rendering import RenderedDocument
from app.services.generation_store import persist_run_artifact

_ARTIFACT_PREFIX = {"tailored_resume": "resume", "cover_letter": "cover_letter"}
_FILE_LABEL = {"tailored_resume": "CV", "cover_letter": "Cover_Letter"}


@dataclass(frozen=True)
class DocumentImport:
    rendered: RenderedDocument
    # Structured content of exactly this file, as JSON.
    content: str
    title: str
    file_stem: str
    docx: bytes | None = None


def document_file_stem(full_name: str, document_type: str, company: str) -> str:
    """`Firstname_Lastname_CV_Company`, in ASCII so every portal accepts the upload."""

    def part(value: str) -> str:
        ascii_value = (
            unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
        )
        return re.sub(r"[^A-Za-z0-9]+", "_", ascii_value).strip("_")

    parts = [part(full_name), _FILE_LABEL[document_type], part(company)[:40].strip("_")]
    return "_".join(item for item in parts if item)[:120] or "Application"


def import_rendered_documents(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    job_id: str,
    items: tuple[DocumentImport, ...] | list[DocumentImport],
    new_version: bool = False,
) -> tuple[DocumentRecord, ...]:
    """Attach each rendered file to the application as a new document version.

    A recovered run does not import the same file twice. `new_version` is used
    when a finished run is rendered again in another template.
    """
    return tuple(
        _import_document(db, run=run, job_id=job_id, item=item, new_version=new_version)
        for item in items
    )


def _import_document(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    job_id: str,
    item: DocumentImport,
    new_version: bool,
) -> DocumentRecord:
    rendered = item.rendered
    prefix = _ARTIFACT_PREFIX[rendered.document_type]
    pdf_artifact_type = f"{prefix}_pdf"
    if not new_version:
        existing = db.scalar(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type == pdf_artifact_type,
                GenerationRunArtifactRecord.document_id.is_not(None),
            )
        )
        if existing is not None:
            document = db.get(DocumentRecord, existing.document_id)
            if document is not None:
                return document

    now = datetime.now(UTC)
    document = db.scalar(
        select(DocumentRecord)
        .join(DocumentAttachmentRecord)
        .where(
            DocumentAttachmentRecord.application_id == run.application_id,
            DocumentRecord.type == rendered.document_type,
            DocumentRecord.job_id == job_id,
        )
        .order_by(DocumentRecord.updated_at.desc(), DocumentRecord.id.desc())
        .limit(1)
    )
    is_new = document is None
    if document is None:
        document = DocumentRecord(
            id=uuid4().hex,
            type=rendered.document_type,
            title=item.title,
            job_id=job_id,
            current_version=0,
            created_at=now,
            updated_at=now,
        )
    document_version = document.current_version + 1
    document.title = item.title
    document.current_version = document_version
    document.updated_at = now
    document.versions.append(
        DocumentVersionRecord(
            id=uuid4().hex,
            document_id=document.id,
            version=document_version,
            content=item.content,
            created_at=now,
        )
    )
    file_name = f"{item.file_stem}.pdf"
    document.files.append(
        DocumentFileRecord(
            id=uuid4().hex,
            document_id=document.id,
            version=document_version,
            template_id=None,
            file_name=file_name,
            content_type="application/pdf",
            renderer_template_id=rendered.template_id[:80],
            renderer_template_version=rendered.template_version[:40],
            renderer_design_sha256=rendered.design_sha256,
            content=rendered.pdf,
            created_at=now,
        )
    )
    if is_new:
        document.attachments.append(
            DocumentAttachmentRecord(
                id=uuid4().hex,
                document_id=document.id,
                application_id=run.application_id,
                created_at=now,
            )
        )
    db.add(document)
    db.flush()

    metadata = {
        "engine": "chromium",
        "templateId": rendered.template_id,
        "templateVersion": rendered.template_version,
        "templateSha256": rendered.design_sha256,
        "pageCount": rendered.page_count,
        "fitScale": rendered.fit_scale,
        "droppedStatementIds": list(rendered.dropped_statement_ids),
        "atsReadable": rendered.ats_readable,
    }
    persist_run_artifact(
        db,
        run=run,
        document_type=rendered.document_type,
        artifact_type=pdf_artifact_type,
        file_name=file_name,
        content_type="application/pdf",
        content=rendered.pdf,
        metadata=metadata,
        document_id=document.id,
        document_version=document_version,
    )
    if item.docx is not None:
        persist_run_artifact(
            db,
            run=run,
            document_type=rendered.document_type,
            artifact_type=f"{prefix}_docx",
            file_name=f"{item.file_stem}.docx",
            content_type=DOCX_CONTENT_TYPE,
            content=item.docx,
            metadata={
                "templateId": rendered.template_id,
                "templateVersion": rendered.template_version,
            },
            document_id=document.id,
            document_version=document_version,
        )
    return document


__all__ = ["DocumentImport", "document_file_stem", "import_rendered_documents"]
