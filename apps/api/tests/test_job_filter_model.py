import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.job_filter import JobFilterSettings, JobFilterSettingsRecord
from app.services.job_filter_settings import (
    job_filter_settings_from_snapshot,
    job_filter_settings_snapshot,
    upsert_job_filter_settings,
)


def test_job_filter_settings_normalize_and_deduplicate_values() -> None:
    settings = JobFilterSettings.model_validate(
        {
            "schemaVersion": 1,
            "enabled": True,
            "allowedSeniority": ["mid", "senior", "mid"],
            "excludedSeniority": ["director", "director"],
            "targetTechnologies": [
                " Python ",
                "python",
                "Machine   Learning",
            ],
            "excludedTechnologies": [" C# ", "c#", " .NET "],
        }
    )

    assert settings.allowed_seniority == ["mid", "senior"]
    assert settings.excluded_seniority == ["director"]
    assert settings.target_technologies == ["Python", "Machine Learning"]
    assert settings.excluded_technologies == ["C#", ".NET"]
    assert job_filter_settings_snapshot(settings) == {
        "schemaVersion": 1,
        "enabled": True,
        "allowedSeniority": ["mid", "senior"],
        "excludedSeniority": ["director"],
        "targetTechnologies": ["Python", "Machine Learning"],
        "excludedTechnologies": ["C#", ".NET"],
    }


def test_missing_job_filter_snapshot_is_the_disabled_default() -> None:
    settings = job_filter_settings_from_snapshot(None)

    assert settings == JobFilterSettings()
    assert settings.enabled is False


def test_job_filter_settings_upsert_is_atomic() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    statements: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def capture_statement(
        _connection,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    with Session(engine) as db:
        upsert_job_filter_settings(
            db,
            owner_id="atomic-owner",
            settings=JobFilterSettings(enabled=True),
        )
        db.commit()
        upsert_job_filter_settings(
            db,
            owner_id="atomic-owner",
            settings=JobFilterSettings(enabled=False),
        )
        db.commit()

        stored = db.scalar(
            select(JobFilterSettingsRecord).where(
                JobFilterSettingsRecord.owner_id == "atomic-owner"
            )
        )

    upserts = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("INSERT INTO JOB_FILTER_SETTINGS")
    ]
    assert len(upserts) == 2
    assert all("ON CONFLICT" in statement.upper() for statement in upserts)
    assert stored is not None
    assert stored.data["enabled"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {
            "allowedSeniority": ["senior"],
            "excludedSeniority": ["senior"],
        },
        {
            "targetTechnologies": ["Python"],
            "excludedTechnologies": ["PYTHON"],
        },
        {"targetTechnologies": ["   "]},
        {"targetTechnologies": ["x" * 81]},
        {"targetTechnologies": [f"technology-{index}" for index in range(51)]},
        {"schemaVersion": 2},
        {"enabled": "true"},
        {"unknown": True},
    ],
)
def test_job_filter_settings_reject_invalid_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        JobFilterSettings.model_validate(payload)
