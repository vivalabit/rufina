from collections.abc import Generator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.documents import (
    DocumentFileRecord,
    DocumentRecord,
    DocumentVersionRecord,
)


OWNER_A = {"X-Rufina-Owner-Id": "owner-a"}
OWNER_B = {"X-Rufina-Owner-Id": "owner-b"}


@pytest.fixture
def api_sessions() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield sessions
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.fixture
def client(api_sessions: sessionmaker[Session]) -> TestClient:
    del api_sessions
    return TestClient(app)


def template_request(name: str = "Zurich backend") -> dict[str, object]:
    return {
        "name": name,
        "baseTemplateId": "modern_two_column",
        "designJson": {
            "accentColor": "#176B87",
            "fontFamily": "Inter",
            "fontScale": 1.0,
            "density": "compact",
            "pageMargins": {
                "top": 12,
                "right": 12,
                "bottom": 12,
                "left": 12,
            },
            "headingStyle": "accent-rule",
            "skillsStyle": "pills",
            "sidebarWidth": 32,
            "sidebarSections": ["skills", "languages"],
        },
    }


def create_custom_template(
    client: TestClient,
    *,
    headers: dict[str, str] = OWNER_A,
    name: str = "Zurich backend",
) -> dict[str, object]:
    response = client.post(
        "/resume-templates",
        headers=headers,
        json=template_request(name),
    )
    assert response.status_code == 201
    return response.json()


def test_lists_bundled_and_owner_custom_templates_through_both_routes(
    client: TestClient,
) -> None:
    custom = create_custom_template(client)

    primary = client.get("/resume-templates", headers=OWNER_A)
    alias = client.get("/documents/resume-templates", headers=OWNER_A)
    other_owner = client.get("/resume-templates", headers=OWNER_B)

    assert primary.status_code == 200
    assert alias.status_code == 200
    assert alias.json() == primary.json()
    assert [item["kind"] for item in primary.json()] == [
        "bundled",
        "bundled",
        "bundled",
        "custom",
    ]
    assert primary.json()[-1]["id"] == custom["id"]
    assert all(item["kind"] == "bundled" for item in other_owner.json())
    assert all("ownerId" not in item for item in primary.json())
    assert all("path" not in key.lower() for item in primary.json() for key in item)


def test_custom_template_crud_is_owner_scoped(client: TestClient) -> None:
    created = create_custom_template(client)
    template_id = created["id"]
    original_hash = created["contentSha256"]

    own_detail = client.get(f"/resume-templates/{template_id}", headers=OWNER_A)
    foreign_detail = client.get(f"/resume-templates/{template_id}", headers=OWNER_B)
    foreign_update = client.patch(
        f"/resume-templates/{template_id}",
        headers=OWNER_B,
        json={"name": "Stolen"},
    )
    updated = client.patch(
        f"/resume-templates/{template_id}",
        headers=OWNER_A,
        json={"name": "Senior backend"},
    )

    assert own_detail.status_code == 200
    assert foreign_detail.status_code == 404
    assert foreign_update.status_code == 404
    assert updated.status_code == 200
    assert updated.json()["name"] == "Senior backend"
    assert updated.json()["version"] == 2
    assert updated.json()["contentSha256"] == original_hash

    foreign_delete = client.delete(
        f"/resume-templates/{template_id}",
        headers=OWNER_B,
    )
    deleted = client.delete(
        f"/resume-templates/{template_id}",
        headers=OWNER_A,
    )
    missing = client.get(f"/resume-templates/{template_id}", headers=OWNER_A)

    assert foreign_delete.status_code == 404
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_bundled_templates_are_read_only_but_can_be_duplicated(
    client: TestClient,
) -> None:
    detail = client.get("/resume-templates/modern_single", headers=OWNER_A)
    updated = client.patch(
        "/resume-templates/modern_single",
        headers=OWNER_A,
        json={"name": "Changed"},
    )
    deleted = client.delete(
        "/resume-templates/modern_single",
        headers=OWNER_A,
    )
    duplicated = client.post(
        "/resume-templates/modern_single/duplicate",
        headers=OWNER_A,
    )

    assert detail.status_code == 200
    assert detail.json()["kind"] == "bundled"
    assert updated.status_code == 405
    assert deleted.status_code == 405
    assert duplicated.status_code == 201
    assert duplicated.json()["kind"] == "custom"
    assert duplicated.json()["baseTemplateId"] == "modern_single"
    assert duplicated.json()["name"] == "Modern copy"


def test_custom_template_duplicate_requires_ownership(client: TestClient) -> None:
    created = create_custom_template(client)
    template_id = created["id"]

    foreign = client.post(
        f"/resume-templates/{template_id}/duplicate",
        headers=OWNER_B,
        json={"name": "Foreign copy"},
    )
    duplicated = client.post(
        f"/resume-templates/{template_id}/duplicate",
        headers=OWNER_A,
        json={"name": "Application copy"},
    )

    assert foreign.status_code == 404
    assert duplicated.status_code == 201
    assert duplicated.json()["name"] == "Application copy"
    assert duplicated.json()["version"] == 1
    assert duplicated.json()["contentSha256"] == created["contentSha256"]


def test_delete_is_blocked_after_template_was_used_for_pdf(
    client: TestClient,
    api_sessions: sessionmaker[Session],
) -> None:
    created = create_custom_template(client)
    template_id = str(created["id"])
    now = datetime.now(UTC)
    document = DocumentRecord(
        id="custom-template-document",
        owner_id="owner-a",
        type="tailored_resume",
        title="Rendered resume",
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    document.versions.append(
        DocumentVersionRecord(
            id="custom-template-version",
            document_id=document.id,
            version=1,
            content="{}",
            created_at=now,
        )
    )
    document.files.append(
        DocumentFileRecord(
            id="custom-template-pdf",
            document_id=document.id,
            version=1,
            file_name="resume.pdf",
            content_type="application/pdf",
            renderer_template_id=template_id,
            renderer_template_version="1",
            content=b"%PDF-1.4",
            created_at=now,
        )
    )
    with api_sessions() as db:
        db.add(document)
        db.commit()

    response = client.delete(
        f"/resume-templates/{template_id}",
        headers=OWNER_A,
    )

    assert response.status_code == 409
    assert "used to render a PDF" in response.json()["detail"]
    assert (
        client.get(f"/resume-templates/{template_id}", headers=OWNER_A).status_code
        == 200
    )


def test_create_rejects_unknown_design_fields_and_empty_patch(
    client: TestClient,
) -> None:
    invalid_request = template_request()
    design = dict(invalid_request["designJson"])
    design["filesystemPath"] = "/tmp/private-template"
    invalid_request["designJson"] = design

    invalid = client.post(
        "/resume-templates",
        headers=OWNER_A,
        json=invalid_request,
    )
    created = create_custom_template(client)
    empty_patch = client.patch(
        f"/resume-templates/{created['id']}",
        headers=OWNER_A,
        json={},
    )

    assert invalid.status_code == 422
    assert empty_patch.status_code == 422
