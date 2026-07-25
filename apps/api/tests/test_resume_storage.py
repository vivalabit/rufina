from datetime import UTC, datetime
import hashlib

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.identity import current_owner_id
from app.models.resume import (
    ResumeMasterRecord,
    ResumeMasterVersionRecord,
    ResumeSourceFileRecord,
)


DOCX_CONTENT_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def build_resume_records(
    *,
    owner_id: str = "owner-a",
    suffix: str = "a",
) -> tuple[
    ResumeMasterRecord,
    ResumeSourceFileRecord,
    ResumeMasterVersionRecord,
]:
    now = datetime.now(UTC)
    source_content = f"docx-{suffix}".encode()
    master = ResumeMasterRecord(
        id=f"master-{suffix}",
        owner_id=owner_id,
        name=f"Master resume {suffix}",
        language="English",
        current_version=1,
        created_at=now,
        updated_at=now,
    )
    source = ResumeSourceFileRecord(
        id=f"source-{suffix}",
        owner_id=owner_id,
        resume_master_id=master.id,
        file_name=f"resume-{suffix}.docx",
        content_type=DOCX_CONTENT_TYPE,
        content_sha256=hashlib.sha256(source_content).hexdigest(),
        size_bytes=len(source_content),
        content=source_content,
        created_at=now,
    )
    version = ResumeMasterVersionRecord(
        id=f"version-{suffix}",
        owner_id=owner_id,
        resume_master_id=master.id,
        version=1,
        schema_version="1.0",
        data={
            "schemaVersion": "1.0",
            "id": master.id,
            "language": "English",
        },
        content_sha256=suffix * 64,
        source_file_id=source.id,
        created_at=now,
    )
    master.source_files.append(source)
    master.versions.append(version)
    return master, source, version


def test_persists_canonical_version_separately_from_import_source(
    sessions: sessionmaker[Session],
) -> None:
    master, source, version = build_resume_records()

    with sessions() as db:
        db.add(master)
        db.commit()
        db.refresh(master)

        assert master.current_version == 1
        assert master.versions == [version]
        assert master.source_files == [source]
        assert master.versions[0].data["schemaVersion"] == "1.0"
        assert master.source_files[0].content == b"docx-a"

    assert not hasattr(ResumeMasterRecord, "content")
    assert not hasattr(ResumeMasterVersionRecord, "content")
    assert hasattr(ResumeSourceFileRecord, "content")


def test_resume_versions_and_import_sources_are_immutable(
    sessions: sessionmaker[Session],
) -> None:
    master, source, version = build_resume_records()
    with sessions() as db:
        db.add(master)
        db.commit()

        source.file_name = "replacement.docx"
        with pytest.raises(ValueError, match="source files are immutable"):
            db.commit()
        db.rollback()

        stored_version = db.get(ResumeMasterVersionRecord, version.id)
        assert stored_version is not None
        stored_version.data = {"schemaVersion": "2.0"}
        with pytest.raises(ValueError, match="master versions are immutable"):
            db.commit()


def test_resume_version_numbers_and_source_hashes_are_unique_per_master(
    sessions: sessionmaker[Session],
) -> None:
    master, source, version = build_resume_records()
    with sessions() as db:
        db.add(master)
        db.commit()

        duplicate_source = ResumeSourceFileRecord(
            id="source-duplicate",
            owner_id=master.owner_id,
            resume_master_id=master.id,
            file_name="duplicate.docx",
            content_type=DOCX_CONTENT_TYPE,
            content_sha256=source.content_sha256,
            size_bytes=source.size_bytes,
            content=source.content,
            created_at=source.created_at,
        )
        db.add(duplicate_source)
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()

        duplicate_version = ResumeMasterVersionRecord(
            id="version-duplicate",
            owner_id=master.owner_id,
            resume_master_id=master.id,
            version=version.version,
            schema_version="1.0",
            data=version.data,
            content_sha256="d" * 64,
            source_file_id=source.id,
            created_at=version.created_at,
        )
        db.add(duplicate_version)
        with pytest.raises(IntegrityError):
            db.commit()


def test_resume_storage_is_owner_scoped(
    sessions: sessionmaker[Session],
) -> None:
    master_a, _, _ = build_resume_records(owner_id="owner-a", suffix="a")
    master_b, _, _ = build_resume_records(owner_id="owner-b", suffix="b")
    with sessions() as db:
        db.add_all([master_a, master_b])
        db.commit()

    token = current_owner_id.set("owner-a")
    try:
        with sessions() as db:
            assert [
                item.id
                for item in db.scalars(select(ResumeMasterRecord)).all()
            ] == ["master-a"]
            assert [
                item.id
                for item in db.scalars(select(ResumeMasterVersionRecord)).all()
            ] == ["version-a"]
            assert [
                item.id
                for item in db.scalars(select(ResumeSourceFileRecord)).all()
            ] == ["source-a"]
    finally:
        current_owner_id.reset(token)
