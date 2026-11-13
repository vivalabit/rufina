from __future__ import annotations

from datetime import date

import pytest

from app.models.generation_workflow import DraftBundle
from app.models.resume import MasterResume
from app.services.ats.cover_letter import letter_salutation, letter_subject
from app.services.ats.job_target import VacancyInput, extract_job_target_without_model
from app.services.ats.planner import build_tailoring_plan, coverage_score, plan_headline
from app.services.ats.profile_index import (
    build_profile_index,
    parse_profile_date,
    split_statement_texts,
)
from app.services.ats.skill_dictionary import default_skill_dictionary
from app.services.ats.tailoring import (
    ModelResponse,
    TailoringError,
    TailoringSession,
    VacancyContext,
)
from app.services.ats.wording import check_statement, number_tokens
from app.services.generation_grounding import validate_grounded_bundle
from tests.tailoring_fixtures import VACANCY_TEXT, master_resume, master_resume_payload

TODAY = date(2026, 11, 1)
TITLE = "Backend Engineer (Python) 80-100%"


def _target():
    return extract_job_target_without_model(VacancyInput(title=TITLE, description=VACANCY_TEXT))


def _vacancy() -> VacancyContext:
    return VacancyContext(
        job_id="job-1",
        title=TITLE,
        company="Northwind Analytics AG",
        location="Zurich",
        text=VACANCY_TEXT,
    )


def _session(document_types=("tailored_resume",), **overrides) -> TailoringSession:
    return TailoringSession(
        **{
            "master": master_resume(),
            "target": _target(),
            "vacancy": _vacancy(),
            "document_types": document_types,
            "today": TODAY,
            **overrides,
        }
    )


def _echo_wording(session: TailoringSession, request, *, changes=None, summary=""):
    """A model that returns each statement unchanged unless `changes` rewrites it."""
    changes = changes or {}
    statements = {item.statement.id: item.statement.text for item in session.plan.statements}
    return ModelResponse(
        data={
            "summary": summary,
            "statements": [
                {"id": item, "text": changes.get(item, statements[item]), "emphasis": []}
                for item in request.statement_ids
            ],
        }
    )


# --- Profile index ------------------------------------------------------------


def test_profile_dates_are_parsed_at_month_precision() -> None:
    assert parse_profile_date("06/2025") == date(2025, 6, 1)
    assert parse_profile_date("2024", end=True) == date(2024, 12, 1)
    assert parse_profile_date("März 2023") == date(2023, 3, 1)
    assert parse_profile_date("soon") is None


def test_a_bullet_holding_a_list_is_split_into_statements() -> None:
    assert split_statement_texts("- Built the API\n- Wrote the tests") == [
        "Built the API",
        "Wrote the tests",
    ]
    assert split_statement_texts("One plain statement.") == ["One plain statement."]


def test_skill_depth_counts_role_months_and_ignores_skills_only_listed() -> None:
    index = build_profile_index(master_resume(), today=TODAY)

    # Python is in the stack of both roles: 09/2024-05/2025 and 06/2025-11/2026.
    assert index.skills["python"].months == 27
    assert index.skills["python"].last_used == date(2026, 11, 1)
    assert index.skills["kubernetes"].experience_ids == ("role-atlas",)
    # TypeScript is listed under Skills but was never used in a role.
    assert index.skills["typescript"].months == 0
    assert index.skills["typescript"].in_skills_section
    assert index.total_months == 27


# --- Planner ------------------------------------------------------------------


def test_plan_keeps_every_statement_and_drops_unrelated_ones_first() -> None:
    master = master_resume()
    plan = build_tailoring_plan(master, build_profile_index(master, today=TODAY), _target())

    assert [item.experience_id for item in plan.experiences] == ["role-atlas", "role-borealis"]
    # Statements are ordered by their value for the vacancy inside each role.
    assert [item.statement.id for item in plan.experiences[0].statements] == [
        "role-atlas-bullet-1",
        "role-atlas-bullet-2",
        "role-atlas-bullet-3",
        "role-atlas-bullet-4",
    ]
    assert plan.excluded_statement_ids == ()
    # Under page pressure the statements without a link to the vacancy go first.
    assert set(plan.drop_order[:3]) == {
        "role-borealis-bullet-3",
        "role-borealis-bullet-2",
        "role-atlas-bullet-4",
    }
    # The best statement of each role is never dropped for page fitting.
    assert "role-atlas-bullet-1" not in plan.drop_order
    assert "role-borealis-bullet-1" not in plan.drop_order


def test_a_role_with_many_statements_keeps_its_most_valuable_ones() -> None:
    master = master_resume(extra_bullets_per_role=8)
    plan = build_tailoring_plan(master, build_profile_index(master, today=TODAY), _target())

    assert [len(item.statements) for item in plan.experiences] == [8, 8]
    assert len(plan.excluded_statement_ids) == 4 + 3
    assert "role-atlas-bullet-1" in {item.statement.id for item in plan.statements}


def test_plan_reports_gaps_only_for_skills_the_profile_lacks() -> None:
    master = master_resume()
    plan = build_tailoring_plan(master, build_profile_index(master, today=TODAY), _target())
    support = {match.label: match.support for match in plan.matches}

    assert support["FastAPI"] == "experience"
    assert support["AWS"] == "profile"
    assert support["Terraform"] == "gap"
    assert "Kafka" not in {match.label for match in plan.gaps}  # preferred, not required


def test_headline_adopts_the_vacancy_title_without_unearned_seniority() -> None:
    master = master_resume()
    index = build_profile_index(master, today=TODAY)
    target = extract_job_target_without_model(
        VacancyInput(title="Senior Backend Engineer", description=VACANCY_TEXT)
    )
    plan = build_tailoring_plan(master, index, target)

    assert plan.headline == "Backend Engineer | Python, FastAPI, PostgreSQL"
    assert plan_headline(master, target, ()) == "Backend Engineer"
    # Workload and bracketed additions of the posting title never reach the headline.
    assert plan_headline(master, _target(), ()) == "Backend Engineer"


def test_coverage_prefers_experience_over_the_skills_list() -> None:
    target = _target()
    in_experience = coverage_score(
        target, experience_text="Built services with FastAPI and PostgreSQL.", skills_text=""
    )
    in_skills = coverage_score(target, experience_text="", skills_text="FastAPI, PostgreSQL")

    assert in_experience.score > in_skills.score > 0


# --- Fact guard ---------------------------------------------------------------

SOURCE = "Cut report generation time by 40% by rebuilding the export service in Python."


@pytest.mark.parametrize(
    ("text", "issue"),
    [
        ("Cut report generation time by 60% by rebuilding the export service in Python.", "number"),
        ("Cut report generation time by 40% by rebuilding the export service in Go and Kafka.",
         "technolog"),
        ("Cut report generation time by 40% for 12 teams with the AcmeFlow platform.", "new"),
        ("Cut report generation time by 40% at Borealis Shop AG.", "employer"),
    ],
)
def test_guard_rejects_facts_that_the_source_does_not_contain(text: str, issue: str) -> None:
    result = check_statement(
        text,
        source=SOURCE,
        other_employers=["Borealis Shop AG"],
        dictionary=default_skill_dictionary(),
    )

    assert not result.ok
    assert any(issue in item for item in result.issues)


def test_guard_accepts_a_rephrasing_and_a_planned_vacancy_term() -> None:
    dictionary = default_skill_dictionary()
    assert check_statement(
        "Rebuilt the export service in Python, cutting report generation time by 40%.",
        source=SOURCE,
        dictionary=dictionary,
    ).ok
    assert check_statement(
        "Built Postgres-backed reporting.",
        source="Built PostgreSQL-backed reporting.",
        terms=["Postgres"],
        dictionary=dictionary,
    ).ok
    assert number_tokens("5'000 and 5,000 and 5000") == {"5000"}


# --- Session ------------------------------------------------------------------


def test_session_assembles_a_grounded_resume_from_accepted_wording() -> None:
    session = _session()
    requests = session.first_round()
    assert [request.kind for request in requests] == ["wording"]
    rewritten = "Rebuilt the export service in Python with FastAPI and PostgreSQL, cutting " \
        "report generation time by 40%."
    session.apply(
        requests,
        [
            _echo_wording(
                session,
                requests[0],
                changes={"role-atlas-bullet-1": rewritten},
                summary="Backend developer building Python services and data pipelines.",
            )
        ],
    )
    assert session.retry_round() == []
    result = session.finish()

    resume = result.resume
    assert resume is not None
    assert [item.master_experience_id for item in resume.experiences] == [
        "role-atlas",
        "role-borealis",
    ]
    assert resume.experiences[0].period == "06/2025 – Present"
    bullets = {bullet.id: bullet for item in resume.experiences for bullet in item.bullets}
    assert bullets["role-atlas-bullet-1"].text == rewritten
    assert bullets["role-atlas-bullet-1"].evidence_ids == ["profile:role-atlas-achievement-1"]
    assert resume.languages == session.master.languages
    assert {skill.name for skill in resume.skills} == {skill.name for skill in session.master.skills}
    # The same rules the previous pipeline enforced on model output still hold.
    validate_grounded_bundle(
        DraftBundle(resume=resume), master_resume=session.master, target_job_id="job-1"
    )
    assert result.report["statements"]["reworded"] == 1
    assert result.report["score"]["after"] >= result.report["score"]["before"]
    assert {"label": "Terraform", "importance": "preferred"} in result.report["gaps"]


def _master_with_concepts(names: list[str]) -> MasterResume:
    payload = master_resume_payload()
    for index, name in enumerate(names, start=1):
        evidence_id = f"source:concept-{index}"
        payload["evidence"].append({"id": evidence_id, "type": "source", "text": name})
        payload["skills"].append(
            {"id": f"concept-{index}", "name": name, "category": "", "evidenceIds": [evidence_id]}
        )
    return MasterResume.model_validate(payload)


def test_skills_list_concepts_only_when_the_vacancy_asks_and_the_resume_does_not_show_them(
) -> None:
    session = _session(
        master=_master_with_concepts(
            ["LLM", "Large Language Models", "Data Engineering", "JWT", "Microservices"]
        )
    )
    requests = session.first_round()
    session.apply(
        requests,
        [
            _echo_wording(
                session,
                requests[0],
                summary="Backend developer who builds Python services and data pipelines.",
            )
        ],
    )
    resume = session.finish().resume
    assert resume is not None

    names = [skill.name for skill in resume.skills]
    # Every technology stays; of the concepts only the vacancy's LLM requirement is
    # listed, once, because nothing else in the resume shows it. Data pipelines are
    # already in the summary; JWT and Microservices are not asked for.
    assert [skill.name for skill in resume.skills if skill.category] == [
        skill.name for skill in session.master.skills if skill.category
    ]
    assert [skill.name for skill in resume.skills if not skill.category] == ["LLM"]
    assert "Microservices" not in names
    validate_grounded_bundle(
        DraftBundle(resume=resume), master_resume=session.master, target_job_id="job-1"
    )


def test_rejected_statement_is_retried_once_and_then_keeps_the_profile_wording() -> None:
    session = _session()
    requests = session.first_round()
    invented = {"role-atlas-bullet-2": "Processed 9 TB of retail data per month with Kafka."}
    session.apply(requests, [_echo_wording(session, requests[0], changes=invented, summary="")])

    retry = session.retry_round()
    assert len(retry) == 1
    assert "role-atlas-bullet-2" in retry[0].statement_ids
    assert "previousAttemptRejectedBecause" in retry[0].prompt
    session.apply(retry, [_echo_wording(session, retry[0], changes=invented)])
    result = session.finish()

    bullets = {bullet.id: bullet.text for item in result.resume.experiences for bullet in item.bullets}
    assert bullets["role-atlas-bullet-2"].startswith("Processed 2 TB of retail data")
    assert result.report["keptOriginal"][0]["id"] == "role-atlas-bullet-2"
    assert result.warnings
    # Without an accepted model summary the profile's own summary stays.
    assert result.resume.summary.text == session.master.summary.text


def test_session_fails_only_when_no_wording_came_back_at_all() -> None:
    session = _session()
    requests = session.first_round()
    session.apply(requests, [ModelResponse(error="timeout")])
    retry = session.retry_round()
    session.apply(retry, [ModelResponse(error="timeout")])

    with pytest.raises(TailoringError) as failure:
        session.finish()
    assert failure.value.code == "wording_failed"
    assert failure.value.retryable


def test_german_vacancy_switches_the_document_language_and_period_label() -> None:
    target = extract_job_target_without_model(
        VacancyInput(
            title="Backend Entwickler Python",
            description=(
                "Wir suchen eine Person für die Entwicklung unserer Python Services mit "
                "FastAPI und PostgreSQL. Sie arbeiten mit Docker und Kubernetes und "
                "bringen Erfahrung in der Softwareentwicklung mit."
            ),
        )
    )
    session = TailoringSession(
        master=master_resume(),
        target=target,
        vacancy=_vacancy(),
        document_types=("tailored_resume",),
        today=TODAY,
    )
    requests = session.first_round()
    assert "Write in German" in requests[0].prompt
    session.apply(requests, [_echo_wording(session, requests[0])])
    resume = session.finish().resume

    assert resume.language == "de"
    assert resume.experiences[0].period == "06/2025 – heute"
    validate_grounded_bundle(
        DraftBundle(resume=resume), master_resume=session.master, target_job_id="job-1"
    )


# --- Cover letter -------------------------------------------------------------


def _letter_response(paragraphs):
    return ModelResponse(data={"contact_name": "", "paragraphs": paragraphs})


def test_cover_letter_is_built_by_code_around_checked_paragraphs() -> None:
    session = _session(("tailored_resume", "cover_letter"))
    requests = session.first_round()
    assert [request.kind for request in requests] == ["wording", "cover_letter"]
    session.apply(
        requests,
        [
            _echo_wording(session, requests[0]),
            _letter_response(
                [
                    {"text": "Your Backend Engineer role at Northwind Analytics AG matches the "
                     "Python services I build today.", "statement_ids": []},
                    {"text": "At Atlas Data GmbH I cut report generation time by 40% by "
                     "rebuilding the export service in Python with FastAPI and PostgreSQL.",
                     "statement_ids": ["role-atlas-bullet-1"]},
                    {"text": "I would welcome a conversation about your data platform.",
                     "statement_ids": []},
                ]
            ),
        ],
    )
    result = session.finish()

    letter = result.cover_letter
    assert letter is not None
    assert letter.subject == "Application for Backend Engineer (Python)"
    assert letter.salutation == "Dear Hiring Team,"
    assert letter.recipient == "Northwind Analytics AG\nZurich"
    assert letter.signature == "Mira Keller"
    assert letter.paragraphs[1].evidence_ids == ("profile:role-atlas-achievement-1",)


def test_cover_letter_with_an_invented_claim_is_dropped_but_the_resume_is_delivered() -> None:
    session = _session(("tailored_resume", "cover_letter"))
    bad = _letter_response(
        [
            {"text": "I have led Terraform migrations for 50 teams.", "statement_ids": []},
            {"text": "I would welcome a conversation.", "statement_ids": []},
        ]
    )
    requests = session.first_round()
    session.apply(requests, [_echo_wording(session, requests[0]), bad])
    retry = session.retry_round()
    assert [request.label for request in retry] == ["wording-retry", "cover-letter-retry"] or [
        request.label for request in retry
    ] == ["cover-letter-retry"]
    session.apply(
        retry,
        [bad if request.kind == "cover_letter" else _echo_wording(session, request)
         for request in retry],
    )
    result = session.finish()

    assert result.resume is not None
    assert result.cover_letter is None
    assert result.report["coverLetterIssues"]
    assert any("cover letter" in warning for warning in result.warnings)


def test_salutation_names_a_person_only_when_the_posting_does() -> None:
    posting = "Questions? Contact Anna Muster, Head of Engineering."
    assert letter_salutation("Anna Muster", vacancy_text=posting, language="de") == (
        "Guten Tag Anna Muster"
    )
    assert letter_salutation("John Doe", vacancy_text=posting, language="en") == "Dear Hiring Team,"
    assert letter_subject("  Data   Engineer ", "de") == "Bewerbung als Data Engineer"


def test_knockouts_are_checked_against_experience_and_language_levels() -> None:
    target = extract_job_target_without_model(
        VacancyInput(title=TITLE, description=VACANCY_TEXT)
    )
    session = _session()
    by_kind = {item["kind"]: item for item in session.report(None)["knockouts"]}

    assert target.knockouts
    assert by_kind["experience"]["met"] is True
    assert by_kind["experience"]["detail"] == "Profile: 2 years 3 months"


def test_profile_language_level_reads_cefr_and_wording() -> None:
    from app.services.ats.tailoring import profile_language_level

    master = master_resume()
    assert profile_language_level(master, "en") == "C1"
    assert profile_language_level(master, "de") == "B1"
    assert profile_language_level(master, "fr") is None
