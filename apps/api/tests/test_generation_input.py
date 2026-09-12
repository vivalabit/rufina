import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, update
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.identity import current_owner_id
from app.models.applications import StoredApplicationRecord
from app.models.jobs import StoredJobRecord
from app.models.resume import ResumeMasterRecord, ResumeMasterVersionRecord
from app.services.generation_input import GenerationInputError, build_generation_input


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def master_profile_data(profile_id: str, *, headline: str) -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": profile_id,
        "language": "English",
        "basics": {
            "fullName": "Ada Lovelace",
            "headline": headline,
        },
        "summary": None,
        "experiences": [],
        "skills": [],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [],
        "sectionOrder": [],
    }


def content_sha256(data: dict[str, object]) -> str:
    payload = json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def seed_complete_sources(sessions: sessionmaker[Session]) -> None:
    now = datetime.now(UTC)
    version_one_data = master_profile_data("master-profile", headline="Engineer")
    version_two_data = master_profile_data("master-profile", headline="Platform Engineer")
    master = ResumeMasterRecord(
        id="master-profile",
        name="Ada Lovelace",
        language="English",
        current_version=2,
        created_at=now - timedelta(days=1),
        updated_at=now,
    )
    master.versions.extend(
        [
            ResumeMasterVersionRecord(
                id="master-profile-version-1",
                resume_master_id=master.id,
                version=1,
                schema_version="1.0",
                data=version_one_data,
                content_sha256=content_sha256(version_one_data),
                created_at=now - timedelta(days=1),
            ),
            ResumeMasterVersionRecord(
                id="master-profile-version-2",
                resume_master_id=master.id,
                version=2,
                schema_version="1.0",
                data=version_two_data,
                content_sha256=content_sha256(version_two_data),
                created_at=now,
            ),
        ]
    )
    with sessions() as db:
        db.add_all(
            [
                StoredApplicationRecord(
                    id="application-1",
                    revision=4,
                    data={
                        "id": "application-1",
                        "status": "draft",
                        "notes": "Focus on reliability.",
                        "applicationGuide": {"steps": ["legacy questionnaire"]},
                        "job": {
                            "id": "vacancy-1",
                            "match": 98,
                            "aiMatch": {"score": 98, "reasons": ["legacy"]},
                        },
                    },
                ),
                StoredJobRecord(
                    id="vacancy-1",
                    revision=7,
                    data={
                        "id": "client-controlled-id",
                        "title": "Platform Engineer",
                        "company": "Example AG",
                        "overview": "Build reliable internal platforms.",
                        "responsibilities": ["Own deployment tooling", "Improve observability"],
                        "requirements": ["Python", "Kubernetes"],
                        "skills": ["Python", "Kubernetes"],
                        "match": 98,
                        "recommendations": [{"action": "Complete an old questionnaire"}],
                    },
                ),
                master,
            ]
        )
        db.commit()
        db.execute(
            update(StoredApplicationRecord)
            .where(StoredApplicationRecord.id == "application-1")
            .values(revision=4)
        )
        db.execute(
            update(StoredJobRecord).where(StoredJobRecord.id == "vacancy-1").values(revision=7)
        )
        db.commit()


def build_input(db: Session, **overrides: object):
    arguments = {
        "application_id": "application-1",
        "document_types": ("tailored_resume", "cover_letter"),
        "language": "de-CH",
        "formatting_parameters": {"tailored_resume": {"maxPages": 2}},
        "user_preferences": "Use a concise, formal style.",
        **overrides,
    }
    return build_generation_input(db, **arguments)


def test_builds_versioned_input_without_match_or_questionnaire_dependencies(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)

    with sessions() as db:
        request = build_input(db)

    assert request.application.id == "application-1"
    assert request.application.revision == 4
    assert request.vacancy.id == "vacancy-1"
    assert request.vacancy.revision == 7
    assert request.master_profile_version.id == "master-profile"
    assert request.master_profile_version.version == 2
    assert request.master_profile_version.content_sha256 == content_sha256(
        master_profile_data("master-profile", headline="Platform Engineer")
    )
    assert request.master_profile_version.data["basics"]["headline"] == "Platform Engineer"
    assert request.vacancy.data["id"] == "vacancy-1"
    assert request.vacancy.full_description == (
        "Overview\nBuild reliable internal platforms.\n\n"
        "Responsibilities\n- Own deployment tooling\n- Improve observability\n\n"
        "Requirements\n- Python\n- Kubernetes\n\n"
        "Skills\n- Python\n- Kubernetes"
    )

    payload = request.model_dump(mode="json", by_alias=True)
    serialized = json.dumps(payload)
    assert "aiMatch" not in serialized
    assert '"match"' not in serialized
    assert "recommendations" not in serialized
    assert "applicationGuide" not in serialized


def test_can_pin_an_older_master_profile_version(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)

    with sessions() as db:
        request = build_input(
            db,
            master_profile_id="master-profile",
            master_profile_version=1,
        )

    assert request.master_profile_version.version == 1
    assert request.master_profile_version.data["basics"]["headline"] == "Engineer"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("remove_application", "application_not_found"),
        ("unlink_vacancy", "application_vacancy_missing"),
        ("remove_vacancy", "vacancy_not_found"),
        ("remove_description", "vacancy_description_missing"),
        ("remove_master_profile", "master_profile_not_found"),
        ("remove_master_version", "master_profile_version_not_found"),
        ("corrupt_master_version", "master_profile_integrity_error"),
        ("invalidate_master_version", "master_profile_invalid"),
    ],
)
def test_rejects_missing_or_inconsistent_authoritative_sources(
    sessions: sessionmaker[Session],
    mutation: str,
    code: str,
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        application = db.get(StoredApplicationRecord, "application-1")
        vacancy = db.get(StoredJobRecord, ("local-owner", "vacancy-1"))
        master = db.get(ResumeMasterRecord, "master-profile")
        version = db.get(ResumeMasterVersionRecord, "master-profile-version-2")
        assert application is not None
        assert vacancy is not None
        assert master is not None
        assert version is not None

        if mutation == "remove_application":
            db.delete(application)
        elif mutation == "unlink_vacancy":
            application.data = {"id": application.id, "status": "draft"}
        elif mutation == "remove_vacancy":
            db.delete(vacancy)
        elif mutation == "remove_description":
            vacancy.data = {
                "id": vacancy.id,
                "title": "Platform Engineer",
                "company": "Example AG",
            }
        elif mutation == "remove_master_profile":
            db.delete(master)
        elif mutation == "remove_master_version":
            db.delete(version)
        elif mutation == "corrupt_master_version":
            db.execute(
                update(ResumeMasterVersionRecord)
                .where(ResumeMasterVersionRecord.id == version.id)
                .values(content_sha256="f" * 64)
            )
        else:
            invalid_data = {"schemaVersion": "1.0", "id": "master-profile"}
            db.execute(
                update(ResumeMasterVersionRecord)
                .where(ResumeMasterVersionRecord.id == version.id)
                .values(
                    data=invalid_data,
                    content_sha256=content_sha256(invalid_data),
                )
            )
        db.commit()

        with pytest.raises(GenerationInputError) as failure:
            build_input(db)

    assert failure.value.code == code


def test_rejects_a_vacancy_without_identity_fields(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        vacancy = db.get(StoredJobRecord, ("local-owner", "vacancy-1"))
        assert vacancy is not None
        vacancy.data = {
            "id": vacancy.id,
            "company": "Example AG",
            "overview": "Build platforms.",
        }
        db.commit()

        with pytest.raises(GenerationInputError) as failure:
            build_input(db)

    assert failure.value.code == "vacancy_data_incomplete"
    assert str(failure.value) == "Vacancy is missing required data: title."


def test_rejects_an_import_placeholder_instead_of_a_full_description(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        vacancy = db.get(StoredJobRecord, ("local-owner", "vacancy-1"))
        assert vacancy is not None
        vacancy.data = {
            **vacancy.data,
            "overview": (
                "Imported from jobs.ch. Open the source vacancy to review "
                "the full description and apply details."
            ),
        }
        db.commit()

        with pytest.raises(GenerationInputError) as failure:
            build_input(db)

    assert failure.value.code == "vacancy_description_missing"
    assert str(failure.value) == (
        "Vacancy has no full description; refresh it from the source or add one manually."
    )


def test_source_lookup_is_owner_scoped(sessions: sessionmaker[Session]) -> None:
    seed_complete_sources(sessions)
    token = current_owner_id.set("another-owner")
    try:
        with sessions() as db, pytest.raises(GenerationInputError) as failure:
            build_input(db)
    finally:
        current_owner_id.reset(token)

    assert failure.value.code == "application_not_found"
