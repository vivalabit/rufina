import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy.orm import Session

from app.core.identity import get_bound_owner_id
from app.models.documents import DocumentTemplateRecord


TEMPLATE_DIRECTORY = (
    Path(__file__).resolve().parent.parent
    / "templates"
    / "cover_letter"
    / "standard"
)
TEMPLATE_MANIFEST_PATH = TEMPLATE_DIRECTORY / "manifest.json"
TEMPLATE_DOCUMENT_PATH = TEMPLATE_DIRECTORY / "standard-cover-letter.docx"
BUNDLED_COVER_LETTER_TEMPLATE_KEY = "standard_cover_letter"


def bundled_cover_letter_template_id(owner_id: str | None = None) -> str:
    owner = owner_id or get_bound_owner_id()
    return str(
        uuid5(
            NAMESPACE_URL,
            f"rufina:cover-letter-template:{BUNDLED_COVER_LETTER_TEMPLATE_KEY}:{owner}",
        )
    )


def is_bundled_cover_letter_template_id(
    template_id: str,
    *,
    owner_id: str | None = None,
) -> bool:
    return template_id == bundled_cover_letter_template_id(owner_id)


def ensure_bundled_cover_letter_template(
    db: Session,
) -> DocumentTemplateRecord:
    manifest = json.loads(TEMPLATE_MANIFEST_PATH.read_text(encoding="utf-8"))
    content = TEMPLATE_DOCUMENT_PATH.read_bytes()
    content_sha256 = hashlib.sha256(content).hexdigest()
    template_id = bundled_cover_letter_template_id()
    record = db.get(DocumentTemplateRecord, template_id)
    now = datetime.now(UTC)
    if record is None:
        record = DocumentTemplateRecord(
            id=template_id,
            owner_id=get_bound_owner_id(),
            type="cover_letter",
            name=str(manifest["name"]),
            file_name=str(manifest["fileName"]),
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            content_sha256=content_sha256,
            content=content,
            extracted_text="",
            created_at=now,
            updated_at=now,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        return record

    if (
        record.content_sha256 != content_sha256
        or record.content != content
        or record.name != manifest["name"]
        or record.file_name != manifest["fileName"]
    ):
        record.name = str(manifest["name"])
        record.file_name = str(manifest["fileName"])
        record.content_sha256 = content_sha256
        record.content = content
        record.updated_at = now
        db.commit()
        db.refresh(record)
    return record


__all__ = [
    "BUNDLED_COVER_LETTER_TEMPLATE_KEY",
    "bundled_cover_letter_template_id",
    "ensure_bundled_cover_letter_template",
    "is_bundled_cover_letter_template_id",
]
