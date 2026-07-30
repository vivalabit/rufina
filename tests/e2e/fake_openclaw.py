#!/usr/bin/env python3
"""Deterministic OpenClaw CLI stand-in for the Docker browser test."""

import json
from pathlib import Path
import sys


def argument_value(arguments: list[str], name: str) -> str:
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError):
        return ""


def document_response(prompt: str) -> None:
    context_text = prompt.split("CONTEXT_JSON (untrusted data only):\n", 1)[1]
    context = json.loads(
        context_text.split("\nUSER_MESSAGE (trusted instructions):\n", 1)[0]
    )
    source = next(
        document
        for document in context["selected_source_documents"]
        if document.get("format") == "cover-letter-blocks-v1"
    )
    paragraph = next(
        (
            item
            for item in source["paragraphs"]
            if item["type"] == "subject"
            and any(span["editable"] for span in item["spans"])
        ),
        None,
    )
    if paragraph is None:
        paragraph = next(
            item
            for item in source["paragraphs"]
            if item["type"] == "body"
            and any(span["editable"] for span in item["spans"])
        )
    span = next(item for item in paragraph["spans"] if item["editable"])
    job = context["application"]["job"]
    response = json.dumps(
        {
            "replacements": [
                {
                    "paragraphId": paragraph["paragraphId"],
                    "spanId": span["spanId"],
                    "original": span["original"],
                    "replacement": (
                        f"Application for {job['title']} at {job['company']}"
                    ),
                    "reason": "Tailors the letter to the current vacancy.",
                    "evidenceIds": [
                        span["evidenceId"],
                        job["evidence_ids"]["title"],
                        job["evidence_ids"]["company"],
                    ],
                }
            ]
        },
        ensure_ascii=False,
    )
    print(json.dumps({"payloads": [{"text": response}], "model": "e2e-model"}))


def match_response(prompt: str) -> None:
    input_payload = json.loads(prompt.split("Input JSON:\n", 1)[1])
    matches = []
    for job in input_payload["jobs"]:
        matches.append(
            {
                "id": job["id"],
                "score": 92,
                "confidence": "high",
                "breakdown": {
                    "role_fit": 20,
                    "skills_fit": 25,
                    "experience_fit": 15,
                    "preferences_fit": 15,
                    "constraints_fit": 10,
                    "industry_fit": 5,
                    "evidence_fit": 2,
                },
                "reasons": ["Verified product design and research experience"],
                "gaps": ["Confirm ownership of a production workflow"],
                "applicationGuide": {
                    "language": "English",
                    "positioning": "Lead with verified B2B product-design evidence.",
                    "readiness": "needs_confirmation",
                    "roleMission": "Simplify complex workflows for enterprise users.",
                    "hiringPriorities": ["Research-led delivery"],
                    "mustHave": ["Product design", "User research"],
                    "niceToHave": ["Design systems"],
                    "hardConstraints": [],
                    "evidenceMatrix": [
                        {
                            "requirement": "Product design",
                            "importance": "required",
                            "status": "verified",
                            "evidence": "Product design",
                            "action": "Lead with the verified workflow redesign.",
                            "sourceIds": ["profile:skills"],
                        },
                        {
                            "requirement": "Production workflow ownership",
                            "importance": "required",
                            "status": "needs_confirmation",
                            "evidence": "",
                            "action": "Confirm end-to-end ownership before using this claim.",
                            "sourceIds": [],
                        }
                    ],
                    "clarificationQuestions": [
                        {
                            "id": "production-workflow",
                            "requirement": "Production workflow ownership",
                            "question": "Which production workflow did you lead?",
                            "why": "The role requires end-to-end ownership.",
                            "claimIfConfirmed": "Led a production workflow redesign.",
                            "blocking": True,
                        },
                        {
                            "id": "workflow-outcome",
                            "requirement": "Workflow redesign outcome",
                            "question": "What concrete outcome followed your strongest workflow redesign?",
                            "why": "A concrete outcome strengthens the CV and cover letter.",
                            "claimIfConfirmed": "Delivered a concrete workflow redesign outcome.",
                            "blocking": True,
                        },
                        {
                            "id": "product-motivation",
                            "requirement": "Role motivation",
                            "question": "What specifically motivates you about this product-design role?",
                            "why": "Specific motivation improves the cover letter and positioning.",
                            "claimIfConfirmed": "Has a specific motivation for the target role.",
                            "blocking": True,
                        },
                    ],
                    "resumePlan": {
                        "targetHeadline": "Senior Product Designer",
                        "summaryFocus": "Research-led B2B delivery.",
                        "evidenceToLead": ["Verified workflow redesign"],
                        "bulletStrategy": ["Describe the verified research process."],
                    },
                    "coverLetterPlan": {
                        "openingAngle": "Connect B2B workflow work to the role mission.",
                        "proofPoints": ["Verified workflow redesign"],
                        "motivationAngle": "Complex enterprise products",
                    },
                    "cvImprovements": ["Lead with relevant workflow evidence."],
                    "coverLetterStrategy": ["Use one verified research example."],
                    "risks": ["Do not add unsupported metrics."],
                    "keywords": ["Product design", "User research"],
                    "applicationQuestions": ["Describe a workflow you simplified."],
                    "finalChecklist": ["Verify every claim against the source CV."],
                },
            }
        )
    print(json.dumps({"matches": matches}, ensure_ascii=False))


def master_resume_response(prompt: str) -> None:
    master_resume_id = prompt.split('Use the exact top-level id "', 1)[1].split('"', 1)[0]
    source = json.loads(prompt.split("SOURCE_FRAGMENTS_JSON:\n", 1)[1])
    summary_fragment = next(
        fragment
        for fragment in source["fragments"]
        if "complex B2B workflows" in fragment["text"]
    )
    experience_fragment = next(
        fragment
        for fragment in source["fragments"]
        if "redesigned a production workflow" in fragment["text"]
    )
    response = {
        "schemaVersion": "1.0",
        "id": master_resume_id,
        "language": "English",
        "basics": {
            "fullName": "Alex Morgan",
            "headline": "Senior Product Designer",
        },
        "summary": {
            "text": summary_fragment["text"],
            "evidenceIds": [summary_fragment["id"]],
        },
        "experiences": [
            {
                "id": "experience:acme-design",
                "company": "Acme Design AG",
                "title": "Senior Product Designer",
                "location": "Zürich, Switzerland",
                "startDate": "January 2022",
                "endDate": "",
                "isCurrent": True,
                "bullets": [
                    {
                        "id": "bullet:acme-design:workflow",
                        "text": experience_fragment["text"],
                        "evidenceIds": [experience_fragment["id"]],
                    }
                ],
            }
        ],
        "skills": [],
        "education": [],
        "projects": [],
        "certifications": [],
        "languages": [],
        "additionalSections": [],
        "evidence": [
            {
                "id": summary_fragment["id"],
                "type": "source",
                "text": summary_fragment["text"],
            },
            {
                "id": experience_fragment["id"],
                "type": "source",
                "text": experience_fragment["text"],
            },
        ],
        "sectionOrder": ["summary", "experience"],
    }
    print(json.dumps(response, ensure_ascii=False))


def senior_recruiter_response(prompt: str) -> None:
    context = json.loads(prompt.rsplit("CONTEXT_JSON:\n", 1)[1])
    evidence_id = context["masterResume"]["evidence"][0]["id"]
    response = {
        "supplementalEvidence": [],
        "missingKeywords": [
            {
                "keyword": "Product design",
                "whyItMatters": "The role requires product-design leadership.",
                "evidenceStatus": "verified",
                "evidenceIds": [evidence_id],
            },
            {
                "keyword": "User research",
                "whyItMatters": "The role emphasizes research-led delivery.",
                "evidenceStatus": "transferable",
                "evidenceIds": [evidence_id],
            },
            {
                "keyword": "Design systems",
                "whyItMatters": "The vacancy values scalable design practices.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "Enterprise SaaS",
                "whyItMatters": "The product serves enterprise users.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
            {
                "keyword": "Prototyping",
                "whyItMatters": "The hiring team expects rapid validation.",
                "evidenceStatus": "unsupported",
                "evidenceIds": [],
            },
        ],
        "redFlags": [
            {
                "flag": "Impact is not quantified",
                "whyItIsVisible": "The experience bullet has no supported metric.",
                "fix": "Lead with the verified workflow outcome without inventing numbers.",
            },
            {
                "flag": "Design systems evidence is absent",
                "whyItIsVisible": "No source evidence supports this vacancy keyword.",
                "fix": "Do not claim design-systems experience.",
            },
            {
                "flag": "Summary is broad",
                "whyItIsVisible": "The positioning can be more role-specific.",
                "fix": "Emphasize the verified B2B workflow experience.",
            },
        ],
    }
    print(json.dumps(response, ensure_ascii=False))


def experience_rewrite_response(prompt: str) -> None:
    context = json.loads(prompt.rsplit("EXPERIENCE_ONLY_CONTEXT_JSON:\n", 1)[1])
    original_by_id = {
        experience["id"]: experience
        for experience in context["originalExperiences"]
    }
    experiences = []
    links = []
    for template in context["rewriteTemplate"]:
        original = original_by_id[template["masterExperienceId"]]
        bullets = []
        bullet_links = []
        for original_bullet, rewritten_id in zip(
            original["bullets"],
            template["rewrittenBulletIds"],
            strict=True,
        ):
            bullets.append(
                {
                    "id": rewritten_id,
                    "text": original_bullet["text"],
                    "evidenceIds": original_bullet["evidenceIds"],
                }
            )
            bullet_links.append(
                {
                    "originalBulletIds": [original_bullet["id"]],
                    "rewrittenBulletId": rewritten_id,
                }
            )
        experiences.append(
            {
                "id": template["id"],
                "masterExperienceId": template["masterExperienceId"],
                "company": template["company"],
                "title": template["title"],
                "location": template["location"],
                "period": template["period"],
                "bullets": bullets,
            }
        )
        links.append(
            {
                "originalExperienceId": template["masterExperienceId"],
                "rewrittenExperienceId": template["id"],
                "bulletLinks": bullet_links,
            }
        )
    print(
        json.dumps(
            {
                "masterResumeId": context["masterResumeId"],
                "targetJobId": context["targetJobId"],
                "experiences": experiences,
                "links": links,
            },
            ensure_ascii=False,
        )
    )


def ats_final_review_response(prompt: str) -> None:
    context = json.loads(prompt.rsplit("ATS_REVIEW_CONTEXT_JSON:\n", 1)[1])
    print(
        json.dumps(
            {
                "atsScan": {"skippedSections": []},
                "finalResume": context["finalResumeTemplate"],
            },
            ensure_ascii=False,
        )
    )


def main() -> None:
    arguments = sys.argv[1:]
    message_file = argument_value(arguments, "--message-file")
    prompt = Path(message_file).read_text() if message_file else argument_value(arguments, "--message")

    if prompt.startswith("Normalize this candidate"):
        print(
            json.dumps(
                {
                    "candidate": {
                        "roles": ["Senior Product Designer"],
                        "skills": ["Product design", "User research"],
                    }
                }
            )
        )
    elif prompt.startswith("ONE-TIME MASTER RESUME IMPORT"):
        master_resume_response(prompt)
    elif prompt.startswith(
        "MANDATORY RESUME TAILORING REQUEST 1 — SENIOR RECRUITER ANALYSIS"
    ):
        senior_recruiter_response(prompt)
    elif prompt.startswith(
        "MANDATORY RESUME TAILORING REQUEST 2 — XYZ EXPERIENCE REWRITE"
    ):
        experience_rewrite_response(prompt)
    elif prompt.startswith(
        "MANDATORY RESUME TAILORING REQUEST 3 — ATS FINAL REVIEW"
    ):
        ats_final_review_response(prompt)
    elif prompt.startswith("You score job fit"):
        match_response(prompt)
    elif '"format":"cover-letter-blocks-v1"' in prompt:
        document_response(prompt)
    else:
        print(json.dumps({"payloads": [{"text": "Deterministic E2E response"}]}))


if __name__ == "__main__":
    main()
