"""extract inline profile and application files into durable binary tables

Revision ID: 20260830_0047
Revises: 20260830_0046
Create Date: 2026-08-30 14:00:00.000000
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import unicodedata
import zipfile
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote_to_bytes
from uuid import NAMESPACE_URL, uuid5
from xml.etree import ElementTree

import sqlalchemy as sa
from alembic import op
from pypdf import PdfReader

revision: str = "20260830_0047"
down_revision: str | None = "20260830_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_AVATAR_URL = "/avatars/default-pug.png"
APPLICATION_ATTACHMENT_CATEGORY = "Application Attachment"
DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
LEGACY_FILE_LIMITS = {
    "primary_resume": 15_000_000,
    "supporting_document": 5_000_000,
    "avatar": 1_000_000,
}
LEGACY_FILE_TYPES = {
    "primary_resume": {
        "application/pdf": (".pdf",),
        DOCX_CONTENT_TYPE: (".docx",),
    },
    "supporting_document": {
        "application/pdf": (".pdf",),
        "application/msword": (".doc",),
        DOCX_CONTENT_TYPE: (".docx",),
        "image/png": (".png",),
        "image/jpeg": (".jpg", ".jpeg"),
        "image/webp": (".webp",),
        "image/gif": (".gif",),
    },
    "avatar": {
        "image/png": (".png",),
        "image/jpeg": (".jpg", ".jpeg"),
        "image/webp": (".webp",),
        "image/gif": (".gif",),
    },
}
INLINE_FILE_FIELD_NAMES = {
    "dataurl",
    "documents",
    "filedata",
    "legacydataurl",
    "resumedataurl",
}
SERIALIZED_DATA_URL_PATTERN = re.compile(
    r"""["']\s*data:[^,\r\n]{0,200},""",
    flags=re.IGNORECASE,
)


def upgrade() -> None:
    connection = op.get_bind()
    _validate_workspace_metadata_backfill(connection)

    op.create_table(
        "profile_files",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("singleton_key", sa.String(length=32), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("issuer", sa.String(length=240), nullable=False),
        sa.Column("notes", sa.String(length=2_000), nullable=False),
        sa.Column("file_name", sa.String(length=240), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("legacy_document_id", sa.String(length=160), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("extracted_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('primary_resume', 'supporting_document', 'avatar')",
            name="ck_profile_files_kind",
        ),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_profile_files_size_positive",
        ),
        sa.CheckConstraint(
            "(kind = 'supporting_document' AND singleton_key IS NULL) OR "
            "(kind IN ('primary_resume', 'avatar') AND singleton_key = kind)",
            name="ck_profile_files_singleton_key",
        ),
        sa.CheckConstraint(
            "kind = 'supporting_document' OR legacy_document_id IS NULL",
            name="ck_profile_files_legacy_id_kind",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "singleton_key",
            name="uq_profile_files_owner_singleton",
        ),
        sa.UniqueConstraint(
            "owner_id",
            "kind",
            "legacy_document_id",
            name="uq_profile_files_owner_kind_legacy",
        ),
    )
    op.create_index(
        op.f("ix_profile_files_content_sha256"),
        "profile_files",
        ["content_sha256"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_files_kind"),
        "profile_files",
        ["kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_files_owner_id"),
        "profile_files",
        ["owner_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_profile_files_updated_at"),
        "profile_files",
        ["updated_at"],
        unique=False,
    )

    op.add_column(
        "workspace_source_documents",
        sa.Column("size_bytes", sa.Integer(), nullable=True),
    )
    op.add_column(
        "workspace_source_documents",
        sa.Column("content_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "workspace_source_documents",
        sa.Column("legacy_document_id", sa.String(length=160), nullable=True),
    )

    _backfill_workspace_metadata(connection)
    _migrate_profile_files(connection)
    _migrate_application_files(connection)
    _scrub_application_event_files(connection)

    with op.batch_alter_table("workspace_source_documents") as batch_op:
        batch_op.alter_column(
            "size_bytes",
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "content_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_workspace_source_documents_size_positive",
            "size_bytes > 0",
        )
        batch_op.create_unique_constraint(
            "uq_workspace_source_documents_owner_application_legacy",
            ["owner_id", "application_id", "legacy_document_id"],
        )
    op.create_index(
        op.f("ix_workspace_source_documents_content_sha256"),
        "workspace_source_documents",
        ["content_sha256"],
        unique=False,
    )


def downgrade() -> None:
    # Inline Base64 payloads were intentionally scrubbed during upgrade. A schema
    # downgrade cannot reconstruct them. Refuse to drop the only remaining copy;
    # operators must export or explicitly delete migrated files first.
    connection = op.get_bind()
    profile_file_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM profile_files")
    ).scalar_one()
    migrated_application_file_count = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM workspace_source_documents "
            "WHERE category = :category AND legacy_document_id IS NOT NULL"
        ),
        {"category": APPLICATION_ATTACHMENT_CATEGORY},
    ).scalar_one()
    if profile_file_count or migrated_application_file_count:
        raise RuntimeError(
            "Cannot downgrade 20260830_0047 while migrated files remain; "
            "export or explicitly delete profile files and migrated application "
            "attachments first"
        )

    op.drop_index(
        op.f("ix_workspace_source_documents_content_sha256"),
        table_name="workspace_source_documents",
    )
    with op.batch_alter_table("workspace_source_documents") as batch_op:
        batch_op.drop_constraint(
            "uq_workspace_source_documents_owner_application_legacy",
            type_="unique",
        )
        batch_op.drop_constraint(
            "ck_workspace_source_documents_size_positive",
            type_="check",
        )
        batch_op.drop_column("legacy_document_id")
        batch_op.drop_column("content_sha256")
        batch_op.drop_column("size_bytes")

    op.drop_index(op.f("ix_profile_files_updated_at"), table_name="profile_files")
    op.drop_index(op.f("ix_profile_files_owner_id"), table_name="profile_files")
    op.drop_index(op.f("ix_profile_files_kind"), table_name="profile_files")
    op.drop_index(op.f("ix_profile_files_content_sha256"), table_name="profile_files")
    op.drop_table("profile_files")


def _backfill_workspace_metadata(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text("SELECT id, content FROM workspace_source_documents")
    ).mappings()
    for row in rows:
        content = _binary_value(row["content"])
        if not content:
            raise RuntimeError(
                "workspace_source_documents contains an empty legacy file; "
                f"cannot backfill size_bytes for {row['id']}"
            )
        connection.execute(
            sa.text(
                "UPDATE workspace_source_documents "
                "SET size_bytes = :size_bytes, content_sha256 = :content_sha256 "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "size_bytes": len(content),
                "content_sha256": hashlib.sha256(content).hexdigest(),
            },
        )


def _validate_workspace_metadata_backfill(connection: sa.Connection) -> None:
    empty_file_id = connection.execute(
        sa.text(
            "SELECT id FROM workspace_source_documents "
            "WHERE content IS NULL OR length(content) = 0 LIMIT 1"
        )
    ).scalar_one_or_none()
    if empty_file_id is not None:
        raise RuntimeError(
            "workspace_source_documents contains an empty legacy file; "
            f"cannot backfill size_bytes for {empty_file_id}"
        )


def _migrate_profile_files(connection: sa.Connection) -> None:
    migrated_at = datetime.now(UTC)
    seen: set[tuple[str, str, str]] = set()
    legacy_ids_by_owner: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    profiles = connection.execute(
        sa.text("SELECT id, owner_id, data FROM profiles ORDER BY id")
    ).mappings()
    for row in profiles:
        owner_id = _limited_text(row["owner_id"], 160, "local-owner")
        profile, is_valid_profile = _json_object_with_status(row["data"])
        avatar_url = profile.get("avatar_url")
        has_inline_avatar = isinstance(
            avatar_url, str
        ) and avatar_url.strip().casefold().startswith("data:")
        should_scrub = (
            not is_valid_profile
            or "resume_data_url" in profile
            or "documents" in profile
            or has_inline_avatar
        )

        resume_data_url = profile.pop("resume_data_url", None)
        decoded_resume = _decode_data_url(resume_data_url)
        if decoded_resume is not None:
            file_name = _limited_text(
                profile.get("resume_file_name"),
                240,
                _fallback_file_name("resume", decoded_resume[0]),
            )
            validated_resume = _validated_legacy_file("primary_resume", file_name, decoded_resume)
            if validated_resume is None:
                decoded_resume = None
            else:
                file_name, content_type, content = validated_resume
        if decoded_resume is not None:
            resume_timestamp = _legacy_datetime(
                _first_value(profile, "resume_updated_at", "resumeUpdatedAt"),
                migrated_at,
            )
            _insert_profile_file(
                connection,
                owner_id=owner_id,
                kind="primary_resume",
                singleton_key="primary_resume",
                title=file_name,
                category="CV / Resume",
                file_name=file_name,
                content_type=content_type,
                content=content,
                extracted_text=_best_effort_legacy_resume_text(
                    content_type,
                    content,
                ),
                created_at=resume_timestamp,
                seen=seen,
            )

        documents = _json_list(profile.pop("documents", None))
        for index, document in enumerate(documents):
            if not isinstance(document, Mapping):
                continue
            decoded_document = _decode_data_url(_first_value(document, "data_url", "dataUrl"))
            if decoded_document is None:
                continue
            file_name = _limited_text(
                _first_value(document, "file_name", "fileName"),
                240,
                _fallback_file_name(f"legacy-document-{index + 1}", decoded_document[0]),
            )
            validated_document = _validated_legacy_file(
                "supporting_document", file_name, decoded_document
            )
            if validated_document is None:
                continue
            file_name, content_type, content = validated_document
            requested_legacy_id = _limited_text(
                document.get("id"),
                160,
                f"legacy-document-{index}",
            )
            taken_legacy_ids = legacy_ids_by_owner[(owner_id, "supporting_document")]
            legacy_document_id = _available_legacy_id(
                requested_legacy_id,
                taken_legacy_ids,
            )
            taken_legacy_ids.add(legacy_document_id)
            _insert_profile_file(
                connection,
                owner_id=owner_id,
                kind="supporting_document",
                singleton_key=None,
                title=_limited_text(document.get("title"), 240, file_name),
                category=_limited_text(document.get("category"), 80, "Other"),
                language=_limited_text(document.get("language"), 40),
                issuer=_limited_text(document.get("issuer"), 240),
                notes=_limited_text(document.get("notes"), 2_000),
                file_name=file_name,
                content_type=content_type,
                content=content,
                legacy_document_id=legacy_document_id,
                created_at=_legacy_datetime(
                    _first_value(document, "uploaded_at", "uploadedAt"),
                    migrated_at,
                ),
                seen=seen,
            )

        if has_inline_avatar:
            decoded_avatar = _decode_data_url(avatar_url)
            profile["avatar_url"] = DEFAULT_AVATAR_URL
            if decoded_avatar is not None:
                validated_avatar = _validated_legacy_file(
                    "avatar",
                    _fallback_file_name("avatar", decoded_avatar[0]),
                    decoded_avatar,
                )
                if validated_avatar is not None:
                    file_name, content_type, content = validated_avatar
                    _insert_profile_file(
                        connection,
                        owner_id=owner_id,
                        kind="avatar",
                        singleton_key="avatar",
                        title="Profile avatar",
                        category="Avatar",
                        file_name=file_name,
                        content_type=content_type,
                        content=content,
                        created_at=migrated_at,
                        seen=seen,
                    )

        profile, nested_files_scrubbed = _scrub_inline_file_values(profile)
        should_scrub = should_scrub or nested_files_scrubbed
        if should_scrub:
            _update_json_data(connection, "profiles", row["id"], profile)

    versions = connection.execute(
        sa.text("SELECT id, data FROM profile_versions ORDER BY id")
    ).mappings()
    for row in versions:
        profile, is_valid_profile = _json_object_with_status(row["data"])
        avatar_url = profile.get("avatar_url")
        has_inline_avatar = isinstance(
            avatar_url, str
        ) and avatar_url.strip().casefold().startswith("data:")
        should_scrub = (
            not is_valid_profile
            or "resume_data_url" in profile
            or "documents" in profile
            or has_inline_avatar
        )
        profile.pop("resume_data_url", None)
        profile.pop("documents", None)
        if has_inline_avatar:
            profile["avatar_url"] = DEFAULT_AVATAR_URL
        profile, nested_files_scrubbed = _scrub_inline_file_values(profile)
        should_scrub = should_scrub or nested_files_scrubbed
        if should_scrub:
            _update_json_data(connection, "profile_versions", row["id"], profile)


def _migrate_application_files(connection: sa.Connection) -> None:
    migrated_at = datetime.now(UTC)
    existing_rows = connection.execute(
        sa.text(
            "SELECT owner_id, application_id, legacy_document_id, content_sha256 "
            "FROM workspace_source_documents"
        )
    ).mappings()
    legacy_ids_by_application: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
    preexisting_hashes: dict[tuple[str, str, str], str] = {}
    for row in existing_rows:
        key_prefix = (str(row["owner_id"]), str(row["application_id"]))
        legacy_id = row["legacy_document_id"]
        if isinstance(legacy_id, str) and legacy_id:
            legacy_ids_by_application[key_prefix].add(legacy_id)
            preexisting_hashes[(*key_prefix, legacy_id)] = str(row["content_sha256"] or "")
    claimed_requested_ids: set[tuple[str, str, str]] = set()

    applications = connection.execute(
        sa.text("SELECT id, owner_id, data FROM stored_applications ORDER BY owner_id, id")
    ).mappings()
    for row in applications:
        application_id = _limited_text(row["id"], 160)
        owner_id = _limited_text(row["owner_id"], 160, "local-owner")
        application, is_valid_application = _json_object_with_status(row["data"])
        should_scrub = not is_valid_application or "documents" in application
        documents = _json_list(application.pop("documents", None))
        for index, document in enumerate(documents):
            if not isinstance(document, Mapping):
                continue
            decoded_document = _decode_data_url(
                _first_value(document, "dataUrl", "data_url", "legacyDataUrl")
            )
            if decoded_document is None:
                continue
            file_name = _limited_text(
                _first_value(document, "fileName", "file_name"),
                240,
                _fallback_file_name(f"application-document-{index + 1}", decoded_document[0]),
            )
            validated_document = _validated_legacy_file(
                "supporting_document", file_name, decoded_document
            )
            if validated_document is None:
                continue
            file_name, content_type, content = validated_document
            content_sha256 = hashlib.sha256(content).hexdigest()
            requested_legacy_id = _limited_text(
                document.get("id"),
                160,
                f"legacy-application-document-{index + 1}",
            )
            requested_key = (owner_id, application_id, requested_legacy_id)
            if (
                requested_key in preexisting_hashes
                and requested_key not in claimed_requested_ids
                and preexisting_hashes[requested_key] == content_sha256
            ):
                claimed_requested_ids.add(requested_key)
                continue
            taken_legacy_ids = legacy_ids_by_application[(owner_id, application_id)]
            legacy_document_id = _available_legacy_id(
                requested_legacy_id,
                taken_legacy_ids,
            )
            taken_legacy_ids.add(legacy_document_id)
            claimed_requested_ids.add(requested_key)

            title = _limited_text(document.get("title"), 240, file_name)
            uploaded_at = _legacy_datetime(
                _first_value(document, "uploadedAt", "uploaded_at"),
                migrated_at,
            )
            record_id = str(
                uuid5(
                    NAMESPACE_URL,
                    "tasko:workspace-source:"
                    f"{owner_id}:{application_id}:"
                    + (
                        f"legacy:{legacy_document_id}"
                        if legacy_document_id is not None
                        else f"sha256:{content_sha256}:index:{index}"
                    ),
                )
            )
            connection.execute(
                sa.text(
                    "INSERT INTO workspace_source_documents ("
                    "id, application_id, category, title, language, file_name, "
                    "content_type, size_bytes, content_sha256, legacy_document_id, "
                    "content, created_at, updated_at, owner_id"
                    ") VALUES ("
                    ":id, :application_id, :category, :title, '', :file_name, "
                    ":content_type, :size_bytes, :content_sha256, :legacy_document_id, "
                    ":content, :created_at, :updated_at, :owner_id"
                    ")"
                ),
                {
                    "id": record_id,
                    "application_id": application_id,
                    "category": APPLICATION_ATTACHMENT_CATEGORY,
                    "title": title,
                    "file_name": file_name,
                    "content_type": content_type,
                    "size_bytes": len(content),
                    "content_sha256": content_sha256,
                    "legacy_document_id": legacy_document_id,
                    "content": content,
                    "created_at": uploaded_at,
                    "updated_at": uploaded_at,
                    "owner_id": owner_id,
                },
            )
        application, nested_files_scrubbed = _scrub_inline_file_values(application)
        should_scrub = should_scrub or nested_files_scrubbed
        if should_scrub:
            _update_json_data(connection, "stored_applications", row["id"], application)


def _scrub_application_event_files(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text("SELECT id, data FROM stored_application_events ORDER BY id")
    ).mappings()
    for row in rows:
        event_data, is_valid_event = _json_object_with_status(row["data"])
        event_data, files_scrubbed = _scrub_inline_file_values(event_data)
        if not is_valid_event or files_scrubbed:
            _update_json_data(
                connection,
                "stored_application_events",
                row["id"],
                event_data,
            )


def _insert_profile_file(
    connection: sa.Connection,
    *,
    owner_id: str,
    kind: str,
    singleton_key: str | None,
    title: str,
    category: str,
    file_name: str,
    content_type: str,
    content: bytes,
    created_at: datetime,
    seen: set[tuple[str, str, str]],
    legacy_document_id: str | None = None,
    language: str = "",
    issuer: str = "",
    notes: str = "",
    extracted_text: str = "",
) -> None:
    if not content:
        return
    content_sha256 = hashlib.sha256(content).hexdigest()
    dedupe_key = (owner_id, kind, content_sha256)
    if singleton_key is not None:
        if dedupe_key in seen:
            return
        seen.add(dedupe_key)
    identity = legacy_document_id or content_sha256
    record_id = str(
        uuid5(
            NAMESPACE_URL,
            f"tasko:profile-file:{owner_id}:{kind}:{identity}:{content_sha256}",
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO profile_files ("
            "id, owner_id, kind, singleton_key, title, category, language, "
            "issuer, notes, file_name, content_type, content_sha256, legacy_document_id, size_bytes, "
            "content, extracted_text, created_at, updated_at"
            ") VALUES ("
            ":id, :owner_id, :kind, :singleton_key, :title, :category, :language, "
            ":issuer, :notes, :file_name, :content_type, :content_sha256, :legacy_document_id, "
            ":size_bytes, :content, :extracted_text, :created_at, :updated_at"
            ")"
        ),
        {
            "id": record_id,
            "owner_id": owner_id,
            "kind": kind,
            "singleton_key": singleton_key,
            "title": title,
            "category": category,
            "language": language,
            "issuer": issuer,
            "notes": notes,
            "file_name": file_name,
            "content_type": content_type,
            "content_sha256": content_sha256,
            "legacy_document_id": legacy_document_id,
            "size_bytes": len(content),
            "content": content,
            "extracted_text": extracted_text[:200_000],
            "created_at": created_at,
            "updated_at": created_at,
        },
    )


def _decode_data_url(value: object) -> tuple[str, bytes] | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped.casefold().startswith("data:"):
        return None
    header, separator, payload = stripped[5:].partition(",")
    if not separator:
        return None
    metadata = header.split(";")
    content_type = metadata[0].strip().casefold() or "application/octet-stream"
    if len(content_type) > 160:
        return None
    try:
        if any(part.strip().casefold() == "base64" for part in metadata[1:]):
            content = base64.b64decode(payload, validate=True)
        else:
            content = unquote_to_bytes(payload)
    except (ValueError, binascii.Error):
        return None
    if not content:
        return None
    return content_type, content


def _validated_legacy_file(
    kind: str,
    file_name: str,
    decoded: tuple[str, bytes],
) -> tuple[str, str, bytes] | None:
    """Apply the same basic invariants as the runtime upload endpoints.

    Unsafe legacy payloads are scrubbed from JSON but are not promoted into the
    downloadable file stores.
    """

    content_type, content = decoded
    content_type = content_type.strip().casefold()
    if content_type == "image/jpg":
        content_type = "image/jpeg"
    allowed_types = LEGACY_FILE_TYPES[kind]
    safe_name = _safe_legacy_file_name(file_name)
    suffix = Path(safe_name).suffix.casefold()

    if content_type in {"", "application/octet-stream"}:
        inferred_types = [
            candidate
            for candidate, extensions in allowed_types.items()
            if (not suffix or suffix in extensions)
            and _legacy_signature_matches(candidate, content)
        ]
        if len(inferred_types) != 1:
            return None
        content_type = inferred_types[0]

    extensions = allowed_types.get(content_type)
    if extensions is None or len(content) > LEGACY_FILE_LIMITS[kind]:
        return None
    if not _legacy_signature_matches(content_type, content):
        return None
    if not suffix:
        safe_name = f"{safe_name}{extensions[0]}"[:240]
    elif suffix not in extensions:
        return None
    return safe_name, content_type, content


def _best_effort_legacy_resume_text(content_type: str, content: bytes) -> str:
    try:
        if content_type == "application/pdf":
            reader = PdfReader(BytesIO(content), strict=False)
            if len(reader.pages) > 50:
                return ""
            return "\n".join(page.extract_text() or "" for page in reader.pages)[:200_000]
        if content_type == DOCX_CONTENT_TYPE:
            with zipfile.ZipFile(BytesIO(content)) as archive:
                candidates = [
                    entry
                    for entry in archive.infolist()
                    if entry.filename == "word/document.xml"
                    or entry.filename.startswith(("word/header", "word/footer"))
                ]
                if (
                    len(archive.infolist()) > 2_048
                    or sum(entry.file_size for entry in candidates) > 20_000_000
                ):
                    return ""
                paragraphs: list[str] = []
                for entry in candidates:
                    root = ElementTree.fromstring(archive.read(entry))
                    text = " ".join(
                        str(element.text or "").strip()
                        for element in root.iter()
                        if element.tag.rsplit("}", 1)[-1] == "t" and str(element.text or "").strip()
                    )
                    if text:
                        paragraphs.append(text)
                return "\n".join(paragraphs)[:200_000]
    except (OSError, ValueError, zipfile.BadZipFile, ElementTree.ParseError):
        return ""
    except Exception:  # noqa: BLE001
        # PDF parsers may surface format-specific exceptions. Migration must
        # retain the validated binary even when text extraction is unavailable.
        return ""
    return ""


def _safe_legacy_file_name(value: str) -> str:
    leaf_name = value.replace("\\", "/").rsplit("/", 1)[-1]
    normalized = unicodedata.normalize("NFC", leaf_name.strip())
    normalized = re.sub(r"[^\w.\- ]+", "-", normalized, flags=re.UNICODE)
    return normalized[:240].rstrip(" .") or "legacy-file"


def _available_legacy_id(requested: str, taken: set[str]) -> str:
    base = requested[:160]
    if base not in taken:
        return base
    counter = 2
    while True:
        suffix = f"~{counter}"
        candidate = f"{base[: 160 - len(suffix)]}{suffix}"
        if candidate not in taken:
            return candidate
        counter += 1


def _scrub_inline_file_values(value: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    def scrub(candidate: Any) -> tuple[Any, bool]:
        if isinstance(candidate, Mapping):
            changed = False
            sanitized: dict[str, Any] = {}
            for key, nested in candidate.items():
                normalized_key = re.sub(r"[_-]+", "", str(key)).casefold()
                if normalized_key in INLINE_FILE_FIELD_NAMES:
                    changed = True
                    continue
                sanitized_value, nested_changed = scrub(nested)
                sanitized[str(key)] = sanitized_value
                changed = changed or nested_changed
            return sanitized, changed
        if isinstance(candidate, list):
            changed = False
            sanitized_items: list[Any] = []
            for item in candidate:
                sanitized_item, item_changed = scrub(item)
                sanitized_items.append(sanitized_item)
                changed = changed or item_changed
            return sanitized_items, changed
        if isinstance(candidate, str):
            normalized = candidate.strip().casefold()
            if normalized.startswith("data:") or SERIALIZED_DATA_URL_PATTERN.search(candidate):
                return "", True
        return candidate, False

    sanitized, changed = scrub(value)
    return dict(sanitized), changed


def _legacy_signature_matches(content_type: str, content: bytes) -> bool:
    if content_type == "application/pdf":
        return content.startswith(b"%PDF-")
    if content_type == DOCX_CONTENT_TYPE:
        return content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
    if content_type == "application/msword":
        return content.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    if content_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    if content_type == "image/gif":
        return content.startswith((b"GIF87a", b"GIF89a"))
    return False


def _json_object_with_status(value: object) -> tuple[dict[str, Any], bool]:
    candidate = value
    for _ in range(3):
        if isinstance(candidate, Mapping):
            return dict(candidate), True
        if isinstance(candidate, (bytes, bytearray, memoryview)):
            try:
                candidate = bytes(candidate).decode("utf-8")
            except UnicodeDecodeError:
                return {}, False
            continue
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except (TypeError, ValueError):
                return {}, False
            continue
        return {}, False
    return (dict(candidate), True) if isinstance(candidate, Mapping) else ({}, False)


def _json_list(value: object) -> list[object]:
    candidate = value
    for _ in range(3):
        if isinstance(candidate, list):
            return candidate
        if isinstance(candidate, (bytes, bytearray, memoryview)):
            try:
                candidate = bytes(candidate).decode("utf-8")
            except UnicodeDecodeError:
                return []
            continue
        if isinstance(candidate, str):
            try:
                candidate = json.loads(candidate)
            except (TypeError, ValueError):
                return []
            continue
        return []
    return candidate if isinstance(candidate, list) else []


def _update_json_data(
    connection: sa.Connection,
    table_name: str,
    record_id: object,
    data: dict[str, Any],
) -> None:
    statement = sa.text(f"UPDATE {table_name} SET data = :data WHERE id = :id").bindparams(
        sa.bindparam("data", type_=sa.JSON())
    )
    connection.execute(statement, {"id": record_id, "data": data})


def _limited_text(
    value: object,
    limit: int,
    default: str = "",
) -> str:
    if not isinstance(value, str):
        return default[:limit]
    normalized = value.strip()
    return (normalized or default)[:limit]


def _optional_limited_text(value: object, limit: int) -> str | None:
    normalized = _limited_text(value, limit)
    return normalized or None


def _legacy_datetime(value: object, default: datetime) -> datetime:
    if not isinstance(value, str) or not value.strip():
        return default
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return default
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _first_value(value: Mapping[object, object], *keys: str) -> object:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _binary_value(value: object) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    return b""


def _fallback_file_name(stem: str, content_type: str) -> str:
    extension_by_type = {
        "application/pdf": ".pdf",
        "application/msword": ".doc",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
        "image/gif": ".gif",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    return f"{stem}{extension_by_type.get(content_type, '')}"[:240]
