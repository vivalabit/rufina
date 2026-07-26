from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import StatementError
from sqlalchemy.orm import Session

from app.core.database import Base
from app.core.identity import current_owner_id
from app.models.resume_templates import (
    ResumeTemplateDefinitionCreateRequest,
    ResumeTemplateDefinitionRecord,
    ResumeTemplateDefinitionResponse,
)


def design_tokens(**overrides: object) -> dict[str, object]:
    return {
        "accentColor": "#176b87",
        "fontFamily": "Inter",
        "fontScale": 1.0,
        "density": "standard",
        "pageMargins": {
            "top": 12,
            "right": 14,
            "bottom": 12,
            "left": 14,
        },
        "headingStyle": "accent-rule",
        "skillsStyle": "pills",
        "sidebarWidth": 32,
        "sidebarSections": ["skills", "languages"],
        **overrides,
    }


def definition_record(
    *,
    record_id: str,
    owner_id: str,
    design_json: dict[str, object] | None = None,
) -> ResumeTemplateDefinitionRecord:
    now = datetime.now(UTC)
    return ResumeTemplateDefinitionRecord(
        id=record_id,
        owner_id=owner_id,
        name="Backend resume",
        base_template_id="modern_two_column",
        design_json=design_json or design_tokens(),
        version=1,
        content_sha256="a" * 64,
        created_at=now,
        updated_at=now,
    )


def test_definition_request_accepts_only_validated_design_tokens() -> None:
    request = ResumeTemplateDefinitionCreateRequest.model_validate(
        {
            "name": "  Backend resume  ",
            "baseTemplateId": "modern_two_column",
            "designJson": design_tokens(),
        }
    )

    assert request.name == "Backend resume"
    assert request.design_json.accent_color == "#176b87"
    assert request.design_json.page_margins.left == 14

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ResumeTemplateDefinitionCreateRequest.model_validate(
            {
                "name": "Unsafe template",
                "baseTemplateId": "classic_single",
                "designJson": design_tokens(customCss="body { display: none }"),
            }
        )

    with pytest.raises(ValidationError):
        ResumeTemplateDefinitionCreateRequest.model_validate(
            {
                "name": "Unsafe template",
                "baseTemplateId": "classic_single",
                "designJson": design_tokens(accentColor="javascript:alert(1)"),
            }
        )


def test_definition_json_is_revalidated_when_persisted() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add(
                definition_record(
                    record_id="definition-invalid",
                    owner_id="owner-a",
                    design_json=design_tokens(unknownToken=True),
                )
            )
            with pytest.raises(StatementError, match="Extra inputs are not permitted"):
                db.commit()
    finally:
        engine.dispose()


def test_resume_template_definitions_are_owner_scoped() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            db.add_all(
                [
                    definition_record(record_id="definition-a", owner_id="owner-a"),
                    definition_record(record_id="definition-b", owner_id="owner-b"),
                ]
            )
            db.commit()

        owner_token = current_owner_id.set("owner-a")
        try:
            with Session(engine) as db:
                records = db.scalars(select(ResumeTemplateDefinitionRecord)).all()
                assert [record.id for record in records] == ["definition-a"]
        finally:
            current_owner_id.reset(owner_token)
    finally:
        engine.dispose()


def test_definition_response_can_be_built_from_record() -> None:
    record = definition_record(record_id="definition-a", owner_id="owner-a")

    response = ResumeTemplateDefinitionResponse.model_validate(record)

    assert response.id == "definition-a"
    assert response.owner_id == "owner-a"
    assert response.design_json.sidebar_sections == ["skills", "languages"]
