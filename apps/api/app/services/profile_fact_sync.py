from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.resume import (
    ConfirmedProfileFactRecord,
    ConfirmedProfileFactResponse,
    MasterResume,
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
)
from app.services.resume_master_review import _canonical_resume_hash


class ProfileFactSyncError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def confirm_profile_fact(
    db: Session,
    *,
    master_resume_id: str,
    fact_text: str,
    expected_version: int,
    idempotency_key: str,
    source_run_id: str | None = None,
) -> ConfirmedProfileFactResponse:
    """Promote an explicit user confirmation into a new immutable master version."""

    existing = db.scalar(
        select(ConfirmedProfileFactRecord).where(
            ConfirmedProfileFactRecord.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if (
            existing.resume_master_id != master_resume_id
            or existing.fact_text != fact_text
            or existing.source_run_id != source_run_id
        ):
            raise ProfileFactSyncError(
                "Idempotency key was already used for another confirmed fact",
                code="idempotency_conflict",
            )
        return _fact_response(existing)

    master = db.scalar(
        select(ResumeMasterRecord)
        .where(ResumeMasterRecord.id == master_resume_id)
        .with_for_update()
    )
    if master is None:
        raise ProfileFactSyncError("Master resume was not found", code="not_found")
    if master.current_version != expected_version:
        raise ProfileFactSyncError(
            "Master resume changed after the fact was reviewed",
            code="stale_version",
        )

    current = db.scalar(
        select(ResumeMasterVersionRecord).where(
            ResumeMasterVersionRecord.resume_master_id == master.id,
            ResumeMasterVersionRecord.version == master.current_version,
        )
    )
    if current is None:
        raise ProfileFactSyncError(
            "Current master resume version is unavailable",
            code="version_not_found",
        )

    fact_id = uuid4().hex
    evidence_id = f"confirmation:{fact_id}"
    updated_data = deepcopy(current.data)
    updated_data["evidence"] = [
        *(updated_data.get("evidence") or []),
        {
            "id": evidence_id,
            "type": "confirmation",
            "text": fact_text,
            "claimType": None,
            "experienceId": None,
            "sourceId": source_run_id,
        },
    ]

    sections = list(updated_data.get("additionalSections") or [])
    confirmed_section = next(
        (item for item in sections if item.get("id") == "confirmed-facts"),
        None,
    )
    new_item = {
        "id": f"confirmed-fact:{fact_id}",
        "text": fact_text,
        "evidenceIds": [evidence_id],
    }
    if confirmed_section is None:
        sections.append(
            {
                "id": "confirmed-facts",
                "title": "Confirmed facts",
                "items": [new_item],
            }
        )
    else:
        confirmed_section["items"] = [*(confirmed_section.get("items") or []), new_item]
    updated_data["additionalSections"] = sections
    section_order = list(updated_data.get("sectionOrder") or [])
    if "additional" not in section_order:
        section_order.append("additional")
    updated_data["sectionOrder"] = section_order

    validated = MasterResume.model_validate(updated_data)
    canonical_data = validated.model_dump(mode="json", by_alias=True)
    next_version = current.version + 1
    version_record = ResumeMasterVersionRecord(
        id=uuid4().hex,
        resume_master_id=master.id,
        version=next_version,
        schema_version=validated.schema_version,
        data=canonical_data,
        content_sha256=_canonical_resume_hash(canonical_data),
        source_file_id=current.source_file_id,
    )
    fact_record = ConfirmedProfileFactRecord(
        id=fact_id,
        resume_master_id=master.id,
        source_run_id=source_run_id,
        from_version=current.version,
        to_version=next_version,
        fact_text=fact_text,
        evidence_id=evidence_id,
        idempotency_key=idempotency_key,
    )
    master.current_version = next_version
    db.add_all([version_record, fact_record])
    db.commit()
    db.refresh(fact_record)
    return _fact_response(fact_record)


def _fact_response(record: ConfirmedProfileFactRecord) -> ConfirmedProfileFactResponse:
    return ConfirmedProfileFactResponse(
        id=record.id,
        masterResumeId=record.resume_master_id,
        fromVersion=record.from_version,
        toVersion=record.to_version,
        evidenceId=record.evidence_id,
        factText=record.fact_text,
        sourceRunId=record.source_run_id,
        createdAt=record.created_at,
    )


__all__ = ["ProfileFactSyncError", "confirm_profile_fact"]
