import json
from collections import deque
from copy import deepcopy
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.documents import DocumentFileRecord, DocumentRecord, DocumentVersionRecord
from app.models.generation_runs import (
    GenerationRunArtifactRecord,
    GenerationRunCheckRecord,
    GenerationRunEventRecord,
    GenerationRunMessageRecord,
    GenerationRunStartRequest,
)
from app.models.generation_workflow import DraftBundle, GeneratedDraftBundle
from app.models.jobs import StoredJobRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.models.resume import MasterResume
from app.services.ai_backend import AIResult, AIUsage
from app.services.candidate_profile import canonical_hash, profile_resume
from app.services.generation_grounding import (
    GenerationGroundingError,
    validate_grounded_bundle,
)
from app.services.generation_input import GenerationInputError
from app.services.generation_latex import CompiledDocument, build_resume_tex
from app.services.generation_resume_templates import resolve_generation_resume_template
from app.services.generation_store import create_generation_run
from app.services.generation_verification import PdfCheck, PdfVerificationReport, VerifiedPdf
from app.services.generation_workflow import GenerationWorkflow, GenerationWorkflowError
from app.services.profile_versions import update_profile_data


class FakeBackend:
    def __init__(
        self,
        payloads: list[dict[str, object]],
        *,
        name: str = "openclaw_codex",
    ) -> None:
        self.name = name
        self.payloads = deque(payloads)
        self.requests = []

    def generate(self, request):
        self.requests.append(request)
        payload = self.payloads.popleft()
        return AIResult(
            text=json.dumps(payload),
            structured_data=payload,
            model=request.model,
            backend=self.name,
            usage=AIUsage(input_tokens=10, output_tokens=20, total_tokens=30),
            latency_ms=5,
            session_id=request.session_id,
            raw_response=json.dumps(payload),
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


def _settings(backend: str = "openclaw_codex") -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend_mode=backend,
        openai_api_model="gpt-direct",
        openai_api_reasoning_effort="medium",
        openai_api_timeout_seconds=120,
        openai_api_max_attempts=2,
        openai_api_retry_backoff_seconds=0,
        openclaw_command="openclaw",
        openclaw_assistant_agent_id="rufina-assistant",
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=1,
        openclaw_assistant_retry_backoff_seconds=0,
        openai_api_key="",
        openai_api_base_url="https://api.openai.com/v1",
    )


def _start() -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single"}},
        userPreferences="Keep it factual.",
        idempotencyKey="workflow-1",
    )


def _seed(sessions: sessionmaker[Session]) -> None:
    seed_complete_sources(sessions)
    with sessions() as db:
        profile = db.get(ProfileRecord, "default")
        data = dict(profile.data)
        data["summary"] = {"text": "Builds reliable platforms.", "evidenceIds": ["source:one"]}
        data["evidence"] = [
            {"id": "source:one", "type": "source", "text": "Builds reliable platforms."}
        ]
        update_profile_data(db, profile, data=ProfilePayload.model_validate(data).model_dump(mode="json"), reason="fixture")
        db.commit()


def _fit() -> dict[str, object]:
    return {
        "eligible": True,
        "overallScore": 82,
        "recommendation": "yes",
        "summary": "Good evidence-backed fit.",
        "strengths": ["Platform experience"],
        "gaps": ["No explicit Go experience"],
        "keywords": [
            {
                "term": "Python",
                "importance": "required",
                "support": "supported",
                "evidenceIds": [],
            }
        ],
        "clarificationQuestions": [],
    }


def _draft() -> dict[str, object]:
    return {
        "resume": {
            "schemaVersion": "1.0",
            "id": "tailored-1",
            "masterResumeId": "default",
            "targetJobId": "vacancy-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace", "headline": "Platform Engineer"},
            "summary": {
                "text": "Builds reliable platforms.",
                "evidenceIds": ["source:one"],
            },
            "experiences": [],
            "skills": [],
            "education": [],
            "projects": [],
            "certifications": [],
            "languages": [],
            "additionalSections": [],
            "evidence": [
                {
                    "id": "source:one",
                    "type": "source",
                    "text": "Builds reliable platforms.",
                }
            ],
            "sectionOrder": ["summary"],
        },
        "coverLetter": None,
    }


def _generated_draft() -> dict[str, object]:
    draft = _draft()
    del draft["resume"]["evidence"]
    return draft


def _review() -> dict[str, object]:
    return {
        "approved": True,
        "summary": "Grounded and consistent.",
        "findings": [],
        "meaningfulChanges": ["Focused the headline on platform engineering"],
        "companySources": [],
    }


def _visual_review() -> dict[str, object]:
    return {
        "approved": True,
        "summary": "Both rendered pages are balanced and readable.",
        "findings": [],
    }


def _renderer(bundle: DraftBundle) -> tuple[CompiledDocument, ...]:
    assert bundle.resume is not None
    return (
        CompiledDocument(
            document_type="tailored_resume",
            engine="lualatex",
            file_name="cv.pdf",
            tex_source=build_resume_tex(bundle.resume),
            pdf=b"%PDF-1.7\nfake",
            compile_log="ok",
        ),
    )


def _verifier(document: CompiledDocument, **_kwargs) -> VerifiedPdf:
    return VerifiedPdf(
        report=PdfVerificationReport(
            documentType=document.document_type,
            pageCount=1,
            extractedText="Ada Lovelace builds reliable platforms with Python.",
            checks=(PdfCheck(name="text_layer", status="passed", message="Readable"),),
        ),
        page_images=(b"fake-png",),
    )


@pytest.mark.parametrize("backend_name", ["openai_api", "openclaw_codex"])
def test_workflow_pauses_after_fit_then_uses_separate_author_and_reviewer_sessions(
    sessions: sessionmaker[Session],
    backend_name: str,
) -> None:
    _seed(sessions)
    settings = _settings(backend_name)
    backend = FakeBackend(
        [_fit(), _generated_draft(), _review(), _visual_review()],
        name=backend_name,
    )
    workflow = GenerationWorkflow(
        settings=settings,
        backend=backend,
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=settings,
        )
        evaluation = workflow.evaluate_fit(db, run)
        assert evaluation.overall_score == 82
        assert run.status == "awaiting_approval"
        assert run.pending_question["id"] == "continue_after_fit"

        outcome = workflow.respond_to_fit(db, run, continue_generation=True)
        messages = db.scalars(
            select(GenerationRunMessageRecord)
            .where(GenerationRunMessageRecord.run_id == run.id)
            .order_by(GenerationRunMessageRecord.sequence)
        ).all()
        artifacts = db.scalars(
            select(GenerationRunArtifactRecord).where(GenerationRunArtifactRecord.run_id == run.id)
        ).all()
        checks = db.scalars(
            select(GenerationRunCheckRecord).where(GenerationRunCheckRecord.run_id == run.id)
        ).all()

    assert outcome is not None and outcome.review.approved is True
    assert run.status == "completed" and run.stage == "final_review"
    assert run.backend == backend_name
    assert any(request.enable_web_search for request in backend.requests)
    assert backend.requests[-1].image_inputs
    sessions_used = {request.session_id.rsplit(":", 1)[-1] for request in backend.requests}
    assert sessions_used == {"fit", "author", "reviewer"}
    assert {message.actor for message in messages} >= {"author", "reviewer", "user"}
    assert any(message.raw_response.startswith("{") for message in messages)
    assert "BEGIN UNTRUSTED APPLICATION DATA" in backend.requests[0].prompt
    assert {artifact.artifact_type for artifact in artifacts} >= {
        "fit_evaluation_json",
        "draft_bundle_json",
        "review_feedback_json",
        "reviewed_draft_bundle_json",
        "resume_pdf",
        "resume_tex",
        "visual_review_json",
    }
    assert checks and all(check.artifact_sha256 for check in checks)
    assert run.result["documents"][0]["pdfUrl"].endswith("/pdf")


@pytest.mark.parametrize(
    "language,description,summary",
    [
        ("German", "Sie entwickeln zuverlässige Plattformen für unser Team.", "Entwickelt zuverlässige Plattformen."),
        ("French", "Vous développez des plateformes fiables pour notre équipe.", "Développe des plateformes fiables."),
    ],
)
def test_auto_language_uses_vacancy_context_and_preserves_generated_language(
    sessions: sessionmaker[Session], language: str, description: str, summary: str,
) -> None:
    _seed(sessions)
    generated = _generated_draft()
    generated["resume"]["language"] = language
    generated["resume"]["summary"]["text"] = summary
    backend = FakeBackend([_fit(), generated, _review(), _visual_review()])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier,
    )
    with sessions() as db:
        vacancy = db.scalar(select(StoredJobRecord).where(StoredJobRecord.id == "vacancy-1"))
        vacancy.data = {**vacancy.data, "overview": description, "responsibilities": [], "requirements": []}
        db.commit()
        run = create_generation_run(
            db, application_id="application-1",
            request=_start().model_copy(update={"language": "Auto"}), settings=_settings(),
        )
        workflow.evaluate_fit(db, run)
        outcome = workflow.respond_to_fit(db, run, continue_generation=True)
        assert outcome.draft.resume.language == language
        assert outcome.draft.resume.summary.text == summary
        assert run.result["draft"]["resume"]["language"] == language

    author_prompt = backend.requests[1].prompt
    reviewer_prompt = backend.requests[2].prompt
    for prompt in (author_prompt, reviewer_prompt):
        assert description in prompt
        assert '"requestedLanguage": "Auto"' in prompt
        assert "vacancy.fullDescription" in prompt
        assert "The CV uses the Master Resume language" not in prompt
    assert "both the CV and cover" in author_prompt
    assert "blocking consistency" in reviewer_prompt


def test_all_stages_share_frozen_core_skill_membership_and_resolved_languages(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    core_names = ["CI/CD", "GitHub Actions", "GitHub", "Playwright", "Pytest"]
    with sessions() as db:
        profile = db.get(ProfileRecord, "default")
        update_profile_data(
            db, profile, data={**profile.data, "skills": "\n".join([*core_names, "Machine Learning"])},
            reason="fixture",
        )
        db.commit()

    generated = _generated_draft()
    generated["resume"]["language"] = "German"
    review = {
        **_review(),
        "findings": [{
            "severity": "warning", "category": "clarity", "document": "resume",
            "message": "Clarify the introduction.",
        }],
    }
    visual_failure = {
        "approved": False, "summary": "Move the heading with its paragraph.",
        "findings": [{
            "document": "resume", "page": 1, "severity": "blocking",
            "message": "An orphaned heading needs layout repair.",
        }],
    }
    backend = FakeBackend([
        _fit(), generated, review, generated, visual_failure, generated, _visual_review(),
    ])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", settings=_settings(),
            request=_start().model_copy(update={"language": "Auto"}),
        )
        profile = db.get(ProfileRecord, "default")
        update_profile_data(
            db, profile, data={**profile.data, "skills": "Rust"}, reason="changed_after_snapshot",
        )
        db.commit()
        workflow.evaluate_fit(db, run)
        outcome = workflow.respond_to_fit(db, run, continue_generation=True)
        assert run.status == "completed"
        expected_skills = [
            {"id": skill.id, "name": skill.name, "category": skill.category}
            for skill in outcome.draft.resume.skills
        ]
        assert [skill["name"] for skill in expected_skills] == core_names
        assert {skill["category"] for skill in expected_skills} == {"Tools / DevOps"}

    # Fit, initial author, reviewer, revision, visual review, PDF repair, final visual review.
    assert len(backend.requests) == 7
    for index, request in enumerate(backend.requests):
        context = json.loads(
            request.prompt.split("BEGIN UNTRUSTED APPLICATION DATA\n")[1].split("\nEND UNTRUSTED")[0]
        )
        assert all(skill["category"] == "" for skill in context["masterResume"]["skills"])
        assert context["skillPolicy"] == {
            "categoryOrder": ["Languages", "Frameworks", "Databases", "Tools / DevOps"],
            "requiredSkills": expected_skills,
            "exactDuplicatesMayBeConsolidated": True,
        }
        assert context["requestedLanguage"] == "Auto"
        assert context["documentLanguages"] == (
            {} if index < 2 else {"tailored_resume": "German"}
        )
        assert "The request preference" in request.prompt or "valid preference" in request.prompt


@pytest.mark.parametrize("document_key", ["resume", "coverLetter"])
def test_auto_is_rejected_only_when_used_as_actual_document_language(sessions, document_key):
    from test_generation_latex import _letter

    _seed(sessions)
    generated = _generated_draft()
    document_type = "tailored_resume"
    if document_key == "coverLetter":
        generated["resume"] = None
        generated["coverLetter"] = _letter().model_dump(mode="json", by_alias=True)
        document_type = "cover_letter"
    generated[document_key]["language"] = "Auto"
    backend = FakeBackend([_fit(), generated])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend,
        renderer=lambda _bundle: pytest.fail("Unresolved language must not be rendered"),
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", settings=_settings(),
            request=_start().model_copy(update={
                "language": "Auto", "document_types": (document_type,),
            }),
        )
        workflow.evaluate_fit(db, run)
        with pytest.raises(GenerationWorkflowError, match="actual language") as failure:
            workflow.respond_to_fit(db, run, continue_generation=True)
        assert failure.value.code == "invalid_ai_response"
        assert run.status == "failed"
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
    assert len(backend.requests) == 2


def test_generated_drafts_use_only_ids_and_store_canonical_evidence_at_every_stage(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    with sessions() as db:
        profile = db.get(ProfileRecord, "default")
        source_text = (
            "Designed and operated reliable platforms, including deployment automation, "
            "incident response, service monitoring, and recovery procedures."
        )
        other_source_text = "Built Python APIs with comprehensive tests and clear interfaces."
        data = {
            **profile.data,
            "summary": {"text": source_text, "evidenceIds": ["source:one", "source:two"]},
            "evidence": [
                {"id": "source:one", "type": "source", "text": source_text},
                {"id": "source:two", "type": "source", "text": other_source_text},
            ],
        }
        update_profile_data(db, profile, data=data, reason="long_master_resume")
        db.commit()

    initial = _generated_draft()
    revised = _generated_draft()
    revised["resume"]["summary"] = {
        "text": "Develops tested Python APIs.",
        "evidenceIds": ["source:two"],
    }
    repaired = _generated_draft()
    repaired["resume"]["summary"]["text"] = "Builds reliable platforms."
    review = {
        **_review(),
        "findings": [{
            "severity": "warning",
            "category": "clarity",
            "message": "Focus the summary on API development.",
            "document": "resume",
        }],
    }
    visual_failure = {
        "approved": False,
        "summary": "Shorten the summary to fit the page.",
        "findings": [],
    }
    backend = FakeBackend(
        [_fit(), initial, review, revised, visual_failure, repaired, _visual_review()]
    )
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier
    )
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings()
        )
        frozen = run.input_snapshot["request"]["masterProfileVersion"]
        master = profile_resume(ProfilePayload.model_validate(frozen["data"]), "default")
        canonical = {proof.id: proof.model_dump(mode="json", by_alias=True) for proof in master.evidence}
        workflow.evaluate_fit(db, run)
        outcome = workflow.respond_to_fit(db, run, continue_generation=True)

        assert run.status == "completed"
        assert outcome is not None and outcome.draft.resume is not None
        assert outcome.draft.resume.summary.text == repaired["resume"]["summary"]["text"]
        assert run.result["draft"]["resume"]["evidence"] == [canonical["source:one"]]
        document = db.scalar(select(DocumentVersionRecord))
        assert document is not None
        persisted_resume = json.loads(document.content)
        assert persisted_resume["evidence"] == [canonical["source:one"]]
        assert persisted_resume["summary"] == repaired["resume"]["summary"]

        expected_artifacts = {
            "draft_bundle_json": (initial, "source:one"),
            "reviewed_draft_bundle_json": (revised, "source:two"),
            "repair_bundle_json": (repaired, "source:one"),
        }
        artifacts = db.scalars(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type.in_(expected_artifacts),
            )
        ).all()
        assert {artifact.artifact_type for artifact in artifacts} == set(expected_artifacts)
        for artifact in artifacts:
            generated, evidence_id = expected_artifacts[artifact.artifact_type]
            persisted = json.loads(artifact.content)
            assert persisted["resume"]["evidence"] == [canonical[evidence_id]]
            assert persisted["resume"]["summary"] == generated["resume"]["summary"]

        author_messages = db.scalars(
            select(GenerationRunMessageRecord).where(
                GenerationRunMessageRecord.run_id == run.id,
                GenerationRunMessageRecord.actor == "author",
                GenerationRunMessageRecord.role == "assistant",
            ).order_by(GenerationRunMessageRecord.sequence)
        ).all()
        assert len(author_messages) == 3
        for message, generated in zip(author_messages, (initial, revised, repaired), strict=True):
            assert json.loads(message.raw_response) == generated
            assert "evidence" not in json.loads(message.content)["resume"]

    assert len(backend.requests) == 7
    for index in (1, 3, 5):
        assert backend.requests[index].response_model is GeneratedDraftBundle
        assert '"evidence":' not in json.dumps(
            backend.requests[index].response_model.model_json_schema(by_alias=True)
        )
    for request in backend.requests:
        context = json.loads(
            request.prompt.split("BEGIN UNTRUSTED APPLICATION DATA\n")[1].split("\nEND UNTRUSTED")[0]
        )
        assert {proof["id"]: proof for proof in context["masterResume"]["evidence"]} == canonical
        for key in ("draft", "previousDraft"):
            if key in context:
                assert "evidence" not in context[key]["resume"]
                assert context[key]["resume"]["summary"]["evidenceIds"]


@pytest.mark.parametrize("invalid_stage", ["initial", "revision", "pdf_repair"])
def test_unknown_generated_evidence_cannot_be_persisted_or_published(
    sessions: sessionmaker[Session],
    invalid_stage: str,
) -> None:
    _seed(sessions)
    invalid = _generated_draft()
    invalid["resume"]["summary"]["evidenceIds"] = ["source:invented"]
    review = {
        **_review(),
        "findings": [{
            "severity": "warning",
            "category": "clarity",
            "message": "Clarify the summary.",
            "document": "resume",
        }],
    }
    payloads = {
        "initial": [_fit(), invalid],
        "revision": [_fit(), _generated_draft(), review, invalid],
        "pdf_repair": [
            _fit(), _generated_draft(), _review(),
            {"approved": False, "summary": "Shorten the summary.", "findings": []}, invalid,
        ],
    }
    backend = FakeBackend(payloads[invalid_stage])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier
    )
    rejected_artifact = {
        "initial": "draft_bundle_json",
        "revision": "reviewed_draft_bundle_json",
        "pdf_repair": "repair_bundle_json",
    }[invalid_stage]
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings()
        )
        workflow.evaluate_fit(db, run)
        with pytest.raises(GenerationGroundingError, match="unknown evidence"):
            workflow.respond_to_fit(db, run, continue_generation=True)

        assert run.status == "failed"
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        assert db.scalar(
            select(func.count()).select_from(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type == rejected_artifact,
            )
        ) == 0
        assert "source:invented" not in json.dumps(run.result)
    assert not backend.payloads


@pytest.mark.parametrize("template_id", ["moderncv_banking", "roman"])
@pytest.mark.parametrize("recovered", [False, True])
def test_selected_resume_template_survives_draft_repair_recovery_and_import(
    sessions: sessionmaker[Session],
    template_id: str,
    recovered: bool,
) -> None:
    _seed(sessions)
    seen_templates: list[str] = []

    def selected_renderer(bundle: DraftBundle, *, resume_template_id: str):
        seen_templates.append(resume_template_id)
        return _renderer(bundle)

    visual_failure = {
        "approved": False,
        "summary": "Shorten the last paragraph to fit the page.",
        "findings": [],
    }
    payloads = [visual_failure, _generated_draft(), _visual_review()]
    if not recovered:
        payloads = [_fit(), _generated_draft(), _review(), *payloads]
    backend = FakeBackend(payloads)
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=selected_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start().model_copy(
                update={"formatting_parameters": {"tailored_resume": {"templateId": template_id}}}
            ),
            settings=_settings(),
        )
        frozen = run.input_snapshot["request"]["masterProfileVersion"]
        profile = db.get(ProfileRecord, "default")
        updated = {**profile.data, "name": "Changed after start", "additional_notes": "New fact"}
        update_profile_data(db, profile, data=updated, reason="edit_while_generating")
        db.commit()
        if recovered:
            run.stage = "pdf_checks"
            run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
            db.commit()
            workflow.resume_pdf_checks(db, run)
        else:
            workflow.evaluate_fit(db, run)
            workflow.respond_to_fit(db, run, continue_generation=True)
        assert run.status == "completed"
        document_file = db.scalar(select(DocumentFileRecord))
        assert document_file is not None
        assert document_file.renderer_template_id == template_id
        assert document_file.renderer_design_sha256 == (
            resolve_generation_resume_template(template_id).content_sha256
        )
        pdf = db.scalar(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type == "resume_pdf",
            )
        )
        assert pdf is not None and pdf.artifact_metadata["templateId"] == template_id
    assert seen_templates == [template_id, template_id]
    for request in backend.requests:
        assert '"candidateProfileVersion"' in request.prompt
        assert frozen["contentSha256"] in request.prompt
        assert '"masterResume"' in request.prompt
        assert 'Changed after start' not in request.prompt
        assert 'New fact' not in request.prompt


def test_recovered_draft_restores_profile_essentials_from_frozen_source(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    rendered: list[DraftBundle] = []

    def capture_renderer(bundle: DraftBundle):
        rendered.append(bundle)
        return _renderer(bundle)

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([_visual_review()]),
        renderer=capture_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        profile = db.get(ProfileRecord, "default")
        data = deepcopy(profile.data)
        data["experience"] = json.dumps([
            {
                "id": "earlier-role",
                "company": "First AG",
                "title": "Backend Engineer",
                "start_date": "2020",
                "end_date": "2022",
                "description": "Built reliable APIs.",
            },
            {
                "id": "current-role",
                "company": "Second AG",
                "title": "Platform Engineer",
                "start_date": "2022",
                "is_current": True,
                "description": "Built data pipelines.",
            },
        ])
        data["skills"] = "Python\nDjango\nTypeScript"
        data["languages"] = [
            {
                "id": f"language-{name.lower()}",
                "name": name,
                "proficiency": proficiency,
                "evidenceIds": [f"source:language-{name.lower()}"],
            }
            for name, proficiency in (("Ukrainian", "Native"), ("Russian", "Native"), ("English", "B2"))
        ]
        data["evidence"].extend(
            {
                "id": language["evidenceIds"][0],
                "type": "source",
                "text": f"{language['name']}: {language['proficiency']}",
            }
            for language in data["languages"]
        )
        update_profile_data(db, profile, data=data, reason="fixture")
        db.commit()
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings()
        )
        frozen_input = deepcopy(run.input_snapshot)
        frozen_profile = frozen_input["request"]["masterProfileVersion"]
        master = profile_resume(ProfilePayload.model_validate(frozen_profile["data"]), "default")

        # A valid persisted draft from the old selection policy lost the native
        # languages/frameworks and ranked employers by relevance.
        draft = _draft()
        draft["resume"]["experiences"] = [
            {
                "id": item.id,
                "masterExperienceId": item.id,
                "company": item.company,
                "title": item.title,
                "period": f"{item.start_date} – {'Present' if item.is_current else item.end_date}",
                "bullets": [bullet.model_dump(mode="json", by_alias=True) for bullet in item.bullets],
            }
            for item in reversed(master.experiences)
        ]
        draft["resume"]["skills"] = [master.skills[0].model_dump(mode="json", by_alias=True)]
        draft["resume"]["evidence"] = [
            item.model_dump(mode="json", by_alias=True) for item in master.evidence
        ]
        draft["resume"]["sectionOrder"] = ["summary", "experience", "skills"]
        DraftBundle.model_validate(draft)
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": draft, "review": _review()}

        # Recovery must not fill omissions from today's mutable profile.
        update_profile_data(
            db,
            profile,
            data={**data, "experience": "[]", "skills": "Go", "languages": []},
            reason="edit_while_generating",
        )
        db.commit()
        outcome = workflow.resume_pdf_checks(db, run)

        assert run.status == "completed"
        assert run.input_snapshot == frozen_input
        assert len(rendered) == 1
        assert rendered[0] == outcome
        assert outcome.resume is not None
        assert [item.master_experience_id for item in outcome.resume.experiences] == [
            "earlier-role", "current-role",
        ]
        assert outcome.resume.languages == master.languages
        assert [item.name for item in outcome.resume.skills] == ["Python", "TypeScript", "Django"]
        assert "languages" in outcome.resume.section_order
        validate_grounded_bundle(outcome, master_resume=master, target_job_id="vacancy-1")
        assert run.result["draft"] == outcome.model_dump(mode="json", by_alias=True)
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 1


@pytest.mark.parametrize(
    ("legacy_id", "legacy_version"),
    [("classic_single", "1.0.1"), ("b426540f-a1e2-4e8b-965e-10ab38b28b40", "2")],
)
def test_recovered_legacy_snapshot_keeps_input_and_records_actual_banking_artifact_metadata(
    sessions: sessionmaker[Session],
    legacy_id: str,
    legacy_version: str,
) -> None:
    _seed(sessions)
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([_visual_review()]),
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        legacy = {
            **run.input_snapshot["templates"][0],
            "templateId": legacy_id,
            "templateVersion": legacy_version,
            "contentSha256": "f" * 64,
        }
        # Simulate an actual pre-profile snapshot. Recovery has no dependency
        # on either today's profile contents or the old resume tables.
        profile = db.get(ProfileRecord, "default")
        old_source = profile_resume(ProfilePayload.model_validate(profile.data), "legacy-master").model_dump(mode="json", by_alias=True)
        old_request = {**run.input_snapshot["request"], "masterProfileVersion": {
            "id": "legacy-master", "version": 1, "contentSha256": canonical_hash(old_source), "data": old_source,
        }}
        run.input_snapshot = {**run.input_snapshot, "request": old_request, "templates": [legacy]}
        original_input = deepcopy(run.input_snapshot)
        original_fingerprint = run.input_fingerprint
        run.stage = "pdf_checks"
        draft = _draft()
        draft["resume"]["masterResumeId"] = "legacy-master"
        run.result = {"fit": _fit(), "draft": draft, "review": _review()}
        db.commit()
        workflow.resume_pdf_checks(db, run)

        assert run.status == "completed"
        assert run.input_snapshot == original_input
        assert run.input_fingerprint == original_fingerprint
        document_file = db.scalar(select(DocumentFileRecord))
        assert document_file is not None
        assert document_file.renderer_template_id == "moderncv_banking"
        assert document_file.renderer_design_sha256 != legacy["contentSha256"]


def test_recovery_rejects_changed_template_before_rendering_or_publication(
    sessions: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    _seed(sessions)
    from app.services import generation_resume_templates

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([]),
        renderer=lambda _bundle: pytest.fail("Changed template must not be rendered"),
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        changed_source = tmp_path / "generation_latex.py"
        changed_source.write_text("# A different deployed renderer\n")
        monkeypatch.setattr(generation_resume_templates, "_RENDERER_SOURCE", changed_source)

        with pytest.raises(GenerationInputError, match="Start a new generation run") as failure:
            workflow.resume_pdf_checks(db, run)

        assert failure.value.code == "resume_template_changed"
        assert run.status == "failed"
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_renderer_type_error_is_not_retried_without_template_selection(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    calls: list[str] = []

    def broken_renderer(_bundle: DraftBundle, *, resume_template_id: str):
        calls.append(resume_template_id)
        raise TypeError("An internal rendering error")

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([]),
        renderer=broken_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        with pytest.raises(TypeError, match="internal rendering error"):
            workflow.resume_pdf_checks(db, run)
        assert run.status == "failed"
    assert calls == ["moderncv_banking"]


def test_declining_fit_finishes_without_drafting(sessions: sessionmaker[Session]) -> None:
    _seed(sessions)
    backend = FakeBackend([_fit()])
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        workflow.evaluate_fit(db, run)
        assert workflow.respond_to_fit(db, run, continue_generation=False) is None

    assert run.status == "cancelled"
    assert len(backend.requests) == 1


def test_pdf_check_database_failure_is_recorded_after_rollback(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.generation_store import persist_run_check

    _seed(sessions)

    def invalid_check(db, **kwargs):
        check = persist_run_check(db, **kwargs)
        check.status = None  # Real failed flush, including SQLAlchemy's expired ORM state.
        db.flush()

    monkeypatch.setattr("app.services.generation_workflow.persist_run_check", invalid_check)
    backend = FakeBackend([])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings(),
        )
        run.stage = "pdf_checks"
        saved_result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        run.result = saved_result
        run.lease_token = "test-worker"
        db.commit()

        with pytest.raises(IntegrityError):
            workflow.resume_pdf_checks(db, run)

        db.refresh(run)
        assert run.status == "failed"
        assert run.stage == "pdf_checks"
        assert run.error["code"] == "database_error"
        assert run.lease_token is None
        assert run.result["review"] == saved_result["review"]
        assert run.result["draft"]
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        assert db.scalar(select(func.count()).select_from(GenerationRunCheckRecord)) == 0
        assert db.scalar(select(func.count()).select_from(GenerationRunEventRecord).where(
            GenerationRunEventRecord.run_id == run.id,
            GenerationRunEventRecord.kind == "run.failed",
        )) == 1
    assert backend.requests == []


def test_recovered_pdf_failure_is_terminal_and_does_not_publish_partial_documents(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)

    def unavailable_compiler(_bundle: DraftBundle):
        raise GenerationWorkflowError(
            "No supported TeX compiler is installed",
            code="pdf_compiler_unavailable",
        )

    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=FakeBackend([]),
        renderer=unavailable_compiler,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "queued"
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()

        with pytest.raises(GenerationWorkflowError, match="No supported TeX"):
            workflow.resume_pdf_checks(db, run)

        assert run.status == "failed"
        assert run.error == {
            "code": "pdf_compiler_unavailable",
            "message": "No supported TeX compiler is installed",
            "retryable": False,
        }
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_pdf_verification_failure_preserves_actionable_terminal_diagnostics(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    visual_failure = {
        "approved": False,
        "summary": "The last page is visually unsafe.",
        "findings": [
            {
                "document": "resume",
                "page": 1,
                "severity": "blocking",
                "message": "Experience text overlaps the footer.",
            }
        ],
    }

    def failing_verifier(document: CompiledDocument, **_kwargs) -> VerifiedPdf:
        return VerifiedPdf(
            report=PdfVerificationReport(
                documentType=document.document_type,
                pageCount=3,
                extractedText="Ada Lovelace builds reliable platforms.",
                checks=(
                    PdfCheck(name="text_layer", status="passed", message="Readable"),
                    PdfCheck(
                        name="page_count",
                        status="failed",
                        message="Found 3 page(s); allowed 1-2",
                    ),
                    PdfCheck(
                        name="keyword:Python",
                        status="warning",
                        message="Keyword missing: Python",
                    ),
                ),
            ),
            page_images=(b"fake-png",),
        )

    backend = FakeBackend(
        [visual_failure, _generated_draft(), visual_failure, _generated_draft(), visual_failure]
    )
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=_renderer,
        verifier=failing_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "queued"
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()

        with pytest.raises(GenerationWorkflowError) as exc_info:
            workflow.resume_pdf_checks(db, run)

        message = str(exc_info.value)
        assert exc_info.value.code == "pdf_verification_failed"
        assert exc_info.value.retryable is True
        assert message.startswith("PDF verification did not pass after three attempts:")
        assert "Found 3 page(s); allowed 1-2" in message
        assert "The last page is visually unsafe." in message
        assert "Experience text overlaps the footer." in message
        assert "Readable" not in message
        assert "Keyword missing: Python" not in message
        assert run.status == "failed"
        assert run.error == {
            "code": "pdf_verification_failed",
            "message": message,
            "retryable": True,
        }
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0
        visual_artifacts = db.scalars(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == run.id,
                GenerationRunArtifactRecord.artifact_type == "visual_review_json",
            )
        ).all()
        assert len(visual_artifacts) == 3


@pytest.mark.parametrize("check_name", ["layout_unavailable", "page_images"])
def test_unavailable_pdf_checks_preserve_artifacts_without_model_repairs(sessions, check_name):
    _seed(sessions)
    verification_calls = []

    def unavailable_verifier(document, **_kwargs):
        verification_calls.append(document)
        return VerifiedPdf(
            report=PdfVerificationReport(
                documentType=document.document_type, pageCount=1, extractedText="Ada Lovelace",
                checks=(PdfCheck(
                    name=check_name, status="failed", message="Verification dependency unavailable",
                ),),
            ),
            page_images=(),
        )

    backend = FakeBackend([])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=unavailable_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings(),
        )
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        with pytest.raises(GenerationWorkflowError) as failure:
            workflow.resume_pdf_checks(db, run)
        assert failure.value.code == "pdf_verification_unavailable"
        assert failure.value.retryable is True
        assert run.status == "failed"
        assert len(verification_calls) == 1
        assert backend.requests == []
        artifacts = db.scalars(select(GenerationRunArtifactRecord).where(
            GenerationRunArtifactRecord.run_id == run.id,
        )).all()
        assert {artifact.artifact_type for artifact in artifacts} >= {
            "resume_pdf_attempt", "resume_tex_attempt", "resume_verification_report",
        }
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_visual_approval_cannot_override_its_own_blocking_findings(sessions):
    _seed(sessions)
    inconsistent_visual = {
        "approved": True, "summary": "One heading still needs repair.",
        "findings": [{
            "document": "resume", "page": 1, "severity": "blocking",
            "message": "The experience heading is separated from its first bullet.",
        }],
    }
    backend = FakeBackend([inconsistent_visual, _generated_draft(), _visual_review()])
    workflow = GenerationWorkflow(
        settings=_settings(), backend=backend, renderer=_renderer, verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", request=_start(), settings=_settings(),
        )
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()
        workflow.resume_pdf_checks(db, run)
        assert run.status == "completed"
        visual_reports = db.scalars(select(GenerationRunArtifactRecord).where(
            GenerationRunArtifactRecord.run_id == run.id,
            GenerationRunArtifactRecord.artifact_type == "visual_review_json",
        ).order_by(GenerationRunArtifactRecord.version)).all()
        assert [json.loads(artifact.content)["approved"] for artifact in visual_reports] == [False, True]
        assert len(backend.requests) == 3
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 1


def test_visual_rejection_blocks_publication_after_deterministic_checks_pass(
    sessions: sessionmaker[Session],
) -> None:
    _seed(sessions)
    visual_failure = {
        "approved": False,
        "summary": "The rendered page could not be safely approved.",
        "findings": [
            {
                "document": "resume",
                "page": 1,
                "severity": "blocking",
                "message": "Experience text overlaps the footer.",
            }
        ],
    }
    backend = FakeBackend(
        [visual_failure, _generated_draft(), visual_failure, _generated_draft(), visual_failure]
    )
    workflow = GenerationWorkflow(
        settings=_settings(),
        backend=backend,
        renderer=_renderer,
        verifier=_verifier,
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        run.status = "queued"
        run.stage = "pdf_checks"
        run.result = {"fit": _fit(), "draft": _draft(), "review": _review()}
        db.commit()

        with pytest.raises(GenerationWorkflowError) as exc_info:
            workflow.resume_pdf_checks(db, run)

        message = str(exc_info.value)
        assert "The rendered page could not be safely approved." in message
        assert "Experience text overlaps the footer." in message
        assert "CV:" not in message
        assert run.status == "failed"
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 0


def test_grounding_rejects_modified_canonical_evidence() -> None:
    master = MasterResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "master-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace"},
            "summary": {"text": "Built APIs.", "evidenceIds": ["source:one"]},
            "evidence": [{"id": "source:one", "type": "source", "text": "Built APIs."}],
            "sectionOrder": ["summary"],
        }
    )
    bundle = DraftBundle.model_validate(
        {
            "resume": {
                "schemaVersion": "1.0",
                "id": "tailored-1",
                "masterResumeId": "master-1",
                "targetJobId": "job-1",
                "language": "English",
                "basics": {"fullName": "Ada Lovelace"},
                "summary": {
                    "text": "Built APIs for millions of users.",
                    "evidenceIds": ["source:one"],
                },
                "evidence": [
                    {
                        "id": "source:one",
                        "type": "source",
                        "text": "Built APIs for millions of users.",
                    }
                ],
                "sectionOrder": ["summary"],
            }
        }
    )

    with pytest.raises(GenerationGroundingError, match="non-canonical"):
        validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")


@pytest.mark.parametrize("template_id", ["moderncv_banking", "roman"])
@pytest.mark.parametrize("document_types", [("cover_letter",), ("tailored_resume", "cover_letter")])
def test_shared_template_and_frozen_sender_reach_letter_renderer_and_import(
    sessions, template_id, document_types,
) -> None:
    from datetime import datetime

    from test_generation_latex import _letter

    from app.services.generation_latex import build_cover_letter_tex

    _seed(sessions)
    draft = _generated_draft()
    draft["coverLetter"] = _letter().model_dump(mode="json", by_alias=True)
    draft["coverLetter"]["signature"] = "Model-invented name"
    if "tailored_resume" not in document_types:
        draft["resume"] = None
    backend = FakeBackend([_fit(), draft, _review(), _visual_review()])
    captured = []

    def renderer(bundle, *, resume_template_id, sender_basics, letter_date):
        assert bundle.cover_letter.signature == sender_basics.full_name
        captured.append((resume_template_id, sender_basics, letter_date))
        compiled = list(_renderer(bundle)) if bundle.resume else []
        compiled.append(CompiledDocument(
            document_type="cover_letter", engine="xelatex", file_name="letter.pdf",
            tex_source=build_cover_letter_tex(
                bundle.cover_letter, template_id=resume_template_id,
                sender_basics=sender_basics, letter_date=letter_date,
            ), pdf=b"%PDF-1.7\nfake", compile_log="ok",
        ))
        return tuple(compiled)

    workflow = GenerationWorkflow(settings=_settings(), backend=backend, renderer=renderer, verifier=_verifier)
    with sessions() as db:
        run = create_generation_run(
            db, application_id="application-1", settings=_settings(),
            request=_start().model_copy(update={
                "document_types": document_types,
                "formatting_parameters": {"cover_letter": {"templateId": template_id}},
            }),
        )
        profile = db.get(ProfileRecord, "default")
        frozen_name = profile.data["name"]
        frozen_email = profile.data["email"]
        update_profile_data(db, profile, data={**profile.data, "name": "Changed after start", "email": "changed@example.com"}, reason="edit_after_start")
        db.commit()
        workflow.evaluate_fit(db, run)
        workflow.respond_to_fit(db, run, continue_generation=True)
        assert run.status == "completed"
        assert len(captured) == 1
        selected, basics, letter_date = captured[0]
        assert selected == template_id
        assert basics.full_name == frozen_name
        assert basics.email == frozen_email
        assert letter_date == datetime.fromisoformat(run.input_snapshot["createdAt"]).date()
        artifacts = db.scalars(select(GenerationRunArtifactRecord).where(
            GenerationRunArtifactRecord.run_id == run.id,
            GenerationRunArtifactRecord.artifact_type.in_(("resume_pdf", "cover_letter_pdf")),
        )).all()
        assert len(artifacts) == len(document_types)
        assert {item.artifact_metadata["templateId"] for item in artifacts} == {template_id}
        templates = {item["documentType"]: item for item in run.input_snapshot["templates"]}
        for artifact in artifacts:
            assert artifact.artifact_metadata["templateSha256"] == templates[artifact.document_type]["contentSha256"]
    for request in backend.requests[2:]:
        context = json.loads(
            request.prompt.split("BEGIN UNTRUSTED APPLICATION DATA\n")[1].split("\nEND UNTRUSTED")[0]
        )
        assert context["documentLanguages"] == {
            document_type: "English" for document_type in document_types
        }
