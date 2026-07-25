import pytest
from pydantic import ValidationError

from app.models.resume import ExperienceRewrite, FinalResume, MasterResume


def evidence(evidence_id: str, text: str) -> dict[str, str]:
    return {
        "id": evidence_id,
        "type": "profile",
        "text": text,
    }


def valid_master_resume() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": "resume:master",
        "language": "English",
        "basics": {
            "fullName": "Ada Lovelace",
            "headline": "Platform Engineer",
        },
        "summary": {
            "text": "Platform engineer delivering reliable Python services.",
            "evidenceIds": ["profile:experience:acme:achievement-api"],
        },
        "experiences": [
            {
                "id": "experience:acme",
                "company": "Acme AG",
                "title": "Platform Engineer",
                "startDate": "2022-01",
                "isCurrent": True,
                "bullets": [
                    {
                        "id": "bullet:acme:api",
                        "text": "Built a reliable Python API.",
                        "evidenceIds": ["profile:experience:acme:achievement-api"],
                    }
                ],
            }
        ],
        "skills": [
            {
                "id": "skill:python",
                "name": "Python",
                "evidenceIds": ["profile:experience:acme:technology-python"],
            }
        ],
        "evidence": [
            evidence(
                "profile:experience:acme:achievement-api",
                "Built a reliable Python API.",
            ),
            evidence(
                "profile:experience:acme:technology-python",
                "Python",
            ),
        ],
        "sectionOrder": ["summary", "experience", "skills"],
    }


def test_master_resume_is_strict_and_evidence_backed() -> None:
    resume = MasterResume.model_validate(valid_master_resume())

    assert resume.id == "resume:master"
    assert resume.experiences[0].id == "experience:acme"
    assert resume.model_dump(by_alias=True)["sectionOrder"] == [
        "summary",
        "experience",
        "skills",
    ]

    invalid = valid_master_resume()
    invalid["unexpected"] = True
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MasterResume.model_validate(invalid)


def test_master_resume_rejects_duplicate_and_unknown_ids() -> None:
    duplicate = valid_master_resume()
    duplicate["skills"] = [
        {
            "id": "bullet:acme:api",
            "name": "Python",
            "evidenceIds": ["profile:experience:acme:technology-python"],
        }
    ]
    with pytest.raises(ValidationError, match="resume item IDs must not contain duplicates"):
        MasterResume.model_validate(duplicate)

    unknown_evidence = valid_master_resume()
    unknown_evidence["summary"] = {
        "text": "Unsupported claim.",
        "evidenceIds": ["profile:missing"],
    }
    with pytest.raises(ValidationError, match="references unknown evidence IDs"):
        MasterResume.model_validate(unknown_evidence)


def test_section_order_matches_non_empty_sections() -> None:
    missing = valid_master_resume()
    missing["sectionOrder"] = ["experience", "skills"]
    with pytest.raises(ValidationError, match="every non-empty section exactly once"):
        MasterResume.model_validate(missing)

    duplicate = valid_master_resume()
    duplicate["sectionOrder"] = ["summary", "experience", "skills", "skills"]
    with pytest.raises(ValidationError, match="sectionOrder must not contain duplicates"):
        MasterResume.model_validate(duplicate)


def test_experience_rewrite_links_each_master_experience_once() -> None:
    rewrite = ExperienceRewrite.model_validate(
        {
            "masterResumeId": "resume:master",
            "targetJobId": "job:platform",
            "experiences": [
                {
                    "id": "rewrite:acme",
                    "masterExperienceId": "experience:acme",
                    "company": "Acme AG",
                    "title": "Platform Engineer",
                    "period": "2022 — Present",
                    "bullets": [
                        {
                            "id": "tailored-bullet:acme:api",
                            "text": "Delivered reliable Python APIs.",
                            "evidenceIds": [
                                "profile:experience:acme:achievement-api",
                            ],
                        }
                    ],
                }
            ],
        }
    )

    assert rewrite.experiences[0].master_experience_id == "experience:acme"

    payload = rewrite.model_dump(by_alias=True)
    payload["experiences"].append(
        {
            **payload["experiences"][0],
            "id": "rewrite:acme:duplicate",
            "bullets": [
                {
                    "id": "tailored-bullet:acme:duplicate",
                    "text": "Another version.",
                    "evidenceIds": ["profile:experience:acme:achievement-api"],
                }
            ],
        }
    )
    with pytest.raises(ValidationError, match="masterExperienceIds must not contain duplicates"):
        ExperienceRewrite.model_validate(payload)


def test_final_resume_validates_order_and_complete_evidence_catalog() -> None:
    final = FinalResume.model_validate(
        {
            "id": "resume:final:platform",
            "masterResumeId": "resume:master",
            "targetJobId": "job:platform",
            "language": "English",
            "basics": {
                "fullName": "Ada Lovelace",
                "headline": "Platform Engineer",
            },
            "summary": {
                "text": "Platform engineer delivering reliable services.",
                "evidenceIds": ["profile:experience:acme:achievement-api"],
            },
            "experiences": [
                {
                    "id": "rewrite:acme",
                    "masterExperienceId": "experience:acme",
                    "company": "Acme AG",
                    "title": "Platform Engineer",
                    "period": "2022 — Present",
                    "bullets": [
                        {
                            "id": "tailored-bullet:acme:api",
                            "text": "Delivered reliable Python APIs.",
                            "evidenceIds": [
                                "profile:experience:acme:achievement-api",
                            ],
                        }
                    ],
                }
            ],
            "evidence": [
                evidence(
                    "profile:experience:acme:achievement-api",
                    "Built a reliable Python API.",
                )
            ],
            "sectionOrder": ["summary", "experience"],
        }
    )

    assert final.master_resume_id == "resume:master"
    assert final.target_job_id == "job:platform"
