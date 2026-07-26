from collections.abc import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.documents import DocumentTemplateRecord
from app.services.resume_template_registry import (
    get_bundled_resume_template,
    is_bundled_resume_template_id,
    list_bundled_resume_templates,
)


def test_registry_contains_all_bundled_resume_templates() -> None:
    templates = list_bundled_resume_templates()

    assert [template.id for template in templates] == [
        "classic_single",
        "modern_single",
        "modern_two_column",
        "swiss_classic",
    ]
    assert [template.columns for template in templates] == [1, 1, 2, 1]
    assert len({template.id for template in templates}) == 4


def test_registry_is_metadata_only() -> None:
    template = get_bundled_resume_template("modern_two_column")

    assert template.layout == "two_column"
    assert template.columns == 2
    assert is_bundled_resume_template_id(template.id) is True
    assert is_bundled_resume_template_id("user-upload") is False


def test_resume_template_api_lists_registry_and_rejects_custom_uploads() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
    )

    def override_get_db() -> Generator[Session, None, None]:
        with testing_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        listed = client.get("/documents/resume-templates")
        uploaded = client.post(
            "/documents/templates",
            json={
                "type": "tailored_resume",
                "name": "User resume",
                "fileName": "user-resume.docx",
                "dataUrl": "data:application/octet-stream;base64,UEs=",
            },
        )

        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [
            "classic_single",
            "modern_single",
            "modern_two_column",
            "swiss_classic",
        ]
        assert uploaded.status_code == 422
        assert "Custom resume DOCX templates are not supported" in (
            uploaded.json()["detail"]
        )
        with testing_session() as db:
            assert db.scalar(
                select(func.count()).select_from(DocumentTemplateRecord)
            ) == 0
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
