from __future__ import annotations

import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.models.resume import (
    FinalResume,
    ImaginatorDraft,
    ImaginatorProtectedFactsAudit,
    MasterResume,
)
from app.services.ai_backend import AIRequest, AIResult, AIUsage
from app.services.resume_imaginator import (
    ResumeImaginatorError,
    assemble_imaginator_resume,
    build_imaginator_prompt,
    build_imaginator_protected_facts_audit_prompt,
    generate_imaginator_resume,
    imaginator_auditable_claims,
    imaginator_source_context,
    validate_imaginator_draft,
    validate_imaginator_locks,
    validate_imaginator_protected_facts_audit,
)

GENERATION_ID = "a" * 32


def master_resume_payload() -> dict[str, object]:
    return {
        "schemaVersion": "1.0",
        "id": "resume:master:imaginator",
        "language": "English",
        "basics": {
            "fullName": "Ada Lovelace",
            "headline": "Platform Engineer",
            "email": "ada@example.test",
            "phone": "+41 44 000 00 00",
            "location": "Zurich, Switzerland",
            "workAuthorization": "Swiss work permit",
            "linkedin": "https://www.linkedin.com/in/ada",
            "github": "https://github.com/ada",
            "portfolio": "https://ada.example.test",
        },
        "summary": {
            "text": "Engineer building reliable services.",
            "evidenceIds": ["source:summary"],
        },
        "experiences": [
            {
                "id": "experience:acme",
                "company": "Acme AG",
                "title": "Platform Engineer",
                "location": "Zurich",
                "startDate": "2022",
                "isCurrent": True,
                "bullets": [
                    {
                        "id": "bullet:acme:platform",
                        "text": "Built Python services.",
                        "evidenceIds": ["profile:acme:platform"],
                    }
                ],
            },
            {
                "id": "experience:globex",
                "company": "Globex GmbH",
                "title": "Software Engineer",
                "location": "Basel",
                "startDate": "2019",
                "endDate": "2021",
                "bullets": [
                    {
                        "id": "bullet:globex:backend",
                        "text": "Maintained backend applications.",
                        "evidenceIds": ["profile:globex:backend"],
                    }
                ],
            },
        ],
        "skills": [
            {
                "id": "skill:python",
                "name": "Python",
                "category": "Programming",
                "evidenceIds": ["profile:skill:python"],
            }
        ],
        "education": [
            {
                "id": "education:eth",
                "institution": "ETH Zürich",
                "credential": "MSc",
                "fieldOfStudy": "Computer Science",
                "location": "Zurich",
                "startDate": "2017",
                "endDate": "2019",
                "details": [
                    {
                        "id": "education:eth:detail:systems",
                        "text": "Distributed systems specialization.",
                        "evidenceIds": ["source:education:eth:systems"],
                    }
                ],
            }
        ],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [
            {
                "id": "source:summary",
                "type": "source",
                "text": "Engineer building reliable services.",
            },
            {
                "id": "profile:acme:platform",
                "type": "profile",
                "text": "Built Python services at Acme AG.",
            },
            {
                "id": "profile:globex:backend",
                "type": "profile",
                "text": "Maintained backend applications at Globex GmbH.",
            },
            {
                "id": "profile:skill:python",
                "type": "profile",
                "text": "Python.",
            },
            {
                "id": "source:education:eth:systems",
                "type": "source",
                "text": "Distributed systems specialization.",
            },
        ],
        "sectionOrder": ["summary", "experience", "skills", "education"],
    }


def master_resume() -> MasterResume:
    return MasterResume.model_validate(master_resume_payload())


def imaginator_draft_payload() -> dict[str, object]:
    return {
        "headline": "Principal AI Platform Architect",
        "summary": (
            "Principal architect delivering global AI platforms and measurable "
            "business transformation."
        ),
        "experiences": [
            {
                "masterExperienceId": "experience:acme",
                "title": "Principal AI Platform Architect",
                "location": "Zurich",
                "period": "2022 — Present",
                "bullets": [
                    "Scaled a global AI platform to 50 markets.",
                    "Reduced model delivery time by 80 percent.",
                ],
            }
        ],
        "omittedExperiences": [
            {
                "masterExperienceId": "experience:globex",
                "reason": "Less relevant to the target leadership role.",
            }
        ],
        "skillGroups": [
            {
                "category": "Data & AI",
                "skills": ["Machine Learning", "LLM Platforms"],
            },
            {
                "category": "Databases",
                "skills": ["PostgreSQL", "Vector Databases"],
            },
        ],
        "projects": [
            {
                "name": "Enterprise AI Control Plane",
                "role": "Founder and Principal Architect",
                "url": "https://projects.example.test/ai-control-plane",
                "bullets": ["Created a governance platform used across 20 teams."],
            }
        ],
        "certifications": [
            {
                "name": "Advanced AI Architecture",
                "issuer": "Example Institute",
                "issuedOn": "2025",
                "expiresOn": "",
            }
        ],
        "languages": [
            {
                "name": "English",
                "proficiency": "Native",
            }
        ],
        "additionalSections": [
            {
                "title": "Industry Leadership",
                "items": ["Keynote speaker at international AI conferences."],
            }
        ],
        "sectionOrder": [
            "summary",
            "skills",
            "experience",
            "projects",
            "education",
            "certifications",
            "languages",
            "additional",
        ],
    }


def imaginator_draft() -> ImaginatorDraft:
    return ImaginatorDraft.model_validate(imaginator_draft_payload())


def assemble():
    return assemble_imaginator_resume(
        generation_id=GENERATION_ID,
        draft=imaginator_draft(),
        master_resume=master_resume(),
        target_job_id="job:principal-ai",
        target_language="English",
    )


def test_assembler_copies_locked_company_education_and_candidate_identity() -> None:
    source = master_resume()
    final, ledger = assemble()

    assert [(item.master_experience_id, item.company) for item in final.experiences] == [
        ("experience:acme", "Acme AG")
    ]
    assert final.experiences[0].title == "Principal AI Platform Architect"
    assert final.education == source.education
    assert final.basics.headline == "Principal AI Platform Architect"
    for field_name in (
        "full_name",
        "email",
        "phone",
        "location",
        "work_authorization",
        "linkedin",
        "github",
        "portfolio",
    ):
        assert getattr(final.basics, field_name) == getattr(source.basics, field_name)

    locked_paths = {
        item.path for item in ledger if item.origin == "locked_source"
    }
    assert locked_paths == {"experiences[0].company", "education[0]"}
    assert final.section_order == [
        "summary",
        "skills",
        "experience",
        "projects",
        "education",
        "certifications",
        "languages",
        "additional",
    ]


def test_lock_validator_rejects_company_education_and_identity_tampering() -> None:
    source = master_resume()
    final, _ledger = assemble()

    changed_experience = final.experiences[0].model_copy(
        update={"company": "Invented Holdings SA"}
    )
    changed_company = final.model_copy(update={"experiences": [changed_experience]})
    with pytest.raises(
        ResumeImaginatorError,
        match="locked employer binding",
    ) as company_error:
        validate_imaginator_locks(changed_company, master_resume=source)
    assert company_error.value.code == "immutable_violation"

    changed_education = final.model_copy(update={"education": []})
    with pytest.raises(
        ResumeImaginatorError,
        match="locked education",
    ) as education_error:
        validate_imaginator_locks(changed_education, master_resume=source)
    assert education_error.value.code == "immutable_violation"

    changed_basics = final.basics.model_copy(
        update={"email": "invented@example.test"}
    )
    changed_identity = final.model_copy(update={"basics": changed_basics})
    with pytest.raises(
        ResumeImaginatorError,
        match="locked candidate identity",
    ) as identity_error:
        validate_imaginator_locks(changed_identity, master_resume=source)
    assert identity_error.value.code == "immutable_violation"


def test_draft_requires_an_explicit_included_or_omitted_partition() -> None:
    source = master_resume()

    incomplete_payload = imaginator_draft_payload()
    incomplete_payload["omittedExperiences"] = []
    incomplete = ImaginatorDraft.model_validate(incomplete_payload)
    with pytest.raises(
        ResumeImaginatorError,
        match="include or explicitly omit every source experience",
    ) as incomplete_error:
        validate_imaginator_draft(incomplete, master_resume=source)
    assert incomplete_error.value.code == "invalid_output"

    unknown_payload = imaginator_draft_payload()
    unknown_payload["omittedExperiences"] = [
        {
            "masterExperienceId": "experience:unknown",
            "reason": "Unknown source binding.",
        },
        {
            "masterExperienceId": "experience:globex",
            "reason": "Less relevant.",
        },
    ]
    unknown = ImaginatorDraft.model_validate(unknown_payload)
    with pytest.raises(
        ResumeImaginatorError,
        match="unknown source experience",
    ) as unknown_error:
        validate_imaginator_draft(unknown, master_resume=source)
    assert unknown_error.value.code == "invalid_output"

    overlapping_payload = imaginator_draft_payload()
    overlapping_payload["omittedExperiences"] = [
        {
            "masterExperienceId": "experience:acme",
            "reason": "Cannot be both included and omitted.",
        },
        {
            "masterExperienceId": "experience:globex",
            "reason": "Less relevant.",
        },
    ]
    with pytest.raises(
        ValidationError,
        match="included and omitted experiences must not overlap",
    ):
        ImaginatorDraft.model_validate(overlapping_payload)


def test_all_experiences_may_be_explicitly_omitted() -> None:
    payload = imaginator_draft_payload()
    payload["experiences"] = []
    payload["omittedExperiences"] = [
        {
            "masterExperienceId": "experience:acme",
            "reason": "Not relevant to the target narrative.",
        },
        {
            "masterExperienceId": "experience:globex",
            "reason": "Not relevant to the target narrative.",
        },
    ]
    draft = ImaginatorDraft.model_validate(payload)

    final, ledger = assemble_imaginator_resume(
        generation_id=GENERATION_ID,
        draft=draft,
        master_resume=master_resume(),
        target_job_id="job:principal-ai",
        target_language="English",
    )

    assert final.experiences == []
    assert "experience" not in final.section_order
    assert final.education == master_resume().education
    assert all(
        not item.path.endswith(".company")
        for item in ledger
        if item.origin == "locked_source"
    )


def test_synthetic_claim_ledger_and_evidence_are_complete_and_coherent() -> None:
    final, ledger = assemble()
    evidence_by_id = {item.id: item for item in final.evidence}
    synthetic_claims = [item for item in ledger if item.origin == "synthetic"]
    locked_claims = [item for item in ledger if item.origin == "locked_source"]

    assert synthetic_claims
    assert locked_claims
    for claim in synthetic_claims:
        assert len(claim.evidence_ids) == 1
        evidence = evidence_by_id[claim.evidence_ids[0]]
        assert evidence.type == "imagination"
        assert evidence.id.startswith(f"imagination:{GENERATION_ID}:")
        assert evidence.source_id == f"imaginator:{GENERATION_ID}"
        assert evidence.text == claim.text
    assert all(not claim.evidence_ids for claim in locked_claims)

    imagination_evidence_ids = {
        item.id for item in final.evidence if item.type == "imagination"
    }
    ledger_evidence_ids = {
        evidence_id
        for claim in synthetic_claims
        for evidence_id in claim.evidence_ids
    }
    assert imagination_evidence_ids == ledger_evidence_ids

    education_evidence_id = "source:education:eth:systems"
    assert education_evidence_id in evidence_by_id
    assert final.education[0].details[0].evidence_ids == [education_evidence_id]
    assert "source:summary" not in evidence_by_id
    assert "profile:acme:platform" not in evidence_by_id


def test_skill_claim_ledger_paths_address_each_nested_skill() -> None:
    _final, ledger = assemble()

    skill_paths = {
        item.path
        for item in ledger
        if item.origin == "synthetic" and item.path.startswith("skills[")
    }

    assert skill_paths == {
        "skills[0].name",
        "skills[0].category",
        "skills[1].name",
        "skills[1].category",
        "skills[2].name",
        "skills[2].category",
        "skills[3].name",
        "skills[3].category",
    }


def test_ai_output_schema_excludes_server_owned_fields() -> None:
    prompt = build_imaginator_prompt(
        master_resume=master_resume(),
        vacancy={
            "id": "job:principal-ai",
            "company": "Target AG",
            "title": "Principal AI Architect",
            "description": "Lead the enterprise AI platform.",
        },
        target_language="English",
        revision_instruction="Emphasize AI leadership.",
    )
    schema_text = (
        prompt.split("IMAGINATOR_DRAFT_JSON_SCHEMA:\n", 1)[1]
        .split("\nIMAGINATOR_CONTEXT_JSON:\n", 1)[0]
    )
    schema = json.loads(schema_text)

    assert set(schema["properties"]) == {
        "headline",
        "summary",
        "experiences",
        "omittedExperiences",
        "skillGroups",
        "projects",
        "certifications",
        "languages",
        "additionalSections",
        "sectionOrder",
    }
    assert set(
        schema["$defs"]["ImaginatorExperienceDraft"]["properties"]
    ) == {
        "masterExperienceId",
        "title",
        "location",
        "period",
        "bullets",
    }
    assert "Do not output a company" in prompt
    assert "Do not output education, full name, contact data, evidence IDs" in prompt
    assert "TRUSTED USER REVISION REQUEST" in prompt
    context = json.loads(prompt.split("IMAGINATOR_CONTEXT_JSON:\n", 1)[1])
    assert context["sourceResume"] == imaginator_source_context(
        master_resume()
    )
    serialized_source = json.dumps(
        context["sourceResume"],
        ensure_ascii=False,
    )
    assert "Ada Lovelace" not in serialized_source
    assert "ada@example.test" not in serialized_source
    assert "source:education" not in serialized_source
    assert "profile:acme" not in serialized_source
    assert context["lockedEmployerBindings"][0]["company"] == "Acme AG"
    assert context["lockedEducation"][0]["institution"] == "ETH Zürich"

    protected_output = deepcopy(imaginator_draft_payload())
    protected_output["education"] = []
    protected_output["experiences"][0]["company"] = "Invented Holdings SA"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ImaginatorDraft.model_validate(protected_output)


def test_generation_uses_typed_generation_and_protected_facts_requests() -> None:
    requests: list[AIRequest] = []

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            requests.append(request)
            if request.response_model is ImaginatorProtectedFactsAudit:
                context = json.loads(
                    request.prompt.split(
                        "PROTECTED_FACTS_AUDIT_CONTEXT_JSON:\n",
                        1,
                    )[1]
                )
                return AIResult(
                    text="",
                    structured_data={
                        "inputFingerprint": context["inputFingerprint"],
                        "verdict": "pass",
                        "safePaths": [
                            claim["path"] for claim in context["claims"]
                        ],
                        "violations": [],
                    },
                    model="gpt-5.6-terra",
                    backend="openai_api",
                    usage=AIUsage(
                        input_tokens=40,
                        output_tokens=20,
                        total_tokens=60,
                        source="provider",
                    ),
                    latency_ms=45,
                    session_id="response-imaginator-audit-1",
                )
            return AIResult(
                text="",
                structured_data=imaginator_draft_payload(),
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(
                    input_tokens=100,
                    output_tokens=200,
                    total_tokens=300,
                    source="provider",
                ),
                latency_ms=123,
                session_id="response-imaginator-1",
            )

    outcome = generate_imaginator_resume(
        master_resume=master_resume(),
        master_resume_version_id="master-version:1",
        target_job_id="job:principal-ai",
        vacancy={
            "id": "job:principal-ai",
            "company": "Target AG",
            "title": "Principal AI Architect",
            "description": "Lead the enterprise AI platform.",
        },
        target_language="English",
        revision_instruction="Emphasize AI leadership.",
        backend=FakeBackend(),
        model="gpt-5.6-terra",
        agent_id="rufina-assistant",
        thinking="high",
        timeout_seconds=120,
    )

    assert len(requests) == 2
    assert requests[0].structured is True
    assert requests[0].response_model is ImaginatorDraft
    assert "STANDALONE RESUME PIPELINE — IMAGINATOR" in requests[0].prompt
    assert requests[1].structured is True
    assert requests[1].response_model is ImaginatorProtectedFactsAudit
    assert "INDEPENDENT IMAGINATOR PROTECTED-FACTS AUDIT" in requests[1].prompt
    assert outcome.final_resume.experiences[0].company == "Acme AG"
    assert outcome.final_resume.education == master_resume().education
    assert outcome.result.usage.total_tokens == 300
    assert outcome.protected_facts_audit.passed is True
    assert outcome.protected_facts_audit.metrics.total_tokens == 60


def test_protected_facts_audit_blocks_implied_google_employment_and_harvard_degree() -> None:
    unsafe_draft = imaginator_draft_payload()
    unsafe_draft["summary"] = (
        "Harvard MBA who served as CTO of Google and now builds AI platforms."
    )

    class FakeBackend:
        name = "openai_api"

        def generate(self, request: AIRequest) -> AIResult:
            if request.response_model is ImaginatorDraft:
                structured_data = unsafe_draft
                session_id = "response-imaginator-unsafe"
            else:
                context = json.loads(
                    request.prompt.split(
                        "PROTECTED_FACTS_AUDIT_CONTEXT_JSON:\n",
                        1,
                    )[1]
                )
                structured_data = {
                    "inputFingerprint": context["inputFingerprint"],
                    "verdict": "reject",
                    "safePaths": [
                        claim["path"]
                        for claim in context["claims"]
                        if claim["path"] != "summary"
                    ],
                    "violations": [
                        {
                            "path": "summary",
                            "categories": ["employer", "education"],
                            "reason": (
                                "Google is not a locked employer and Harvard MBA "
                                "is not present in locked education."
                            ),
                        }
                    ],
                }
                session_id = "response-imaginator-audit-unsafe"
            return AIResult(
                text="",
                structured_data=structured_data,
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id=session_id,
            )

    with pytest.raises(
        ResumeImaginatorError,
        match="conflicts with protected source facts",
    ) as error:
        generate_imaginator_resume(
            master_resume=master_resume(),
            master_resume_version_id="master-version:1",
            target_job_id="job:principal-ai",
            vacancy={
                "id": "job:principal-ai",
                "company": "Target AG",
                "title": "Principal AI Architect",
                "description": "Lead the enterprise AI platform.",
            },
            target_language="English",
            revision_instruction="",
            backend=FakeBackend(),
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="high",
            timeout_seconds=120,
        )

    assert error.value.code == "protected_fact_violation"


def test_protected_facts_audit_must_exactly_partition_every_generated_claim() -> None:
    source = master_resume()
    draft = imaginator_draft()
    _prompt, fingerprint, claim_count = (
        build_imaginator_protected_facts_audit_prompt(
            draft=draft,
            master_resume=source,
        )
    )
    claim_paths = [
        claim["path"] for claim in imaginator_auditable_claims(draft)
    ]
    assert claim_count == len(claim_paths)
    incomplete = ImaginatorProtectedFactsAudit.model_validate(
        {
            "inputFingerprint": fingerprint,
            "verdict": "pass",
            "safePaths": claim_paths[:-1],
            "violations": [],
        }
    )

    with pytest.raises(
        ResumeImaginatorError,
        match="did not classify every claim",
    ) as error:
        validate_imaginator_protected_facts_audit(
            incomplete,
            draft=draft,
            master_resume=source,
        )

    assert error.value.code == "invalid_output"


def test_generation_rejects_protected_fields_returned_by_the_model() -> None:
    invalid_output = deepcopy(imaginator_draft_payload())
    invalid_output["experiences"][0]["company"] = "Invented Holdings SA"

    class FakeBackend:
        name = "openai_api"

        def generate(self, _request: AIRequest) -> AIResult:
            return AIResult(
                text="",
                structured_data=invalid_output,
                model="gpt-5.6-terra",
                backend="openai_api",
                usage=AIUsage(),
                latency_ms=1,
                session_id="response-imaginator-invalid",
            )

    with pytest.raises(
        ResumeImaginatorError,
        match="invalid structured data",
    ) as error:
        generate_imaginator_resume(
            master_resume=master_resume(),
            master_resume_version_id="master-version:1",
            target_job_id="job:principal-ai",
            vacancy={
                "id": "job:principal-ai",
                "company": "Target AG",
                "title": "Principal AI Architect",
                "description": "Lead the enterprise AI platform.",
            },
            target_language=None,
            revision_instruction="",
            backend=FakeBackend(),
            model="gpt-5.6-terra",
            agent_id="rufina-assistant",
            thinking="high",
            timeout_seconds=120,
        )
    assert error.value.code == "invalid_output"


def test_imagination_evidence_is_isolated_from_standard_resume_models() -> None:
    canonical_payload = deepcopy(master_resume_payload())
    canonical_payload["evidence"].append(
        {
            "id": "imagination:not-allowed",
            "type": "imagination",
            "text": "Invented canonical fact.",
        }
    )
    with pytest.raises(
        ValidationError,
        match="Master Resume evidence cannot contain Imaginator claims",
    ):
        MasterResume.model_validate(canonical_payload)

    final, _ledger = assemble()
    standard_payload = final.model_dump(by_alias=True, exclude_none=True)
    standard_payload["id"] = "resume:ats:standard"
    with pytest.raises(
        ValidationError,
        match="reserved for Imaginator resumes",
    ):
        FinalResume.model_validate(standard_payload)
