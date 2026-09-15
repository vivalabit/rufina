import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pdfplumber
import pytest
from pypdf import PdfReader
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from test_generation_input import seed_complete_sources

from app.core.database import Base
from app.models.documents import (
    DocumentAttachmentRecord,
    DocumentFileRecord,
    DocumentRecord,
    DocumentVersionRecord,
)
from app.models.generation_runs import GenerationRunArtifactRecord, GenerationRunStartRequest
from app.models.generation_workflow import CoverLetterDraft, DraftBundle
from app.models.resume import FinalResume
from app.services import generation_latex
from app.services.generation_artifact_import import import_compiled_generation_documents
from app.services.generation_latex import (
    CompiledDocument,
    build_cover_letter_tex,
    build_resume_tex,
    compile_latex_document,
    latex_escape,
    render_generation_bundle,
)
from app.services.generation_store import create_generation_run


@pytest.fixture
def sessions() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        ai_backend_mode="openclaw_codex",
        openai_api_model="gpt-direct",
        openai_api_reasoning_effort="medium",
        openai_api_timeout_seconds=120,
        openai_api_max_attempts=2,
        openai_api_retry_backoff_seconds=0,
        openclaw_assistant_model="openai/gpt-worker",
        openclaw_assistant_thinking="high",
        openclaw_assistant_timeout_seconds=180,
        openclaw_assistant_max_attempts=1,
        openclaw_assistant_retry_backoff_seconds=0,
    )


def _start(key: str = "latex-run") -> GenerationRunStartRequest:
    return GenerationRunStartRequest(
        documentTypes=("tailored_resume",),
        language="English",
        formattingParameters={"tailored_resume": {"templateId": "classic_single"}},
        userPreferences="",
        idempotencyKey=key,
    )


def _resume() -> FinalResume:
    return FinalResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "tailored-1",
            "masterResumeId": "master-profile",
            "targetJobId": "vacancy-1",
            "language": "English",
            "basics": {
                "fullName": "Ada Lovelace",
                "headline": "R&D_100% Engineer",
                "email": "ada@example.com",
            },
            "summary": {
                "text": "Builds APIs & platforms.",
                "evidenceIds": ["source:one"],
            },
            "evidence": [
                {"id": "source:one", "type": "source", "text": "Builds APIs & platforms."}
            ],
            "sectionOrder": ["summary"],
        }
    )


def _letter() -> CoverLetterDraft:
    return CoverLetterDraft.model_validate(
        {
            "id": "letter-1",
            "targetJobId": "vacancy-1",
            "language": "English",
            "recipient": "Example AG",
            "subject": "Platform Engineer",
            "salutation": "Dear hiring team,",
            "paragraphs": [
                {"text": "I build reliable platforms.", "evidenceIds": ["source:one"]},
                {"text": "I would welcome a conversation.", "evidenceIds": []},
            ],
            "closing": "Kind regards,",
            "signature": "Ada Lovelace",
        }
    )


def _full_resume() -> FinalResume:
    data = _resume().model_dump(by_alias=True)
    data["basics"].update(
        phone="+41 44 555 0100",
        location="Zurich, Switzerland",
        workAuthorization="Swiss work permit",
        linkedin="https://example.com/ada",
        github="https://example.com/ada-code",
    )
    data.update(
        experiences=[{
            "id": "rewritten-1",
            "masterExperienceId": "experience-1",
            "title": "Platform Engineer",
            "company": "Northstar Labs",
            "location": "Zurich",
            "period": "2022 - Present",
            "bullets": [{
                "id": "experience-bullet-1",
                "text": "Built reliable data pipelines.",
                "evidenceIds": ["source:one"],
            }],
        }],
        skills=[
            {"id": "skill-1", "name": "Python", "category": "Data", "evidenceIds": ["source:one"]},
            {"id": "skill-2", "name": "SQL", "category": "Data", "evidenceIds": ["source:one"]},
            {"id": "skill-3", "name": "Mentoring", "category": "", "evidenceIds": ["source:one"]},
        ],
        education=[{
            "id": "education-1",
            "credential": "MSc",
            "fieldOfStudy": "Computer Science",
            "institution": "Example University",
            "location": "Bern",
            "startDate": "2018",
            "endDate": "2020",
            "details": [{
                "id": "education-detail-1",
                "text": "Thesis on dependable systems.",
                "evidenceIds": ["source:one"],
            }],
        }],
        projects=[{
            "id": "project-1",
            "name": "Open Metrics",
            "role": "Maintainer",
            "url": "https://example.com/metrics",
            "bullets": [{
                "id": "project-bullet-1",
                "text": "Created a reusable monitoring toolkit.",
                "evidenceIds": ["source:one"],
            }],
        }],
        certifications=[{
            "id": "certification-1",
            "name": "Cloud Foundations",
            "issuer": "Example Institute",
            "issuedOn": "2023-06",
            "evidenceIds": ["source:one"],
        }],
        languages=[{
            "id": "language-1",
            "name": "English",
            "proficiency": "Fluent",
            "evidenceIds": ["source:one"],
        }],
        additionalSections=[{
            "id": "additional-1",
            "title": "Community",
            "items": [{
                "id": "community-bullet-1",
                "text": "Volunteers at a local coding club.",
                "evidenceIds": ["source:one"],
            }],
        }],
        sectionOrder=[
            "summary", "experience", "education", "skills",
            "languages", "projects", "certifications", "additional",
        ],
    )
    return FinalResume.model_validate(data)


def test_latex_sources_escape_untrusted_values() -> None:
    assert latex_escape("A&B_100% #{x} \\") == (r"A\&B\_100\% \#\{x\} \textbackslash{}")
    resume_tex = build_resume_tex(_resume())
    letter_tex = build_cover_letter_tex(_letter())

    assert "APIs & platforms" not in resume_tex
    assert r"APIs \& platforms" in resume_tex
    assert r"\documentclass[]{cover}" in letter_tex
    assert "\\write18" not in resume_tex + letter_tex


def test_classic_template_preserves_all_resume_sections_and_groups_skills() -> None:
    resume = _full_resume()
    tex = build_resume_tex(resume, template_id="ishchenko_classic")

    for text in (
        resume.basics.full_name,
        resume.basics.headline,
        resume.basics.location,
        resume.basics.work_authorization,
        resume.basics.email,
        resume.basics.phone,
        resume.experiences[0].title,
        resume.experiences[0].company,
        resume.experiences[0].period,
        resume.experiences[0].bullets[0].text,
        resume.education[0].institution,
        resume.education[0].field_of_study,
        resume.education[0].start_date,
        resume.education[0].end_date,
        resume.education[0].details[0].text,
        resume.projects[0].name,
        resume.projects[0].role,
        resume.projects[0].url,
        resume.projects[0].bullets[0].text,
        resume.certifications[0].name,
        resume.certifications[0].issuer,
        resume.certifications[0].issued_on,
        resume.languages[0].name,
        resume.languages[0].proficiency,
        resume.additional_sections[0].title,
        resume.additional_sections[0].items[0].text,
        "Mentoring",
    ):
        assert latex_escape(text) in tex, f"Missing resume content: {text}"
    assert "Python, SQL" in tex
    assert tex.count("Data:") == 1
    ordered_content = [
        resume.summary.text, resume.experiences[0].title,
        resume.education[0].institution, "Python", resume.languages[0].name,
        resume.projects[0].name, resume.certifications[0].name,
        resume.additional_sections[0].title,
    ]
    positions = [tex.index(latex_escape(text)) for text in ordered_content]
    assert positions == sorted(positions)


@pytest.mark.parametrize("template_id", ["moderncv_banking", "ishchenko_classic"])
def test_both_templates_escape_tex_commands_in_resume_content(template_id: str) -> None:
    data = _full_resume().model_dump(by_alias=True)
    injection = r"R&D_100% #{x} \input{/etc/passwd} \write18{touch marker}"
    data["summary"]["text"] = injection
    data["experiences"][0]["title"] = injection
    data["projects"][0]["bullets"][0]["text"] = injection
    tex = build_resume_tex(FinalResume.model_validate(data), template_id=template_id)

    assert tex.count(latex_escape(injection)) == 3
    assert r"\input{" not in tex
    assert r"\write18{" not in tex


@pytest.mark.parametrize("url", [
    "javascript:alert(1)", "file:///etc/passwd", "data:text/html,example",
    "//example.com/profile", "https:///missing-host", "https://[invalid",
])
def test_classic_template_never_activates_non_web_or_malformed_links(url: str) -> None:
    data = _full_resume().model_dump(by_alias=True)
    data["basics"].update(linkedin=url, github="", portfolio="")
    data["projects"][0]["url"] = url
    tex = build_resume_tex(FinalResume.model_validate(data), template_id="ishchenko_classic")

    assert tex.count(latex_escape(url)) == 2
    assert r"\href{" not in tex


def test_classic_template_keeps_http_links_with_escaped_query_parameters() -> None:
    data = _full_resume().model_dump(by_alias=True)
    url = "https://example.com/profile?q=R&D_100%#work"
    data["basics"].update(linkedin=url, github="", portfolio="")
    tex = build_resume_tex(FinalResume.model_validate(data), template_id="ishchenko_classic")

    assert rf"\href{{{latex_escape(url)}}}" in tex
    assert url not in tex


def test_renderer_rejects_an_unsupported_template() -> None:
    with pytest.raises(ValueError, match="Unsupported generation resume template"):
        build_resume_tex(_resume(), template_id="unregistered-template")


def test_bundle_compiles_the_selected_cv_template_and_keeps_the_cover_letter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiled_sources: list[str] = []

    def runner(command, *, cwd, **_kwargs):
        workdir = Path(cwd)
        compiled_sources.append((workdir / "document.tex").read_text())
        (workdir / "document.pdf").write_bytes(b"%PDF-1.7\ncompiled")
        return subprocess.CompletedProcess(command, 0, stdout="compiled", stderr="")

    monkeypatch.setattr(generation_latex.shutil, "which", lambda name: f"/usr/bin/{name}")
    bundle = DraftBundle(resume=_full_resume(), coverLetter=_letter())
    documents = render_generation_bundle(
        bundle, resume_template_id="ishchenko_classic", runner=runner,
    )

    expected_cv = build_resume_tex(bundle.resume, template_id="ishchenko_classic")
    expected_letter = build_cover_letter_tex(bundle.cover_letter)
    assert compiled_sources == [expected_cv, expected_cv, expected_letter, expected_letter]
    assert [(document.document_type, document.tex_source) for document in documents] == [
        ("tailored_resume", expected_cv), ("cover_letter", expected_letter),
    ]
    assert expected_cv != build_resume_tex(bundle.resume, template_id="moderncv_banking")


def test_compiler_uses_no_shell_escape_and_copies_versioned_cover_assets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    def runner(command, *, cwd, **_kwargs):
        commands.append(command)
        workdir = Path(cwd)
        assert (workdir / "cover.cls").is_file()
        assert (workdir / "OpenFonts" / "fonts" / "lato" / "Lato-Lig.ttf").is_file()
        (workdir / "document.pdf").write_bytes(b"%PDF-1.7\ncompiled")
        return subprocess.CompletedProcess(command, 0, stdout="compiled", stderr="")

    monkeypatch.setattr(generation_latex.shutil, "which", lambda name: f"/usr/bin/{name}")
    result = compile_latex_document(
        document_type="cover_letter",
        engine="xelatex",
        file_name="letter.pdf",
        tex_source=build_cover_letter_tex(_letter()),
        runner=runner,
        include_cover_assets=True,
    )

    assert result.pdf.startswith(b"%PDF-")
    assert len(commands) == 2
    assert "-no-shell-escape" in commands[0]


@pytest.mark.parametrize("template_id", ["moderncv_banking", "ishchenko_classic"])
def test_real_compilers_produce_readable_resume_and_cover_letter_pdfs(template_id: str) -> None:
    if not shutil.which("lualatex") or not shutil.which("xelatex"):
        pytest.skip("The local host does not provide the Docker TeX toolchain")

    compiled = render_generation_bundle(
        DraftBundle(resume=_full_resume(), coverLetter=_letter()),
        resume_template_id=template_id,
    )

    assert {document.document_type for document in compiled} == {
        "tailored_resume",
        "cover_letter",
    }
    assert {document.engine for document in compiled} == {"lualatex", "xelatex"}
    for document in compiled:
        assert document.pdf.startswith(b"%PDF-")
        assert len(PdfReader(BytesIO(document.pdf)).pages) >= 1
        with pdfplumber.open(BytesIO(document.pdf)) as pdf:
            for page in pdf.pages:
                for char in page.chars:
                    if char["text"].strip():
                        assert -1 <= char["x0"] <= char["x1"] <= page.width + 1
                        assert -1 <= char["top"] <= char["bottom"] <= page.height + 1
        text = " ".join(" ".join(
            page.extract_text() or "" for page in PdfReader(BytesIO(document.pdf)).pages
        ).split())
        assert "Ada Lovelace" in text
        if document.document_type == "tailored_resume":
            for expected in (
                "Northstar Labs", "Platform Engineer", "2022", "Present",
                "Python", "SQL", "Mentoring", "Example University", "2018", "2020",
                "English", "Fluent", "Open Metrics", "Cloud Foundations",
                "local coding club",
            ):
                assert expected in text
            if template_id == "ishchenko_classic":
                for expected in (
                    "R&D_100% Engineer", "Swiss work permit",
                    "Thesis on dependable systems.", "Maintainer", "2023-06",
                ):
                    assert expected in text
        else:
            assert "I build reliable platforms." in text


def test_compiled_pdf_is_imported_once_and_attached_to_application(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    bundle = DraftBundle(resume=_resume())
    compiled = (
        CompiledDocument(
            document_type="tailored_resume",
            engine="lualatex",
            file_name="cv.pdf",
            tex_source=build_resume_tex(_resume()),
            pdf=b"%PDF-1.7\ncompiled",
            compile_log="ok",
        ),
    )
    with sessions() as db:
        run = create_generation_run(
            db,
            application_id="application-1",
            request=_start(),
            settings=_settings(),
        )
        first = import_compiled_generation_documents(db, run=run, bundle=bundle, compiled=compiled)
        db.commit()
        second = import_compiled_generation_documents(db, run=run, bundle=bundle, compiled=compiled)
        db.commit()

        assert first[0].id == second[0].id
        assert db.scalar(select(func.count()).select_from(GenerationRunArtifactRecord)) == 2
        attachment = db.scalar(select(DocumentAttachmentRecord))
        file = db.scalar(select(DocumentFileRecord))
        assert attachment is not None and attachment.application_id == "application-1"
        assert file is not None and file.content_type == "application/pdf"
        assert file.content == compiled[0].pdf


def test_a_later_run_creates_a_new_version_of_the_attached_document(
    sessions: sessionmaker[Session],
) -> None:
    seed_complete_sources(sessions)
    bundle = DraftBundle(resume=_resume())
    compiled = (
        CompiledDocument(
            document_type="tailored_resume",
            engine="lualatex",
            file_name="cv.pdf",
            tex_source=build_resume_tex(_resume()),
            pdf=b"%PDF-1.7\nfirst",
            compile_log="ok",
        ),
    )
    with sessions() as db:
        first_run = create_generation_run(
            db,
            application_id="application-1",
            request=_start("first-run"),
            settings=_settings(),
        )
        first_document = import_compiled_generation_documents(
            db, run=first_run, bundle=bundle, compiled=compiled
        )[0]
        first_run.status = "completed"
        first_run.stage = "final_review"
        db.commit()

        second_run = create_generation_run(
            db,
            application_id="application-1",
            request=_start("revision-run"),
            settings=_settings(),
        )
        revised = (
            compiled[0].__class__(
                document_type=compiled[0].document_type,
                engine=compiled[0].engine,
                file_name=compiled[0].file_name,
                tex_source=compiled[0].tex_source,
                pdf=b"%PDF-1.7\nrevised",
                compile_log="ok",
            ),
        )
        second_document = import_compiled_generation_documents(
            db, run=second_run, bundle=bundle, compiled=revised
        )[0]
        db.commit()

        assert second_document.id == first_document.id
        assert second_document.current_version == 2
        assert db.scalar(select(func.count()).select_from(DocumentRecord)) == 1
        assert db.scalar(select(func.count()).select_from(DocumentVersionRecord)) == 2
        assert db.scalar(select(func.count()).select_from(DocumentFileRecord)) == 2
        final_artifact = db.scalar(
            select(GenerationRunArtifactRecord).where(
                GenerationRunArtifactRecord.run_id == second_run.id,
                GenerationRunArtifactRecord.artifact_type == "resume_pdf",
            )
        )
        assert final_artifact is not None and final_artifact.document_version == 2
