from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import cast
from urllib.parse import quote
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session, load_only

from app.models.profile import (
    ProfileFileKind,
    ProfileFilePayload,
    ProfileFileRecord,
    ProfilePayload,
    utc_now,
)
from app.models.resume import ResumeSourceExtraction
from app.services.resume_source_extraction import (
    DOCX_CONTENT_TYPE,
    PDF_CONTENT_TYPE,
    ResumeSourceExtractionError,
    extract_resume_source,
)

PROFILE_FILE_LIMITS: dict[ProfileFileKind, int] = {
    "primary_resume": 15_000_000,
    "supporting_document": 5_000_000,
    "avatar": 1_000_000,
}
DOC_CONTENT_TYPE = "application/msword"
PNG_CONTENT_TYPE = "image/png"
JPEG_CONTENT_TYPE = "image/jpeg"
WEBP_CONTENT_TYPE = "image/webp"
GIF_CONTENT_TYPE = "image/gif"
MAX_EXTRACTED_TEXT_CHARACTERS = 200_000

ALLOWED_FILE_TYPES: dict[ProfileFileKind, dict[str, tuple[str, ...]]] = {
    "primary_resume": {
        PDF_CONTENT_TYPE: (".pdf",),
        DOCX_CONTENT_TYPE: (".docx",),
    },
    "supporting_document": {
        PDF_CONTENT_TYPE: (".pdf",),
        DOC_CONTENT_TYPE: (".doc",),
        DOCX_CONTENT_TYPE: (".docx",),
        PNG_CONTENT_TYPE: (".png",),
        JPEG_CONTENT_TYPE: (".jpg", ".jpeg"),
        WEBP_CONTENT_TYPE: (".webp",),
        GIF_CONTENT_TYPE: (".gif",),
    },
    "avatar": {
        PNG_CONTENT_TYPE: (".png",),
        JPEG_CONTENT_TYPE: (".jpg", ".jpeg"),
        WEBP_CONTENT_TYPE: (".webp",),
        GIF_CONTENT_TYPE: (".gif",),
    },
}


class ProfileFileValidationError(ValueError):
    pass


class ProfileFileAlreadyExistsError(ProfileFileValidationError):
    pass


class ProfileFileIdentityConflictError(ProfileFileValidationError):
    pass


def profile_file_size_limit(kind: ProfileFileKind) -> int:
    return PROFILE_FILE_LIMITS[kind]


def normalize_content_type(value: str) -> str:
    return value.partition(";")[0].strip().casefold()


def safe_profile_file_name(value: str) -> str:
    leaf_name = value.replace("\\", "/").rsplit("/", 1)[-1]
    normalized = unicodedata.normalize("NFC", leaf_name.strip())
    normalized = re.sub(r"[^\w.\- ]+", "-", normalized, flags=re.UNICODE)
    normalized = normalized[:240].rstrip(" .")
    return normalized or "profile-file"


def validate_profile_file_upload(
    *,
    kind: ProfileFileKind,
    file_name: str,
    content_type: str,
    content: bytes,
) -> tuple[str, str]:
    safe_name = safe_profile_file_name(file_name)
    normalized_content_type = normalize_content_type(content_type)
    if not content:
        raise ProfileFileValidationError("Profile file must not be empty")
    limit = profile_file_size_limit(kind)
    if len(content) > limit:
        raise ProfileFileValidationError(
            f"{kind.replace('_', ' ').title()} must be no larger than {limit} bytes"
        )

    suffix = Path(safe_name).suffix.casefold()
    if normalized_content_type in {"", "application/octet-stream"}:
        inferred_types = [
            candidate
            for candidate, candidate_extensions in ALLOWED_FILE_TYPES[kind].items()
            if suffix in candidate_extensions and _content_signature_matches(candidate, content)
        ]
        if len(inferred_types) == 1:
            normalized_content_type = inferred_types[0]

    extensions = ALLOWED_FILE_TYPES[kind].get(normalized_content_type)
    if extensions is None:
        allowed = ", ".join(sorted(ALLOWED_FILE_TYPES[kind]))
        raise ProfileFileValidationError(
            f"Unsupported {kind.replace('_', ' ')} content type; allowed: {allowed}"
        )
    if suffix not in extensions:
        raise ProfileFileValidationError(
            f"File extension does not match content type {normalized_content_type}"
        )
    if not _content_signature_matches(normalized_content_type, content):
        raise ProfileFileValidationError(
            f"File content does not match content type {normalized_content_type}"
        )
    return safe_name, normalized_content_type


def best_effort_extracted_text(
    *,
    file_name: str,
    content_type: str,
    content: bytes,
) -> str:
    if content_type not in {PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE}:
        return ""
    try:
        source = extract_resume_source(
            file_name=file_name,
            content_type=content_type,
            content=content,
        )
    except ResumeSourceExtractionError:
        return ""
    return source.text[:MAX_EXTRACTED_TEXT_CHARACTERS]


def extract_profile_resume_source(record: ProfileFileRecord) -> ResumeSourceExtraction:
    if record.kind != "primary_resume":
        raise ProfileFileValidationError("Profile file is not the primary resume")
    if record.content_type not in {PDF_CONTENT_TYPE, DOCX_CONTENT_TYPE}:
        raise ProfileFileValidationError("Primary resume must be a PDF or DOCX file")
    return extract_resume_source(
        file_name=record.file_name,
        content_type=record.content_type,
        content=record.content,
    )


def store_profile_file(
    db: Session,
    *,
    kind: ProfileFileKind,
    file_name: str,
    content_type: str,
    content: bytes,
    extracted_text: str = "",
    title: str = "",
    category: str = "",
    language: str = "",
    issuer: str = "",
    notes: str = "",
    replace_singleton: bool = True,
    legacy_document_id: str | None = None,
) -> ProfileFileRecord:
    safe_name, normalized_content_type = validate_profile_file_upload(
        kind=kind,
        file_name=file_name,
        content_type=content_type,
        content=content,
    )
    content_sha256 = hashlib.sha256(content).hexdigest()
    normalized_legacy_id = (legacy_document_id or "").strip()[:160] or None
    if normalized_legacy_id is not None and kind != "supporting_document":
        raise ProfileFileValidationError("legacyDocumentId is only valid for supporting documents")
    if normalized_legacy_id is not None:
        existing_legacy = db.scalar(
            select(ProfileFileRecord).where(
                ProfileFileRecord.kind == kind,
                ProfileFileRecord.legacy_document_id == normalized_legacy_id,
            )
        )
        if existing_legacy is not None:
            if existing_legacy.content_sha256 != content_sha256:
                raise ProfileFileIdentityConflictError(
                    "legacyDocumentId already identifies a different profile file"
                )
            return existing_legacy

    existing = None
    if kind in {"primary_resume", "avatar"}:
        existing = db.scalar(
            select(ProfileFileRecord).where(
                ProfileFileRecord.kind == kind,
                ProfileFileRecord.content_sha256 == content_sha256,
            )
        )
    now = utc_now()
    normalized_metadata = {
        "title": _clean_metadata(title, 240) or Path(safe_name).stem[:240],
        "category": _clean_metadata(category, 80),
        "language": _clean_metadata(language, 40),
        "issuer": _clean_metadata(issuer, 240),
        "notes": _clean_metadata(notes, 2_000),
    }
    if existing is not None:
        existing.file_name = safe_name
        existing.content_type = normalized_content_type
        existing.size_bytes = len(content)
        existing.extracted_text = extracted_text[:MAX_EXTRACTED_TEXT_CHARACTERS]
        existing.updated_at = now
        for field, value in normalized_metadata.items():
            setattr(existing, field, value)
        db.flush()
        return existing

    if kind in {"primary_resume", "avatar"}:
        singleton = db.scalar(select(ProfileFileRecord).where(ProfileFileRecord.kind == kind))
        if singleton is not None:
            if not replace_singleton:
                raise ProfileFileAlreadyExistsError(f"A {kind.replace('_', ' ')} is already stored")
            db.delete(singleton)
            # Force DELETE before INSERT to satisfy the portable singleton key.
            db.flush()

    record = ProfileFileRecord(
        id=str(uuid4()),
        kind=kind,
        singleton_key=kind if kind in {"primary_resume", "avatar"} else None,
        file_name=safe_name,
        content_type=normalized_content_type,
        content_sha256=content_sha256,
        legacy_document_id=normalized_legacy_id,
        size_bytes=len(content),
        content=content,
        extracted_text=extracted_text[:MAX_EXTRACTED_TEXT_CHARACTERS],
        created_at=now,
        updated_at=now,
        **normalized_metadata,
    )
    db.add(record)
    db.flush()
    return record


def list_profile_files(
    db: Session,
    *,
    kind: ProfileFileKind | None = None,
) -> list[tuple[ProfileFileRecord, bool]]:
    metadata_columns = (
        ProfileFileRecord.id,
        ProfileFileRecord.kind,
        ProfileFileRecord.title,
        ProfileFileRecord.category,
        ProfileFileRecord.language,
        ProfileFileRecord.issuer,
        ProfileFileRecord.notes,
        ProfileFileRecord.file_name,
        ProfileFileRecord.content_type,
        ProfileFileRecord.content_sha256,
        ProfileFileRecord.legacy_document_id,
        ProfileFileRecord.size_bytes,
        ProfileFileRecord.created_at,
        ProfileFileRecord.updated_at,
    )
    has_extracted_text = func.length(ProfileFileRecord.extracted_text) > 0
    statement = select(ProfileFileRecord, has_extracted_text).options(load_only(*metadata_columns))
    if kind is not None:
        statement = statement.where(ProfileFileRecord.kind == kind)
    rows = db.execute(
        statement.order_by(
            ProfileFileRecord.updated_at.desc(),
            ProfileFileRecord.created_at.desc(),
            ProfileFileRecord.id,
        )
    ).all()
    return [(record, bool(extracted_text_available)) for record, extracted_text_available in rows]


def enrich_profile_with_files(db: Session, profile: ProfilePayload) -> ProfilePayload:
    """Hydrate AI-only metadata without loading binary content."""
    metadata_columns = (
        ProfileFileRecord.id,
        ProfileFileRecord.kind,
        ProfileFileRecord.title,
        ProfileFileRecord.category,
        ProfileFileRecord.language,
        ProfileFileRecord.issuer,
        ProfileFileRecord.notes,
        ProfileFileRecord.file_name,
        ProfileFileRecord.content_type,
        ProfileFileRecord.content_sha256,
        ProfileFileRecord.legacy_document_id,
        ProfileFileRecord.size_bytes,
        ProfileFileRecord.created_at,
        ProfileFileRecord.updated_at,
    )
    primary_resume = db.scalar(
        select(ProfileFileRecord)
        .options(load_only(*metadata_columns, ProfileFileRecord.extracted_text))
        .where(ProfileFileRecord.kind == "primary_resume")
        .order_by(
            ProfileFileRecord.updated_at.desc(),
            ProfileFileRecord.created_at.desc(),
            ProfileFileRecord.id,
        )
    )
    supporting_documents = db.scalars(
        select(ProfileFileRecord)
        .options(load_only(*metadata_columns))
        .where(ProfileFileRecord.kind == "supporting_document")
        .order_by(
            ProfileFileRecord.updated_at.desc(),
            ProfileFileRecord.created_at.desc(),
            ProfileFileRecord.id,
        )
    ).all()

    profile.runtime_primary_resume = (
        _runtime_profile_file_metadata(primary_resume, include_extracted_text=True)
        if primary_resume is not None
        else None
    )
    profile.runtime_supporting_documents = [
        _runtime_profile_file_metadata(record, include_extracted_text=False)
        for record in supporting_documents
    ]
    return profile


def get_profile_file(db: Session, file_id: str) -> ProfileFileRecord | None:
    return db.scalar(select(ProfileFileRecord).where(ProfileFileRecord.id == file_id))


def update_profile_file_metadata(
    record: ProfileFileRecord,
    changes: dict[str, str | None],
) -> None:
    if record.kind != "supporting_document":
        raise ProfileFileValidationError("Only supporting document metadata can be edited")
    for field in ("title", "category", "language", "issuer", "notes"):
        if field not in changes:
            continue
        value = changes[field]
        limit = 2_000 if field == "notes" else 240
        if field == "category":
            limit = 80
        elif field == "language":
            limit = 40
        setattr(record, field, _clean_metadata(value or "", limit))
    record.updated_at = utc_now()


def profile_file_payload(
    record: ProfileFileRecord,
    *,
    extracted_text_available: bool | None = None,
) -> ProfileFilePayload:
    return ProfileFilePayload(
        id=record.id,
        kind=cast(ProfileFileKind, record.kind),
        title=record.title,
        category=record.category,
        language=record.language,
        issuer=record.issuer,
        notes=record.notes,
        file_name=record.file_name,
        size_bytes=record.size_bytes,
        content_type=record.content_type,
        content_sha256=record.content_sha256,
        extracted_text_available=(
            bool(record.extracted_text.strip())
            if extracted_text_available is None
            else extracted_text_available
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
        download_url=f"/profile/files/{record.id}",
    )


def profile_file_content_disposition(file_name: str, *, inline: bool = False) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name).strip("-._")
    ascii_name = re.sub(r"-+", "-", ascii_name) or "profile-file"
    disposition = "inline" if inline else "attachment"
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(file_name, safe='')}"


def _runtime_profile_file_metadata(
    record: ProfileFileRecord,
    *,
    include_extracted_text: bool,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "id": record.id,
        "kind": record.kind,
        "title": record.title,
        "category": record.category,
        "language": record.language,
        "issuer": record.issuer,
        "notes": record.notes,
        "file_name": record.file_name,
        "size_bytes": record.size_bytes,
        "content_type": record.content_type,
        "content_sha256": record.content_sha256,
        "legacy_document_id": record.legacy_document_id,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
    if include_extracted_text:
        metadata["extracted_text"] = record.extracted_text.strip()
    return metadata


def _clean_metadata(value: str, limit: int) -> str:
    return unicodedata.normalize("NFC", value.strip())[:limit]


def _content_signature_matches(content_type: str, content: bytes) -> bool:
    if content_type == PDF_CONTENT_TYPE:
        return content.startswith(b"%PDF-")
    if content_type == DOCX_CONTENT_TYPE:
        return content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if content_type == DOC_CONTENT_TYPE:
        return content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if content_type == PNG_CONTENT_TYPE:
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == JPEG_CONTENT_TYPE:
        return content.startswith(b"\xff\xd8\xff")
    if content_type == WEBP_CONTENT_TYPE:
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if content_type == GIF_CONTENT_TYPE:
        return content.startswith((b"GIF87a", b"GIF89a"))
    return False


__all__ = [
    "ProfileFileAlreadyExistsError",
    "ProfileFileIdentityConflictError",
    "ProfileFileValidationError",
    "best_effort_extracted_text",
    "enrich_profile_with_files",
    "extract_profile_resume_source",
    "get_profile_file",
    "list_profile_files",
    "normalize_content_type",
    "profile_file_content_disposition",
    "profile_file_payload",
    "profile_file_size_limit",
    "store_profile_file",
    "update_profile_file_metadata",
    "validate_profile_file_upload",
]
