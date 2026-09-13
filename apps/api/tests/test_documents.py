import base64
import hashlib
import json
from collections.abc import Generator
from datetime import UTC, datetime
from io import BytesIO

from docx import Document
from docx.oxml import OxmlElement
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import documents as documents_api
from app.core.database import Base, get_db
from app.main import app
from app.models.applications import StoredApplicationRecord
from app.models.documents import (
    DocumentAttachmentRecord,
    DocumentFileRecord,
    DocumentRecord,
    DocumentTemplateRecord,
    DocumentVersionRecord,
)


def test_resume_template_preflight_rejects_custom_docx_without_saving() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    supported_document = Document()
    supported_document.add_paragraph("PROFILE", style="Heading 1")
    supported_body = supported_document.add_paragraph(
        "Product designer building reliable B2B workflows with research evidence."
    )
    supported_body.add_run()._r.append(OxmlElement("w:drawing"))
    supported_output = BytesIO()
    supported_document.save(supported_output)
    supported_data_url = (
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
        "base64," + base64.b64encode(supported_output.getvalue()).decode()
    )

    unsupported_document = Document()
    unsupported_paragraph = unsupported_document.add_paragraph("Unsupported source")
    unsupported_paragraph.add_run()._r.append(OxmlElement("w:object"))
    unsupported_output = BytesIO()
    unsupported_document.save(unsupported_output)
    unsupported_data_url = (
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;"
        "base64," + base64.b64encode(unsupported_output.getvalue()).decode()
    )

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        supported = client.post(
            "/documents/templates/preflight",
            json={
                "type": "tailored_resume",
                "name": "Supported CV",
                "fileName": "resume.docx",
                "dataUrl": supported_data_url,
                "promptCharacters": 2200,
            },
        )
        rejected = client.post(
            "/documents/templates/preflight",
            json={
                "type": "tailored_resume",
                "name": "Unsupported CV",
                "fileName": "unsupported.docx",
                "dataUrl": unsupported_data_url,
            },
        )
        with testing_session_local() as db:
            template_count = db.scalar(select(func.count()).select_from(DocumentTemplateRecord))
    finally:
        app.dependency_overrides.clear()

    assert supported.status_code == 422
    assert rejected.status_code == 422
    assert "Custom resume DOCX templates are not supported" in (supported.json()["detail"])
    assert template_count == 0


def test_workspace_sources_reject_resume_uploads_but_keep_cover_letters() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    with testing_session_local() as db:
        db.add_all(
            [
                StoredApplicationRecord(
                    id="application-sources",
                    data={"id": "application-sources", "status": "draft"},
                ),
                StoredApplicationRecord(
                    id="application-other",
                    data={"id": "application-other", "status": "draft"},
                ),
            ]
        )
        db.commit()

    document = Document()
    document.add_paragraph("Professional profile")
    output = BytesIO()
    document.save(output)
    original_content = output.getvalue()
    replacement_document = Document()
    replacement_document.add_paragraph("Updated professional profile")
    replacement_output = BytesIO()
    replacement_document.save(replacement_output)
    replacement_content = replacement_output.getvalue()
    docx_content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        resume_rejected = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-sources",
                "category": "CV / Resume",
                "title": "Target CV",
                "language": "English",
                "fileName": "Résumé-Едуард.docx",
            },
            content=original_content,
            headers={"Content-Type": docx_content_type},
        )
        created = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-sources",
                "category": "Cover Letter",
                "title": "Source cover letter",
                "language": "English",
                "fileName": "Cover-Letter.docx",
            },
            content=original_content,
            headers={"Content-Type": docx_content_type},
        )
        listed = client.get(
            "/documents/workspace-sources/library",
            params={"applicationId": "application-sources"},
        )
        other_workspace = client.get(
            "/documents/workspace-sources/library",
            params={"applicationId": "application-other"},
        )
        source_id = created.json()["id"]
        replacement_params = {
            "applicationId": "application-sources",
            "category": "Cover Letter",
            "title": "Updated source cover letter",
            "language": "German",
            "fileName": "Updated-Cover-Letter.docx",
        }
        wrong_workspace_replace = client.put(
            f"/documents/workspace-sources/{source_id}",
            params={**replacement_params, "applicationId": "application-other"},
            content=replacement_content,
            headers={"Content-Type": docx_content_type},
        )
        wrong_owner_replace = client.put(
            f"/documents/workspace-sources/{source_id}",
            params=replacement_params,
            content=replacement_content,
            headers={
                "Content-Type": docx_content_type,
                "X-Rufina-Owner-Id": "another-owner",
            },
        )
        replaced = client.put(
            f"/documents/workspace-sources/{source_id}",
            params=replacement_params,
            content=replacement_content,
            headers={"Content-Type": docx_content_type},
        )
        downloaded = client.get(replaced.json()["downloadUrl"])
        previewed = client.get(f"{replaced.json()['downloadUrl']}&preview=true")
        wrong_workspace_download = client.get(
            f"/documents/workspace-sources/{source_id}/download",
            params={"applicationId": "application-other"},
        )
        wrong_owner_download = client.get(
            created.json()["downloadUrl"],
            headers={"X-Rufina-Owner-Id": "another-owner"},
        )
        wrong_owner_delete = client.delete(
            f"/documents/workspace-sources/{source_id}",
            params={"applicationId": "application-sources"},
            headers={"X-Rufina-Owner-Id": "another-owner"},
        )
        wrong_workspace_delete = client.delete(
            f"/documents/workspace-sources/{source_id}",
            params={"applicationId": "application-other"},
        )
        deleted = client.delete(
            f"/documents/workspace-sources/{source_id}",
            params={"applicationId": "application-sources"},
        )
        listed_after_delete = client.get(
            "/documents/workspace-sources/library",
            params={"applicationId": "application-sources"},
        )
    finally:
        app.dependency_overrides.clear()

    assert resume_rejected.status_code == 410
    assert "Master Resume" in resume_rejected.json()["detail"]
    assert created.status_code == 201
    assert created.json()["fileName"] == "Cover-Letter.docx"
    assert created.json()["category"] == "Cover Letter"
    assert created.json()["sizeBytes"] == len(original_content)
    assert created.json()["contentSha256"] == hashlib.sha256(original_content).hexdigest()
    assert "dataUrl" not in created.json()
    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert listed.headers["vary"] == "X-Rufina-Owner-Id, X-Tasko-Owner-Id"
    assert [source["id"] for source in listed.json()] == [source_id]
    assert "dataUrl" not in listed.json()[0]
    assert downloaded.status_code == 200
    assert replaced.status_code == 200
    assert replaced.json()["id"] == source_id
    assert replaced.json()["title"] == "Updated source cover letter"
    assert replaced.json()["language"] == "German"
    assert replaced.json()["fileName"] == "Updated-Cover-Letter.docx"
    assert replaced.json()["contentSha256"] == hashlib.sha256(replacement_content).hexdigest()
    assert wrong_workspace_replace.status_code == 404
    assert wrong_owner_replace.status_code == 404
    assert downloaded.content == replacement_content
    assert downloaded.headers["content-type"] == docx_content_type
    assert downloaded.headers["content-length"] == str(len(replacement_content))
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert previewed.status_code == 200
    assert previewed.content == replacement_content
    assert previewed.headers["content-disposition"].startswith("inline;")
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["cross-origin-resource-policy"] == "same-site"
    assert wrong_workspace_download.status_code == 404
    assert wrong_owner_download.status_code == 404
    assert wrong_owner_delete.status_code == 404
    assert other_workspace.json() == []
    assert wrong_workspace_delete.status_code == 404
    assert deleted.status_code == 204
    assert listed_after_delete.json() == []


def test_application_attachments_validate_type_and_size() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    with testing_session_local() as db:
        db.add(
            StoredApplicationRecord(
                id="application-attachments",
                data={"id": "application-attachments", "status": "draft"},
            )
        )
        db.commit()

    docx_content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    document = Document()
    document.add_paragraph("Supporting document")
    docx_output = BytesIO()
    document.save(docx_output)
    supported_files = [
        ("application/pdf", "details.pdf", b"%PDF-1.7 attachment"),
        (
            "application/msword",
            "details.doc",
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1legacy-doc-attachment",
        ),
        (docx_content_type, "details.docx", docx_output.getvalue()),
        ("image/png", "details.png", b"\x89PNG\r\n\x1a\npng-attachment"),
        ("image/jpeg", "details.jpeg", b"\xff\xd8\xffjpeg-attachment"),
        ("image/webp", "details.webp", b"RIFF\x00\x00\x00\x00WEBPwebp-attachment"),
    ]

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        for index, (content_type, file_name, content) in enumerate(supported_files):
            response = client.post(
                "/documents/workspace-sources/upload",
                params={
                    "applicationId": "application-attachments",
                    "category": "Application Attachment",
                    "title": f"Attachment {index}",
                    "fileName": file_name,
                },
                content=content,
                headers={"Content-Type": content_type},
            )
            assert response.status_code == 201
            assert response.json()["fileType"] == content_type
            assert response.json()["sizeBytes"] == len(content)

        mismatched_type = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-attachments",
                "category": "Application Attachment",
                "title": "Mismatched",
                "fileName": "image.png",
            },
            content=b"mismatched",
            headers={"Content-Type": "application/pdf"},
        )
        unsupported_type = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-attachments",
                "category": "Application Attachment",
                "title": "Unsupported",
                "fileName": "notes.txt",
            },
            content=b"unsupported",
            headers={"Content-Type": "application/octet-stream"},
        )
        invalid_signature = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-attachments",
                "category": "Application Attachment",
                "title": "Disguised executable",
                "fileName": "disguised.pdf",
            },
            content=b"not-a-pdf",
            headers={"Content-Type": "application/pdf"},
        )
        invalid_cover_letter = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-attachments",
                "category": "Cover Letter",
                "title": "Invalid cover letter",
                "fileName": "invalid.docx",
            },
            content=b"not-a-validated-docx",
            headers={"Content-Type": docx_content_type},
        )
        oversized = client.post(
            "/documents/workspace-sources/upload",
            params={
                "applicationId": "application-attachments",
                "category": "Application Attachment",
                "title": "Oversized",
                "fileName": "oversized.pdf",
            },
            content=b"x" * 5_000_001,
            headers={"Content-Type": "application/pdf"},
        )
        listed = client.get(
            "/documents/workspace-sources/library",
            params={"applicationId": "application-attachments"},
        )
    finally:
        app.dependency_overrides.clear()

    assert mismatched_type.status_code == 422
    assert unsupported_type.status_code == 422
    assert invalid_signature.status_code == 422
    assert invalid_cover_letter.status_code == 422
    assert oversized.status_code == 413
    assert listed.status_code == 200
    assert len(listed.json()) == len(supported_files)
    assert all("dataUrl" not in attachment for attachment in listed.json())


def test_document_versions_download_and_application_attachments() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    with testing_session_local() as db:
        db.add(
            StoredApplicationRecord(
                id="application-one",
                data={"id": "application-one", "status": "applied"},
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        created = client.post(
            "/documents",
            json={
                "type": "cover_letter",
                "title": "Figma cover letter",
                "content": "Dear Hiring Team,\n\nI am applying for the role.",
                "jobId": "job-figma",
                "applicationId": "application-one",
            },
        )
        document_id = created.json()["id"]
        updated = client.patch(
            f"/documents/{document_id}",
            json={
                "content": json.dumps({"replacements": []}),
            },
        )
        restored = client.post(
            f"/documents/{document_id}/restore",
            json={"version": 1},
        )
        listed = client.get("/documents?jobId=job-figma")
        downloaded = client.get(f"/documents/{document_id}/download?version=2")
        detached = client.delete(f"/documents/{document_id}/attachments/application-one")
        deleted = client.delete(f"/documents/{document_id}")

        with testing_session_local() as db:
            version_count = db.scalar(select(func.count()).select_from(DocumentVersionRecord))
            attachment_count = db.scalar(select(func.count()).select_from(DocumentAttachmentRecord))
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 201
    assert created.json()["currentVersion"] == 1
    assert created.json()["applicationIds"] == ["application-one"]
    assert created.json()["versions"][0]["hasRenderedDocx"] is False
    assert updated.status_code == 200
    assert updated.json()["id"] == document_id
    assert updated.json()["currentVersion"] == 2
    assert len(updated.json()["versions"]) == 2
    assert updated.json()["applicationIds"] == ["application-one"]
    assert restored.status_code == 200
    assert restored.json()["id"] == document_id
    assert restored.json()["currentVersion"] == 3
    assert restored.json()["versions"][-1]["content"].startswith("Dear Hiring Team")
    assert restored.json()["applicationIds"] == ["application-one"]
    assert listed.status_code == 200
    assert listed.json()[0]["jobId"] == "job-figma"
    assert downloaded.status_code == 410
    assert downloaded.json()["detail"] == (
        "Rendered document artifact is no longer available for recovery"
    )
    assert detached.status_code == 204
    assert deleted.status_code == 204
    assert version_count == 0
    assert attachment_count == 0


def test_file_access_does_not_load_preparation_analysis(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    monkeypatch.setattr(
        documents_api,
        "render_docx_to_pdf",
        lambda _content: b"%PDF-1.7 independent preview",
    )

    now = datetime.now(UTC)
    document_id = "document-independent-access"
    template_id = "template-independent-access"
    with testing_session_local() as db:
        db.add_all(
            [
                StoredApplicationRecord(
                    id="application-file-access",
                    data={"id": "application-file-access", "status": "draft"},
                ),
                StoredApplicationRecord(
                    id="application-file-attachment",
                    data={"id": "application-file-attachment", "status": "draft"},
                ),
                DocumentTemplateRecord(
                    id=template_id,
                    type="cover_letter",
                    name="Historical template",
                    file_name="historical-template.docx",
                    content_type=(
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    ),
                    content_sha256="a" * 64,
                    content=b"historical template",
                    extracted_text="Historical template",
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        document = DocumentRecord(
            id=document_id,
            type="cover_letter",
            title="Historical cover letter",
            job_id="job-without-current-match",
            current_version=1,
            created_at=now,
            updated_at=now,
        )
        document.versions.append(
            DocumentVersionRecord(
                id="version-independent-access",
                document_id=document_id,
                version=1,
                content="Historical document content",
                created_at=now,
            )
        )
        document.files.append(
            DocumentFileRecord(
                id="file-independent-access",
                document_id=document_id,
                version=1,
                template_id=template_id,
                file_name="historical-cover-letter.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content=b"historical rendered file",
                created_at=now,
            )
        )
        document.attachments.append(
            DocumentAttachmentRecord(
                id="attachment-independent-access",
                document_id=document_id,
                application_id="application-file-access",
                created_at=now,
            )
        )
        db.add(document)
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        listed = client.get(
            "/documents",
            params={"applicationId": "application-file-access"},
        )
        detail = client.get(f"/documents/{document_id}")
        versions = client.get(f"/documents/{document_id}/versions")
        downloaded = client.get(f"/documents/{document_id}/download")
        previewed = client.get(f"/documents/{document_id}/pdf")
        attached = client.post(
            f"/documents/{document_id}/attachments",
            json={"applicationId": "application-file-attachment"},
        )
    finally:
        app.dependency_overrides.clear()

    assert listed.status_code == 200
    assert detail.status_code == 200
    assert versions.status_code == 200
    assert [item["version"] for item in versions.json()["items"]] == [1]
    assert downloaded.status_code == 200
    assert downloaded.content == b"historical rendered file"
    assert previewed.status_code == 200
    assert previewed.content == b"%PDF-1.7 independent preview"
    assert attached.status_code == 200
    assert attached.json()["applicationIds"] == [
        "application-file-access",
        "application-file-attachment",
    ]


def test_document_download_preserves_unicode_filename_for_rendered_docx() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    rendered_document = Document()
    rendered_document.add_paragraph("Rendered content")
    rendered_output = BytesIO()
    rendered_document.save(rendered_output)

    with testing_session_local() as db:
        record = DocumentRecord(
            id="unicode-document",
            type="tailored_resume",
            title="Résumé Едуард",
            current_version=1,
        )
        record.versions.append(
            DocumentVersionRecord(
                id="unicode-version",
                document_id=record.id,
                version=1,
                content=json.dumps({"replacements": []}),
            )
        )
        record.files.append(
            DocumentFileRecord(
                id="unicode-file",
                document_id=record.id,
                version=1,
                template_id=None,
                content=rendered_output.getvalue(),
            )
        )
        db.add(record)
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        downloaded = client.get("/documents/unicode-document/download")
    finally:
        app.dependency_overrides.clear()

    assert downloaded.status_code == 200
    assert downloaded.content == rendered_output.getvalue()
    assert downloaded.headers["content-disposition"] == (
        'attachment; filename="R-sum-v1.docx"; '
        "filename*=UTF-8''R%C3%A9sum%C3%A9-%D0%95%D0%B4%D1%83%D0%B0%D1%80%D0%B4-v1.docx"
    )


def test_cover_letter_pdf_download_converts_the_saved_docx(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    rendered_document = Document()
    rendered_document.add_paragraph("Rendered cover letter")
    rendered_output = BytesIO()
    rendered_document.save(rendered_output)
    rendered_content = rendered_output.getvalue()

    with testing_session_local() as db:
        record = DocumentRecord(
            id="cover-letter-pdf",
            type="cover_letter",
            title="Bewerbungsschreiben Zürich",
            current_version=1,
        )
        record.versions.append(
            DocumentVersionRecord(
                id="cover-letter-pdf-version",
                document_id=record.id,
                version=1,
                content=json.dumps({"replacements": []}),
            )
        )
        record.files.append(
            DocumentFileRecord(
                id="cover-letter-pdf-file",
                document_id=record.id,
                version=1,
                template_id="standard-cover-letter",
                file_name="Bewerbungsschreiben-Zürich.docx",
                content_type=(
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                ),
                content=rendered_content,
            )
        )
        db.add(record)
        db.commit()

    converted_content = b"%PDF-1.7\nconverted-cover-letter"

    def fake_render_docx_to_pdf(content: bytes) -> bytes:
        assert content == rendered_content
        return converted_content

    monkeypatch.setattr(
        "app.api.documents.render_docx_to_pdf",
        fake_render_docx_to_pdf,
    )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        downloaded = client.get("/documents/cover-letter-pdf/pdf")
    finally:
        app.dependency_overrides.clear()

    assert downloaded.status_code == 200
    assert downloaded.content == converted_content
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["content-disposition"] == (
        'attachment; filename="Bewerbungsschreiben-Z-rich.pdf"; '
        "filename*=UTF-8''Bewerbungsschreiben-Z%C3%BCrich.pdf"
    )


def test_pdf_artifact_is_downloadable_but_immutable() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with testing_session_local() as db:
        record = DocumentRecord(
            id="pdf-document",
            type="tailored_resume",
            title="Ada resume",
            current_version=1,
        )
        record.versions.append(
            DocumentVersionRecord(
                id="pdf-version",
                document_id=record.id,
                version=1,
                content='{"id":"final-resume"}',
            )
        )
        record.files.append(
            DocumentFileRecord(
                id="pdf-file",
                document_id=record.id,
                version=1,
                template_id=None,
                file_name="Ada-Lovelace-resume.pdf",
                content_type="application/pdf",
                renderer_template_id="modern_single",
                renderer_template_version="1.0.0",
                content=b"%PDF-1.7\nstored",
            )
        )
        db.add(record)
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        detail = client.get("/documents/pdf-document")
        downloaded = client.get("/documents/pdf-document/download")
        restored = client.post(
            "/documents/pdf-document/restore",
            json={"version": 1},
        )
        restored_download = client.get(
            "/documents/pdf-document/download",
            params={"version": 2},
        )
    finally:
        app.dependency_overrides.clear()

    artifact = detail.json()["versions"][0]["artifact"]
    assert detail.status_code == 200
    assert artifact["contentType"] == "application/pdf"
    assert artifact["templateId"] == "modern_single"
    assert artifact["templateVersion"] == "1.0.0"
    assert "finalResumeJson" not in artifact
    assert restored.status_code == 405
    assert "read-only" in restored.json()["detail"]
    assert restored_download.status_code == 404
    assert downloaded.content == b"%PDF-1.7\nstored"
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.headers["content-disposition"].startswith(
        'attachment; filename="Ada-Lovelace-resume.pdf"'
    )


def test_document_version_history_is_paginated_from_newest_to_oldest() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    now = datetime.now(UTC)
    with testing_session_local() as db:
        record = DocumentRecord(
            id="paginated-document",
            type="cover_letter",
            title="Long history",
            current_version=25,
            created_at=now,
            updated_at=now,
        )
        record.versions.extend(
            DocumentVersionRecord(
                id=f"paginated-version-{version}",
                document_id=record.id,
                version=version,
                content=f"Version {version}",
                created_at=now,
            )
            for version in range(1, 26)
        )
        db.add(record)
        db.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        document = client.get("/documents/paginated-document")
        older_page = client.get("/documents/paginated-document/versions?limit=20&offset=20")
    finally:
        app.dependency_overrides.clear()

    assert document.status_code == 200
    assert document.json()["versionsTotal"] == 25
    assert document.json()["versionsHasMore"] is True
    assert [version["version"] for version in document.json()["versions"]] == list(range(6, 26))
    assert older_page.status_code == 200
    assert older_page.json()["total"] == 25
    assert [version["version"] for version in older_page.json()["items"]] == list(range(1, 6))


def test_document_attachment_requires_existing_application() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        response = client.post(
            "/documents",
            json={
                "type": "tailored_resume",
                "title": "Resume for Stripe",
                "content": "# Experience\nVerified achievements",
                "applicationId": "missing-application",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 410
    assert response.json()["detail"] == "Tailored resume creation is not available"


def test_cover_letter_template_preserves_visual_structure() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    with testing_session_local() as db:
        db.add(
            StoredApplicationRecord(
                id="application-template",
                data={"id": "application-template", "status": "draft"},
            )
        )
        db.commit()

    template = Document()
    template.sections[0].header.paragraphs[0].text = "EDUARD · SOFTWARE ENGINEER"
    template.add_paragraph("Dear Hiring Team,")
    body = template.add_paragraph("Original reusable body paragraph.")
    body.style = template.styles["Normal"]
    template.add_paragraph("Kind regards,")
    template.add_paragraph("Eduard")
    template.sections[0].footer.paragraphs[0].text = "Private application"
    template_output = BytesIO()
    template.save(template_output)
    data_url = (
        "data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,"
        + base64.b64encode(template_output.getvalue()).decode()
    )

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        uploaded = client.post(
            "/documents/templates",
            json={
                "type": "cover_letter",
                "name": "My cover letter",
                "fileName": "cover-letter.docx",
                "dataUrl": data_url,
            },
        )
        template_id = uploaded.json()["id"]
        listed = client.get("/documents/templates/library")
        created = client.post(
            "/documents",
            json={
                "type": "cover_letter",
                "title": "Generated cover letter",
                "content": (
                    "Dear Acme Hiring Team,\n\n"
                    "My first tailored paragraph.\n\n"
                    "My second tailored paragraph.\n\n"
                    "Kind regards,\n\nEduard"
                ),
                "jobId": "job-acme",
                "applicationId": "application-template",
                "templateId": template_id,
            },
        )
        downloaded = client.get(f"/documents/{created.json()['id']}/download")
    finally:
        app.dependency_overrides.clear()

    rendered = Document(BytesIO(downloaded.content))
    body_text = "\n".join(paragraph.text for paragraph in rendered.paragraphs)
    header_text = rendered.sections[0].header.paragraphs[0].text
    footer_text = rendered.sections[0].footer.paragraphs[0].text

    assert uploaded.status_code == 201
    assert listed.status_code == 200
    assert listed.json()[0]["fileName"] == "standard-cover-letter.docx"
    assert listed.json()[0]["builtIn"] is True
    assert any(
        item["fileName"] == "cover-letter.docx" and item["builtIn"] is False
        for item in listed.json()
    )
    assert created.status_code == 201
    assert downloaded.status_code == 200
    assert header_text == "EDUARD · SOFTWARE ENGINEER"
    assert footer_text == "Private application"
    assert "My first tailored paragraph." in body_text
    assert "My second tailored paragraph." in body_text
    assert "Original reusable body paragraph." not in body_text


def test_legacy_resume_document_creation_is_gone() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session_local() as db:
            yield db

    with testing_session_local() as db:
        db.add(
            StoredApplicationRecord(
                id="application-resume-template",
                data={"id": "application-resume-template", "status": "draft"},
            )
        )
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        created = client.post(
            "/documents",
            json={
                "type": "tailored_resume",
                "title": "Tailored resume",
                "content": json.dumps(
                    {
                        "replacements": [
                            {
                                "blockId": "block-0004",
                                "spanId": "block-0004-span-0001",
                                "original": "Evidence-backed professional summary.",
                                "replacement": "Backend engineer focused on FastAPI",
                                "reason": "Matches the target role with verified profile evidence",
                                "evidenceIds": ["source:block-0004-span-0001"],
                            }
                        ]
                    }
                ),
                "applicationId": "application-resume-template",
                "templateId": "classic_single",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert created.status_code == 410
    assert created.json()["detail"] == "Tailored resume creation is not available"
