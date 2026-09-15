from __future__ import annotations

import json
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
from app.models.generation_workflow import DraftBundle
from app.services.generation_latex import CompiledDocument, safe_document_stem
from app.services.generation_snapshot import (
    GenerationRunSnapshot,
    GenerationTemplateSnapshot,
    resolve_run_resume_template,
)
from app.services.generation_store import persist_run_artifact


def import_compiled_generation_documents(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    bundle: DraftBundle,
    compiled: tuple[CompiledDocument, ...],
) -> tuple[DocumentRecord, ...]:
    snapshot = GenerationRunSnapshot.model_validate(run.input_snapshot)
    vacancy = snapshot.request.vacancy.data
    role = str(vacancy.get("title") or "Application")
    company = str(vacancy.get("company") or "")
    stem = safe_document_stem(f"{company}-{role}")
    templates = {item.document_type: item for item in snapshot.templates}
    if "tailored_resume" in snapshot.request.document_types:
        templates["tailored_resume"] = resolve_run_resume_template(snapshot)
    documents: list[DocumentRecord] = []
    for rendered in compiled:
        structured = (
            bundle.resume if rendered.document_type == "tailored_resume" else bundle.cover_letter
        )
        if structured is None:
            continue
        document = _import_compiled_document(
            db,
            run=run,
            rendered=rendered,
            content=json.dumps(
                structured.model_dump(mode="json", by_alias=True),
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            title=(
                f"{role} — Tailored CV"
                if rendered.document_type == "tailored_resume"
                else f"{role} — Cover letter"
            ),
            job_id=snapshot.request.vacancy.id,
            file_name=(
                f"{stem}-cv.pdf"
                if rendered.document_type == "tailored_resume"
                else f"{stem}-cover-letter.pdf"
            ),
            template=templates[rendered.document_type],
        )
        documents.append(document)
    return tuple(documents)


def _import_compiled_document(
    db: Session,
    *,
    run: ApplicationGenerationRunRecord,
    rendered: CompiledDocument,
    content: str,
    title: str,
    job_id: str,
    file_name: str,
    template: GenerationTemplateSnapshot,
) -> DocumentRecord:
    pdf_artifact_type = (
        "resume_pdf" if rendered.document_type == "tailored_resume" else "cover_letter_pdf"
    )
    existing_artifact = db.scalar(
        select(GenerationRunArtifactRecord).where(
            GenerationRunArtifactRecord.run_id == run.id,
            GenerationRunArtifactRecord.artifact_type == pdf_artifact_type,
            GenerationRunArtifactRecord.document_id.is_not(None),
        )
    )
    if existing_artifact is not None:
        document = db.get(DocumentRecord, existing_artifact.document_id)
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
            title=title,
            job_id=job_id,
            current_version=0,
            created_at=now,
            updated_at=now,
        )
    document_version = document.current_version + 1
    document.title = title
    document.current_version = document_version
    document.updated_at = now
    document.versions.append(
        DocumentVersionRecord(
            id=uuid4().hex,
            document_id=document.id,
            version=document_version,
            content=content,
            created_at=now,
        )
    )
    document.files.append(
        DocumentFileRecord(
            id=uuid4().hex,
            document_id=document.id,
            version=document_version,
            template_id=None,
            file_name=file_name,
            content_type="application/pdf",
            renderer_template_id=template.template_id,
            renderer_template_version=template.template_version,
            renderer_design_sha256=template.content_sha256,
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

    tex_artifact = persist_run_artifact(
        db,
        run=run,
        document_type=rendered.document_type,
        artifact_type=(
            "resume_tex" if rendered.document_type == "tailored_resume" else "cover_letter_tex"
        ),
        file_name=file_name.removesuffix(".pdf") + ".tex",
        content_type="application/x-tex",
        content=rendered.tex_source.encode(),
        metadata={
            "engine": rendered.engine,
            "templateId": template.template_id,
            "templateVersion": template.template_version,
        },
        document_id=document.id,
        document_version=document_version,
    )
    pdf_artifact = persist_run_artifact(
        db,
        run=run,
        document_type=rendered.document_type,
        artifact_type=pdf_artifact_type,
        file_name=file_name,
        content_type="application/pdf",
        content=rendered.pdf,
        metadata={
            "engine": rendered.engine,
            "templateId": template.template_id,
            "templateVersion": template.template_version,
            "templateSha256": template.content_sha256,
            "sourceArtifactId": tex_artifact.id,
            "compileLog": rendered.compile_log,
        },
        document_id=document.id,
        document_version=document_version,
    )
    pdf_artifact.document_id = document.id
    return document


__all__ = ["import_compiled_generation_documents"]
