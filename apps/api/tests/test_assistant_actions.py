from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models.applications import StoredApplicationEventRecord, StoredApplicationRecord
from app.models.assistant import (
    AppliedAssistantActionRecord,
    AssistantApplicationContext,
    AssistantJobContext,
)
from app.models.documents import DocumentRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.assistant import extract_assistant_action_previews


def test_openclaw_action_previews_require_apply_and_are_idempotent() -> None:
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

    job = AssistantJobContext(
        id="job-figma",
        title="Senior Product Designer",
        company="Figma",
        location="Remote",
        match=91,
    )
    application = AssistantApplicationContext(
        id="application-figma",
        status="interview",
        nextStep="Wait for scheduling",
        notes="Recruiter screen completed",
        job=job,
    )
    profile = ProfilePayload(name="Eduard", headline="Product designer")
    raw_response = r"""I prepared five changes. Review each preview before applying.

<TASKO_ACTIONS_JSON>
[
  {"type":"add_application_note","note":"Hiring manager round confirmed."},
  {"type":"update_application_next_step","nextStep":"Prepare portfolio walkthrough"},
  {"type":"create_interview_event","title":"Figma hiring manager interview","startsAt":"2026-07-22T10:00:00+02:00","durationMinutes":45,"timezone":"Europe/Zurich","location":"Google Meet","notes":"Bring portfolio"},
  {"type":"save_document","documentType":"cover_letter","title":"Figma cover letter","content":"Dear Figma team,\n\nVerified draft."},
  {"type":"update_profile_field","field":"headline","value":"Product designer focused on complex B2B workflows"}
]
</TASKO_ACTIONS_JSON>"""
    visible_text, previews = extract_assistant_action_previews(
        raw_response,
        request_id="request-actions",
        context_kind="application",
        context_id=application.id,
        profile=profile,
        job=job,
        application=application,
    )

    assert visible_text == "I prepared five changes. Review each preview before applying."
    assert [preview.type for preview in previews] == [
        "add_application_note",
        "update_application_next_step",
        "create_interview_event",
        "save_document",
        "update_profile_field",
    ]
    assert previews[1].fields[0].before == "Wait for scheduling"

    with testing_session_local() as db:
        db.add(
            StoredApplicationRecord(
                id=application.id,
                data={
                    "id": application.id,
                    "status": "interview",
                    "appliedAt": "2026-07-10T08:00:00Z",
                    "nextStep": application.next_step,
                    "notes": application.notes,
                    "documents": [],
                    "job": {
                        "id": job.id,
                        "title": job.title,
                        "company": job.company,
                        "location": job.location,
                        "type": "Full-time",
                        "match": job.match,
                        "logo": "manual",
                        "overview": "Design complex workflows",
                        "responsibilities": [],
                        "requirements": [],
                        "skills": [],
                        "salary": "Not specified",
                        "posted": "Recently",
                        "experience": "",
                        "department": "Design",
                        "salaryAverage": "",
                        "salaryMin": "",
                        "salaryMax": "",
                        "recommendations": [],
                        "companyInfo": "",
                        "reviews": [],
                        "similarJobs": [],
                    },
                },
            )
        )
        db.add(ProfileRecord(id="default", data=profile.model_dump()))
        db.commit()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    try:
        responses = [
            client.post(
                "/assistant/actions/apply",
                json={"action": preview.model_dump(by_alias=True, mode="json")},
            )
            for preview in previews
        ]
        repeated_note = client.post(
            "/assistant/actions/apply",
            json={"action": previews[0].model_dump(by_alias=True, mode="json")},
        )

        with testing_session_local() as db:
            stored_application = db.get(StoredApplicationRecord, application.id)
            stored_profile = db.get(ProfileRecord, "default")
            event_count = db.scalar(select(func.count()).select_from(StoredApplicationEventRecord))
            document_count = db.scalar(select(func.count()).select_from(DocumentRecord))
            applied_count = db.scalar(
                select(func.count()).select_from(AppliedAssistantActionRecord)
            )
    finally:
        app.dependency_overrides.clear()

    assert all(response.status_code == 200 for response in responses)
    assert repeated_note.status_code == 200
    assert repeated_note.json() == responses[0].json()
    assert stored_application is not None
    assert "documents" not in stored_application.data
    assert "documents" not in responses[0].json()["resource"]
    assert stored_application.data["notes"].count("Hiring manager round confirmed.") == 1
    assert stored_application.data["nextStep"] == "Prepare portfolio walkthrough"
    assert stored_profile is not None
    assert stored_profile.data["headline"] == "Product designer focused on complex B2B workflows"
    assert event_count == 1
    assert document_count == 1
    assert applied_count == 5


def test_application_action_is_rejected_when_context_changed() -> None:
    profile = ProfilePayload()
    job = AssistantJobContext(id="job-one", title="Designer", company="Example")
    application = AssistantApplicationContext(
        id="application-one",
        status="applied",
        job=job,
    )
    _, previews = extract_assistant_action_previews(
        '<TASKO_ACTIONS_JSON>[{"type":"add_application_note","note":"Followed up"}]</TASKO_ACTIONS_JSON>',
        request_id="request-context",
        context_kind="application",
        context_id=application.id,
        profile=profile,
        job=job,
        application=application,
    )

    tampered = previews[0].model_copy(update={"context_id": "application-two"})
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
            "/assistant/actions/apply",
            json={"action": tampered.model_dump(by_alias=True, mode="json")},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 409
    assert "context changed" in response.json()["detail"]


def test_action_preview_strips_machine_blocks_and_keeps_only_valid_context_actions() -> None:
    profile = ProfilePayload(headline="Product designer")
    raw_response = """Review the safe previews below.

<TASKO_ACTIONS_JSON>
[
  {"type":"add_application_note","note":"Requires an application"},
  {"type":"update_profile_field","field":"headline","value":"Senior product designer"},
  {"type":"update_profile_field","field":"email","value":"not-allowed@example.com"},
  {"type":"create_interview_event","title":"Interview","startsAt":"2026-07-22T10:00:00","durationMinutes":45,"timezone":"Europe/Zurich"},
  {"type":"unknown_action","value":"ignored"}
]
</TASKO_ACTIONS_JSON>"""

    visible_text, previews = extract_assistant_action_previews(
        raw_response,
        request_id="request-filter-actions",
        context_kind="profile",
        context_id="",
        profile=profile,
        job=None,
        application=None,
    )

    assert visible_text == "Review the safe previews below."
    assert "TASKO_ACTIONS_JSON" not in visible_text
    assert [preview.type for preview in previews] == ["update_profile_field"]
    assert previews[0].fields[0].before == "Product designer"
    assert previews[0].fields[0].after == "Senior product designer"
    assert previews[0].payload == {
        "field": "headline",
        "value": "Senior product designer",
        "expectedValue": "Product designer",
    }
