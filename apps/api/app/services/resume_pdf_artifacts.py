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
    ImaginatorResumeRecord,
    SeniorRecruiterAnalysisRecord,
)
from app.services.resume_pdf_renderer import ResolvedResumeTemplate

PDF_CONTENT_TYPE = "application/pdf"
RESUME_PDF_ARTIFACT_SCHEMA_VERSION = "1.2"


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
    design_sha256: str,
) -> StoredResumePdfArtifact | None:
    artifact = db.scalar(
        select(DocumentFileRecord)
        .join(DocumentRecord)
        .where(
            DocumentFileRecord.source_ats_final_review_id == ats_final_review_id,
            DocumentFileRecord.renderer_template_id == template_id,
            DocumentFileRecord.renderer_template_version == template_version,
            DocumentFileRecord.renderer_design_sha256 == design_sha256,
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
    template: ResolvedResumeTemplate,
    created_at: datetime,
) -> StoredResumePdfArtifact:
    existing = find_resume_pdf_artifact(
        db,
        ats_final_review_id=ats_review.id,
        template_id=template.id,
        template_version=template.version,
        design_sha256=template.design_sha256,
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
        "generationMode": "recruiter_xyz_ats",
        "resumeMasterId": ats_review.resume_master_id,
        "resumeMasterVersionId": ats_review.resume_master_version_id,
        "targetJobId": ats_review.target_job_id,
        "documentLanguage": final_resume.language,
        "seniorRecruiterAnalysisId": recruiter_analysis.id,
        "experienceRewriteId": experience_rewrite.id,
        "atsFinalReviewId": ats_review.id,
        "templateId": template.id,
        "templateVersion": template.version,
        "customTemplateId": template.id,
        "customTemplateVersion": template.version,
        "baseTemplateId": template.base_template_id,
        "designHash": template.design_sha256,
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
            (
                f"rufina:resume-pdf:{owner_id}:{ats_review.id}:"
                f"{template.id}:{template.version}:{template.design_sha256}"
            ),
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
        renderer_template_id=template.id,
        renderer_template_version=template.version,
        renderer_design_sha256=template.design_sha256,
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


def find_imaginator_resume_pdf_artifact(
    db: Session,
    *,
    imaginator_resume_id: str,
    template_id: str,
    template_version: str,
    design_sha256: str,
) -> StoredResumePdfArtifact | None:
    artifact = db.scalar(
        select(DocumentFileRecord)
        .join(DocumentRecord)
        .where(
            DocumentFileRecord.source_imaginator_resume_id == imaginator_resume_id,
            DocumentFileRecord.renderer_template_id == template_id,
            DocumentFileRecord.renderer_template_version == template_version,
            DocumentFileRecord.renderer_design_sha256 == design_sha256,
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


def store_imaginator_resume_pdf_artifact(
    db: Session,
    *,
    imaginator_resume: ImaginatorResumeRecord,
    final_resume: FinalResume,
    pdf: bytes,
    file_name: str,
    template: ResolvedResumeTemplate,
    created_at: datetime,
) -> StoredResumePdfArtifact:
    existing = find_imaginator_resume_pdf_artifact(
        db,
        imaginator_resume_id=imaginator_resume.id,
        template_id=template.id,
        template_version=template.version,
        design_sha256=template.design_sha256,
    )
    if existing is not None:
        return existing

    final_resume_json = final_resume.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    stage_results = {
        "schemaVersion": RESUME_PDF_ARTIFACT_SCHEMA_VERSION,
        "generationMode": "imaginator",
        "imaginator": imaginator_resume.result,
        "claimLedger": imaginator_resume.claim_ledger,
        "protectedFactsAudit": imaginator_resume.protected_facts_audit,
    }
    input_versions = {
        "schemaVersion": RESUME_PDF_ARTIFACT_SCHEMA_VERSION,
        "generationMode": "imaginator",
        "resumeMasterId": imaginator_resume.resume_master_id,
        "resumeMasterVersionId": imaginator_resume.resume_master_version_id,
        "targetJobId": imaginator_resume.target_job_id,
        "documentLanguage": final_resume.language,
        "imaginatorResumeId": imaginator_resume.id,
        "imaginatorPromptVersion": imaginator_resume.prompt_version,
        "imaginatorConstraintsVersion": imaginator_resume.constraints_version,
        "imaginatorAuditPromptVersion": imaginator_resume.protected_facts_audit.get(
            "promptVersion",
            "",
        ),
        "imaginatorInputFingerprint": imaginator_resume.input_fingerprint,
        "templateId": template.id,
        "templateVersion": template.version,
        "customTemplateId": template.id,
        "customTemplateVersion": template.version,
        "baseTemplateId": template.base_template_id,
        "designHash": template.design_sha256,
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
        "syntheticClaimCount": sum(
            1 for item in imaginator_resume.claim_ledger if item.get("origin") == "synthetic"
        ),
        "lockedClaimCount": sum(
            1 for item in imaginator_resume.claim_ledger if item.get("origin") == "locked_source"
        ),
        "protectedFactsAudit": {
            "passed": imaginator_resume.protected_facts_audit.get(
                "passed",
                False,
            ),
            "auditedClaimCount": imaginator_resume.protected_facts_audit.get(
                "auditedClaimCount",
                0,
            ),
            "inputFingerprint": (
                imaginator_resume.protected_facts_audit.get("result", {}).get(
                    "inputFingerprint",
                    "",
                )
                if isinstance(
                    imaginator_resume.protected_facts_audit.get("result"),
                    dict,
                )
                else ""
            ),
            "model": imaginator_resume.protected_facts_audit.get("model", ""),
            "backend": imaginator_resume.protected_facts_audit.get(
                "backend",
                "",
            ),
        },
        "stages": {
            "imaginator": stage_provenance(imaginator_resume),
        },
    }
    owner_id = get_bound_owner_id()
    document_id = str(
        uuid5(
            NAMESPACE_URL,
            (
                f"rufina:resume-pdf:{owner_id}:imaginator:"
                f"{imaginator_resume.id}:{template.id}:{template.version}:"
                f"{template.design_sha256}"
            ),
        )
    )
    document = DocumentRecord(
        id=document_id,
        type="tailored_resume",
        title=f"{final_resume.basics.full_name} resume",
        job_id=imaginator_resume.target_job_id,
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
        renderer_template_id=template.id,
        renderer_template_version=template.version,
        renderer_design_sha256=template.design_sha256,
        source_imaginator_resume_id=imaginator_resume.id,
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
        generation_model=imaginator_resume.model,
        generation_backend=imaginator_resume.backend,
        input_versions=input_versions,
        created_at=created_at,
    )
    document.version_generation_provenance.append(
        DocumentVersionGenerationProvenanceRecord(
            document_id=document_id,
            version=1,
            generation_fingerprint=generation_fingerprint,
            generation_model=imaginator_resume.model,
            generation_backend=imaginator_resume.backend,
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
    record: (
        SeniorRecruiterAnalysisRecord
        | ExperienceRewriteRecord
        | AtsFinalReviewRecord
        | ImaginatorResumeRecord
    ),
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
    "find_imaginator_resume_pdf_artifact",
    "find_resume_pdf_artifact",
    "stage_provenance",
    "store_imaginator_resume_pdf_artifact",
    "store_resume_pdf_artifact",
]
