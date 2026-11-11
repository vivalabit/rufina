from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.generation_workflow import DraftBundle, GeneratedDraftBundle
from app.models.resume import FinalResume, MasterResume
from app.services.generation_grounding import (
    GenerationGroundingError,
    ground_generated_bundle,
    validate_grounded_bundle,
)
from app.services.generation_workflow import (
    GenerationWorkflowError,
    _require_requested_documents,
)


def _generated_payload() -> dict:
    return {
        "resume": {
            "id": "tailored-1",
            "masterResumeId": "master-1",
            "targetJobId": "job-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace"},
            "summary": {"text": "Builds reliable platforms.", "evidenceIds": ["source:summary"]},
            "experiences": [
                {
                    "id": "rewritten-alpha",
                    "masterExperienceId": "role-alpha",
                    "company": "Alpha AG",
                    "title": "Engineer",
                    "period": "Jan 2022–Present",
                    "bullets": [
                        {
                            "id": "rewritten-alpha-bullet",
                            "text": "Built reliable APIs.",
                            "evidenceIds": ["profile:alpha", "source:summary"],
                        }
                    ],
                },
                {
                    "id": "rewritten-beta",
                    "masterExperienceId": "role-beta",
                    "company": "Beta AG",
                    "title": "Developer",
                    "period": "Jan 2020–Dec 2021",
                    "bullets": [
                        {
                            "id": "rewritten-beta-bullet",
                            "text": "Maintained search services.",
                            "evidenceIds": ["profile:beta"],
                        }
                    ],
                },
            ],
            "skills": [
                {"id": "skill-python", "name": "Python", "category": "Languages", "evidenceIds": ["source:skill"]}
            ],
            "education": [
                {
                    "id": "education-1",
                    "institution": "Example University",
                    "credential": "BSc",
                    "details": [
                        {
                            "id": "education-detail",
                            "text": "Computer science.",
                            "evidenceIds": ["source:education"],
                        }
                    ],
                }
            ],
            "projects": [
                {
                    "id": "project-1",
                    "name": "API platform",
                    "bullets": [
                        {
                            "id": "project-bullet",
                            "text": "Designed an API platform.",
                            "evidenceIds": ["source:project"],
                        }
                    ],
                }
            ],
            "certifications": [
                {
                    "id": "cert-1",
                    "name": "Cloud certification",
                    "issuer": "Cloud vendor",
                    "evidenceIds": ["source:certification"],
                }
            ],
            "languages": [
                {
                    "id": "language-1",
                    "name": "English",
                    "proficiency": "Fluent",
                    "evidenceIds": ["source:language"],
                }
            ],
            "additionalSections": [
                {
                    "id": "additional-1",
                    "title": "Volunteering",
                    "items": [
                        {
                            "id": "volunteer-bullet",
                            "text": "Mentored students.",
                            "evidenceIds": ["source:additional"],
                        }
                    ],
                }
            ],
            "sectionOrder": [
                "summary",
                "experience",
                "skills",
                "education",
                "projects",
                "certifications",
                "languages",
                "additional",
            ],
        },
        "coverLetter": {
            "id": "letter-1",
            "targetJobId": "job-1",
            "language": "English",
            "recipient": "Hiring team",
            "subject": "Engineer application",
            "salutation": "Dear hiring team,",
            "paragraphs": [
                {
                    "text": "My platform work is relevant to your team.",
                    "evidenceIds": ["source:letter-only"],
                },
                {"text": "I would welcome a conversation.", "evidenceIds": []},
            ],
            "closing": "Kind regards,",
            "signature": "Ada Lovelace",
        },
    }


def _master() -> MasterResume:
    resume = deepcopy(_generated_payload()["resume"])
    resume.pop("masterResumeId")
    resume.pop("targetJobId")
    resume["id"] = "master-1"
    resume["summary"]["text"] = (
        "Builds reliable platforms using detailed delivery and operational experience. " * 12
    )
    resume["experiences"] = [
        {
            "id": "role-alpha",
            "company": "Alpha AG",
            "title": "Engineer",
            "startDate": "2022-01",
            "isCurrent": True,
            "bullets": [
                {
                    "id": "alpha-bullet",
                    "text": "Built reliable APIs and documented their operational design.",
                    "evidenceIds": ["profile:alpha"],
                }
            ],
        },
        {
            "id": "role-beta",
            "company": "Beta AG",
            "title": "Developer",
            "startDate": "2020-01",
            "endDate": "2021-12",
            "bullets": [
                {
                    "id": "beta-bullet",
                    "text": "Maintained search services.",
                    "evidenceIds": ["profile:beta"],
                }
            ],
        },
    ]
    resume["evidence"] = [
        {"id": f"source:{key}", "type": "source", "text": text, "sourceId": "retained-cv"}
        for key, text in [
            ("summary", resume["summary"]["text"]),
            ("skill", "Python"),
            ("education", "Computer science BSc, Example University."),
            ("project", "Designed an API platform."),
            ("certification", "Cloud certification"),
            ("language", "Fluent English"),
            ("additional", "Mentored students."),
            ("letter-only", "Platform work relevant to the employer's engineering tasks."),
            ("unused", "An unrelated historical detail omitted from this application."),
        ]
    ] + [
        {
            "id": f"profile:{key}",
            "type": "profile",
            "text": text,
            "claimType": "achievement",
            "experienceId": f"role-{key}",
        }
        for key, text in [
            ("alpha", "Built reliable APIs and documented their operational design."),
            ("beta", "Maintained search services."),
        ]
    ]
    return MasterResume.model_validate(resume)


def test_model_response_schema_uses_references_without_an_evidence_catalog() -> None:
    schema = GeneratedDraftBundle.model_json_schema()
    for definition in schema.get("$defs", {}).values():
        assert "evidence" not in definition.get("properties", {})
    assert "ResumeEvidence" not in schema.get("$defs", {})
    assert "evidence" in FinalResume.model_json_schema()["properties"]

    payload = _generated_payload()
    payload["resume"]["evidence"] = []
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GeneratedDraftBundle.model_validate(payload)


def test_server_assembles_only_referenced_canonical_evidence_from_all_sections() -> None:
    master = _master()
    original = master.model_dump(mode="json", by_alias=True)
    generated = GeneratedDraftBundle.model_validate(_generated_payload())

    bundle = ground_generated_bundle(generated, master_resume=master, target_job_id="job-1")

    assert isinstance(bundle, DraftBundle)
    assert isinstance(bundle.resume, FinalResume)
    expected_ids = {
        "source:summary",
        "profile:alpha",
        "profile:beta",
        "source:skill",
        "source:education",
        "source:project",
        "source:certification",
        "source:language",
        "source:additional",
    }
    assert {item.id for item in bundle.resume.evidence} == expected_ids
    assert len(bundle.resume.evidence) == len(expected_ids)
    canonical = {item.id: item for item in master.evidence}
    assert all(item == canonical[item.id] for item in bundle.resume.evidence)
    assert all(item is not canonical[item.id] for item in bundle.resume.evidence)
    assert [item.id for item in bundle.resume.evidence] == [
        item.id for item in master.evidence if item.id in expected_ids
    ]
    assert bundle.cover_letter == generated.cover_letter
    assert bundle.resume.summary.text == "Builds reliable platforms."
    assert len(bundle.resume.summary.text) < len(master.summary.text)
    assert len(bundle.resume.experiences) == len(master.experiences)
    assert canonical["source:summary"].text == next(
        item.text for item in bundle.resume.evidence if item.id == "source:summary"
    )
    assert "evidence" not in generated.resume.model_dump()
    assert DraftBundle.model_validate(bundle.model_dump(mode="json", by_alias=True)) == bundle

    bundle.resume.evidence.clear()
    assert master.model_dump(mode="json", by_alias=True) == original


@pytest.mark.parametrize(
    "path",
    [
        ("summary",),
        ("experiences", 0, "bullets", 0),
        ("skills", 0),
        ("education", 0, "details", 0),
        ("projects", 0, "bullets", 0),
        ("certifications", 0),
        ("languages", 0),
        ("additionalSections", 0, "items", 0),
    ],
)
def test_unknown_resume_reference_is_rejected_in_every_section(path: tuple) -> None:
    payload = _generated_payload()
    item = payload["resume"]
    for key in path:
        item = item[key]
    item["evidenceIds"] = ["source:missing"]

    with pytest.raises(GenerationGroundingError, match="unknown evidence"):
        ground_generated_bundle(
            GeneratedDraftBundle.model_validate(payload),
            master_resume=_master(),
            target_job_id="job-1",
        )


def test_cover_letter_only_is_supported_and_unknown_references_are_rejected() -> None:
    payload = _generated_payload()
    payload["resume"] = None
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=_master(), target_job_id="job-1"
    )
    assert bundle.resume is None
    assert bundle.cover_letter.paragraphs[0].evidence_ids == ("source:letter-only",)

    payload["coverLetter"]["paragraphs"][0]["evidenceIds"] = ["source:missing"]
    with pytest.raises(GenerationGroundingError, match="unknown evidence"):
        ground_generated_bundle(
            GeneratedDraftBundle.model_validate(payload),
            master_resume=_master(),
            target_job_id="job-1",
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("company", "Another AG", "protected employer or title"),
        ("title", "Director", "protected employer or title"),
        ("period", "Jan 2021–Present", "protected role dates"),
        ("masterExperienceId", "role-missing", "unknown experience"),
    ],
)
def test_server_grounding_preserves_experience_guards(field: str, value: str, error: str) -> None:
    payload = _generated_payload()
    payload["resume"]["experiences"][0][field] = value
    with pytest.raises(GenerationGroundingError, match=error):
        ground_generated_bundle(
            GeneratedDraftBundle.model_validate(payload),
            master_resume=_master(),
            target_job_id="job-1",
        )


def test_server_grounding_rejects_reassignment_of_another_employers_fact() -> None:
    payload = _generated_payload()
    payload["resume"]["experiences"][0]["bullets"][0]["evidenceIds"] = ["profile:beta"]
    with pytest.raises(GenerationGroundingError, match="another employer"):
        ground_generated_bundle(
            GeneratedDraftBundle.model_validate(payload),
            master_resume=_master(),
            target_job_id="job-1",
        )


@pytest.mark.parametrize(
    ("document", "field", "value", "error"),
    [
        ("resume", "masterResumeId", "another-master", "wrong source snapshot"),
        ("resume", "targetJobId", "another-job", "wrong source snapshot"),
        ("coverLetter", "targetJobId", "another-job", "wrong vacancy"),
    ],
)
def test_server_grounding_rejects_wrong_source_or_vacancy(
    document: str, field: str, value: str, error: str
) -> None:
    payload = _generated_payload()
    payload[document][field] = value
    with pytest.raises(GenerationGroundingError, match=error):
        ground_generated_bundle(
            GeneratedDraftBundle.model_validate(payload),
            master_resume=_master(),
            target_job_id="job-1",
        )


def test_generated_bundle_requires_at_least_one_document() -> None:
    with pytest.raises(ValidationError, match="at least one document"):
        GeneratedDraftBundle.model_validate({"resume": None, "coverLetter": None})


@pytest.mark.parametrize(
    ("missing", "requested", "code"),
    [
        ("resume", "tailored_resume", "missing_resume_draft"),
        ("coverLetter", "cover_letter", "missing_cover_letter_draft"),
    ],
)
def test_materialized_bundle_does_not_mask_a_missing_requested_document(
    missing: str, requested: str, code: str
) -> None:
    payload = _generated_payload()
    payload[missing] = None
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=_master(), target_job_id="job-1"
    )
    with pytest.raises(GenerationWorkflowError) as error:
        _require_requested_documents(bundle, [requested])
    assert error.value.code == code


def _master_with_broader_skills_and_native_languages() -> MasterResume:
    data = _master().model_dump(mode="json", by_alias=True)
    for index, name in enumerate(("Ukrainian", "Russian")):
        evidence_id = f"source:native-{index}"
        data["languages"].append(
            {"id": f"native-{index}", "name": name, "proficiency": "Native", "evidenceIds": [evidence_id]}
        )
        data["evidence"].append({"id": evidence_id, "type": "source", "text": f"{name}: Native"})
    for index, (name, category) in enumerate(
        (
            ("Django", "Frameworks"), ("FastAPI", "Frameworks"),
            ("Go", "Languages"), ("Pytest", "Tools / DevOps"),
            ("PostgreSQL", "Databases"), ("Redis", "Databases"),
        )
    ):
        evidence_id = f"source:foundation-{index}"
        data["skills"].append(
            {"id": f"foundation-{index}", "name": name, "category": category, "evidenceIds": [evidence_id]}
        )
        data["evidence"].append({"id": evidence_id, "type": "source", "text": name})
    return MasterResume.model_validate(data)


def test_preservation_survives_author_selection_and_a_later_pdf_repair() -> None:
    master = _master_with_broader_skills_and_native_languages()
    payload = _generated_payload()
    # The profile's order, not inferred date order or model relevance, is authoritative.
    master.experiences.reverse()
    source_before = master.model_dump(mode="json", by_alias=True)
    payload["resume"]["languages"][0]["proficiency"] = "Native"
    generated = GeneratedDraftBundle.model_validate(payload)
    generated_before = generated.model_dump(mode="json", by_alias=True)
    bundle = ground_generated_bundle(generated, master_resume=master, target_job_id="job-1")

    for attempt in range(2):
        resume = bundle.resume
        assert [item.master_experience_id for item in resume.experiences] == ["role-beta", "role-alpha"]
        assert resume.languages == master.languages
        assert {item.name for item in resume.skills} == {item.name for item in master.skills}
        assert resume.section_order == [
            "summary", "experience", "education", "languages", "skills",
            "projects", "certifications", "additional",
        ]
        assert all(
            item in resume.evidence
            for item in master.evidence
            if item.id.startswith(("source:native-", "source:foundation-"))
        )
        if attempt == 0:
            repair = bundle.model_dump(mode="json", by_alias=True, exclude={"resume": {"evidence"}})
            repair["resume"]["experiences"].reverse()
            repair["resume"]["skills"] = []
            repair["resume"]["languages"] = []
            repair["resume"]["sectionOrder"] = [
                name for name in repair["resume"]["sectionOrder"] if name not in {"skills", "languages"}
            ]
            bundle = ground_generated_bundle(
                GeneratedDraftBundle.model_validate(repair), master_resume=master, target_job_id="job-1"
            )

    assert master.model_dump(mode="json", by_alias=True) == source_before
    assert generated.model_dump(mode="json", by_alias=True) == generated_before


def test_skills_allow_new_priority_and_categories_without_losing_source_names() -> None:
    master = _master_with_broader_skills_and_native_languages()
    payload = _generated_payload()
    fastapi = master.skills[2].model_dump(mode="json", by_alias=True)
    fastapi["category"] = "Python frameworks"
    payload["resume"]["skills"].insert(0, fastapi)
    payload["resume"]["skills"].append(
        {"id": "python-again", "name": "PYTHON", "category": "", "evidenceIds": ["source:skill"]}
    )
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=master, target_job_id="job-1"
    )
    frameworks = [item for item in bundle.resume.skills if item.category == "Frameworks"]
    assert [item.name for item in frameworks] == ["FastAPI", "Django"]
    assert list(dict.fromkeys(item.category for item in bundle.resume.skills)) == [
        "Languages", "Frameworks", "Databases", "Tools / DevOps",
    ]
    assert [item.name for item in bundle.resume.skills].count("Python") == 1
    assert len(bundle.resume.skills) == len(master.skills)


@pytest.mark.parametrize("select_optional", [False, True])
def test_optional_skill_groups_require_author_selection_and_follow_core_groups(
    select_optional: bool,
) -> None:
    source = _master_with_broader_skills_and_native_languages().model_dump(mode="json", by_alias=True)
    optional = {
        "id": "skill-llm", "name": "OpenAI API", "category": "AI & Automation",
        "evidenceIds": ["source:llm"],
    }
    source["skills"].append(optional)
    source["evidence"].append({"id": "source:llm", "type": "source", "text": "OpenAI API integration"})
    master = MasterResume.model_validate(source)
    payload = _generated_payload()
    if select_optional:
        payload["resume"]["skills"].insert(0, optional)
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=master, target_job_id="job-1"
    )
    categories = list(dict.fromkeys(item.category for item in bundle.resume.skills))
    assert categories[:4] == ["Languages", "Frameworks", "Databases", "Tools / DevOps"]
    assert ("OpenAI API" in [item.name for item in bundle.resume.skills]) is select_optional
    assert categories[4:] == (["AI & Automation"] if select_optional else [])
    assert ("source:llm" in [item.id for item in bundle.resume.evidence]) is select_optional


def test_vacancy_priority_inside_each_core_group_is_not_replaced_by_source_order() -> None:
    master = _master_with_broader_skills_and_native_languages()
    by_name = {item.name: item for item in master.skills}
    payload = _generated_payload()
    payload["resume"]["skills"] = [
        by_name[name].model_dump(mode="json", by_alias=True)
        for name in ("Pytest", "Redis", "PostgreSQL", "FastAPI", "Django", "Go", "Python")
    ]
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=master, target_job_id="job-1"
    )
    assert [item.name for item in bundle.resume.skills] == [
        "Go", "Python", "FastAPI", "Django", "Redis", "PostgreSQL", "Pytest",
    ]


def test_source_core_skill_cannot_be_moved_to_an_optional_group() -> None:
    master = _master_with_broader_skills_and_native_languages()
    payload = _generated_payload()
    payload["resume"]["skills"][0]["category"] = "AI & Automation"
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=master, target_job_id="job-1"
    )
    assert bundle.resume.skills[0].name == "Python"
    assert bundle.resume.skills[0].category == "Languages"


@pytest.mark.parametrize("legacy_category", ["", "Data", "Databases"])
def test_legacy_core_categories_are_corrected_without_restoring_optional_concepts(
    legacy_category: str,
) -> None:
    source = _master_with_broader_skills_and_native_languages().model_dump(mode="json", by_alias=True)
    for skill in source["skills"]:
        skill["category"] = legacy_category
    source["skills"].append({
        "id": "skill-ml", "name": "Machine Learning", "category": "",
        "evidenceIds": ["source:ml"],
    })
    source["evidence"].append({"id": "source:ml", "type": "source", "text": "Machine Learning"})
    master = MasterResume.model_validate(source)
    payload = _generated_payload()
    payload["resume"]["skills"] = []
    payload["resume"]["sectionOrder"].remove("skills")
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=master, target_job_id="job-1"
    )
    assert [item.name for item in bundle.resume.skills] == [
        "Python", "Go", "Django", "FastAPI", "PostgreSQL", "Redis", "Pytest",
    ]
    assert list(dict.fromkeys(item.category for item in bundle.resume.skills)) == [
        "Languages", "Frameworks", "Databases", "Tools / DevOps",
    ]
    assert "source:ml" not in [item.id for item in bundle.resume.evidence]


def test_omitted_role_is_rejected_instead_of_silently_shortening_work_history() -> None:
    payload = _generated_payload()
    payload["resume"]["experiences"].pop()
    with pytest.raises(GenerationGroundingError, match="every source experience"):
        ground_generated_bundle(
            GeneratedDraftBundle.model_validate(payload), master_resume=_master(), target_job_id="job-1"
        )


def test_skill_derived_from_role_evidence_can_add_a_new_skills_section() -> None:
    source = _master().model_dump(mode="json", by_alias=True)
    source["skills"] = []
    source["sectionOrder"].remove("skills")
    master = MasterResume.model_validate(source)
    payload = _generated_payload()
    payload["resume"]["skills"] = [
        {"id": "api-skill", "name": "API development", "evidenceIds": ["profile:alpha"]}
    ]
    payload["resume"]["sectionOrder"].remove("skills")
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(payload), master_resume=master, target_job_id="job-1"
    )
    assert bundle.resume.skills[0].name == "API development"
    assert "skills" in bundle.resume.section_order


@pytest.mark.parametrize("section", ["experiences", "languages", "skills"])
def test_validation_catches_protected_content_loss_after_materialization(section: str) -> None:
    master = _master_with_broader_skills_and_native_languages()
    bundle = ground_generated_bundle(
        GeneratedDraftBundle.model_validate(_generated_payload()), master_resume=master, target_job_id="job-1"
    )
    getattr(bundle.resume, section).pop()
    with pytest.raises(GenerationGroundingError):
        validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")
