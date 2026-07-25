from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, uuid4, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.models.documents import (
    DocumentFileRecord,
    DocumentGenerationProvenanceRecord,
    DocumentRecord,
    DocumentVersionGenerationProvenanceRecord,
    DocumentVersionRecord,
)
from app.models.resume import (
    AtsFinalReviewRecord,
    ExperienceRewriteRecord,
    FinalResume,
    SeniorRecruiterAnalysisRecord,
)


PDF_CONTENT_TYPE = "application/pdf"
RESUME_PDF_ARTIFACT_SCHEMA_VERSION = "1.0"


@dataclass(frozen=True)
class StoredResumePdfArtifact:
    document: DocumentRecord
    file: DocumentFileRecord
    created: bool


def find_resume_pdf_artifact(
    db: Session,
    *,
    ats_final_review_id: str,
    template_id: str,
    template_version: str,
) -> StoredResumePdfArtifact | None:
    artifact = db.scalar(
        select(DocumentFileRecord)
        .join(DocumentRecord)
        .where(
            DocumentFileRecord.source_ats_final_review_id == ats_final_review_id,
            DocumentFileRecord.renderer_template_id == template_id,
            DocumentFileRecord.renderer_template_version == template_version,
        )
    )
    if artifact is None:
        return None
    document = db.get(DocumentRecord, artifact.document_id)
    if document is None:
        return None
    return StoredResumePdfArtifact(
        document=document,
        file=artifact,
        created=False,
    )


def store_resume_pdf_artifact(
    db: Session,
    *,
    ats_review: AtsFinalReviewRecord,
    experience_rewrite: ExperienceRewriteRecord,
    recruiter_analysis: SeniorRecruiterAnalysisRecord,
    final_resume: FinalResume,
    pdf: bytes,
    file_name: str,
    template_id: str,
    template_version: str,
    created_at: datetime,
) -> StoredResumePdfArtifact:
    existing = find_resume_pdf_artifact(
        db,
        ats_final_review_id=ats_review.id,
        template_id=template_id,
        template_version=template_version,
    )
    if existing is not None:
        return existing

    final_resume_json = final_resume.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    stage_results = {
        "schemaVersion": RESUME_PDF_ARTIFACT_SCHEMA_VERSION,
        "seniorRecruiterAnalysis": recruiter_analysis.result,
        "experienceRewrite": experience_rewrite.result,
        "atsFinalReview": ats_review.result,
    }
    input_versions = {
        "schemaVersion": RESUME_PDF_ARTIFACT_SCHEMA_VERSION,
        "resumeMasterId": ats_review.resume_master_id,
        "resumeMasterVersionId": ats_review.resume_master_version_id,
        "targetJobId": ats_review.target_job_id,
        "seniorRecruiterAnalysisId": recruiter_analysis.id,
        "experienceRewriteId": experience_rewrite.id,
        "atsFinalReviewId": ats_review.id,
        "templateId": template_id,
        "templateVersion": template_version,
    }
    generation_fingerprint = hashlib.sha256(
        json.dumps(
            input_versions,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    provenance = {
        **input_versions,
        "artifactSchemaVersion": RESUME_PDF_ARTIFACT_SCHEMA_VERSION,
        "contentType": PDF_CONTENT_TYPE,
        "fileName": file_name,
        "contentSha256": hashlib.sha256(pdf).hexdigest(),
        "createdAt": created_at.isoformat(),
        "stages": {
            "seniorRecruiterAnalysis": stage_provenance(recruiter_analysis),
            "experienceRewrite": stage_provenance(experience_rewrite),
            "atsFinalReview": stage_provenance(ats_review),
        },
    }
    owner_id = get_bound_owner_id()
    document_id = str(
        uuid5(
            NAMESPACE_URL,
            (f"rufina:resume-pdf:{owner_id}:{ats_review.id}:{template_id}:{template_version}"),
        )
    )
    document = DocumentRecord(
        id=document_id,
        type="tailored_resume",
        title=f"{final_resume.basics.full_name} resume",
        job_id=ats_review.target_job_id,
        current_version=1,
        created_at=created_at,
        updated_at=created_at,
    )
    document.versions.append(
        DocumentVersionRecord(
            id=str(uuid4()),
            document_id=document_id,
            version=1,
            content=json.dumps(
                final_resume_json,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ),
            created_at=created_at,
        )
    )
    artifact = DocumentFileRecord(
        id=str(uuid4()),
        document_id=document_id,
        version=1,
        template_id=None,
        file_name=file_name,
        content_type=PDF_CONTENT_TYPE,
        renderer_template_id=template_id,
        renderer_template_version=template_version,
        source_ats_final_review_id=ats_review.id,
        final_resume_json=final_resume_json,
        stage_results=stage_results,
        provenance=provenance,
        content=pdf,
        created_at=created_at,
    )
    document.files.append(artifact)
    document.generation_provenance = DocumentGenerationProvenanceRecord(
        document_id=document_id,
        generation_fingerprint=generation_fingerprint,
        generation_model=ats_review.model,
        generation_backend=ats_review.backend,
        input_versions=input_versions,
        created_at=created_at,
    )
    document.version_generation_provenance.append(
        DocumentVersionGenerationProvenanceRecord(
            document_id=document_id,
            version=1,
            generation_fingerprint=generation_fingerprint,
            generation_model=ats_review.model,
            generation_backend=ats_review.backend,
            input_versions=input_versions,
            created_at=created_at,
        )
    )
    db.add(document)
    db.flush()
    return StoredResumePdfArtifact(
        document=document,
        file=artifact,
        created=True,
    )


def stage_provenance(
    record: (SeniorRecruiterAnalysisRecord | ExperienceRewriteRecord | AtsFinalReviewRecord),
) -> dict[str, object]:
    return {
        "id": record.id,
        "promptVersion": record.prompt_version,
        "model": record.model,
        "backend": record.backend,
        "providerSessionId": record.provider_session_id,
        "usage": {
            "inputTokens": record.input_tokens,
            "outputTokens": record.output_tokens,
            "totalTokens": record.total_tokens,
            "source": record.token_count_source,
        },
        "latencyMs": record.latency_ms,
        "createdAt": record.created_at.isoformat(),
    }


__all__ = [
    "PDF_CONTENT_TYPE",
    "RESUME_PDF_ARTIFACT_SCHEMA_VERSION",
    "StoredResumePdfArtifact",
    "find_resume_pdf_artifact",
    "stage_provenance",
    "store_resume_pdf_artifact",
]
