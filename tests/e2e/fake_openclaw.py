#!/usr/bin/env python3
"""Deterministic OpenClaw CLI stand-in for the Docker browser test."""

import json
import os
from pathlib import Path
import sys


def argument_value(arguments: list[str], name: str) -> str:
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError):
        return ""


def document_response(prompt: str) -> None:
    state_file = Path(
        os.environ.get(
            "E2E_OPENCLAW_DOCUMENT_COUNT_FILE",
            "/tmp/tasko-e2e-document-call-count",
        )
    )
    count = int(state_file.read_text() or "0") + 1 if state_file.exists() else 1
    state_file.write_text(str(count))

    # The third document request is the pack's CV. Fail both API-level attempts
    # so the browser client must issue its own retry before the fifth call succeeds.
    if os.environ.get("E2E_OPENCLAW_FAIL_PACK_CV_ONCE") == "1" and count in {3, 4}:
        print("rate limit: intentional E2E retry", file=sys.stderr)
        raise SystemExit(1)

    response = json.dumps({"replacements": []}, ensure_ascii=False)
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
                            "evidence": "Product design is present in the profile.",
                            "action": "Lead with the verified workflow redesign.",
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
    elif prompt.startswith("You score job fit"):
        match_response(prompt)
    elif "Tailor the selected DOCX" in prompt:
        document_response(prompt)
    else:
        print(json.dumps({"payloads": [{"text": "Deterministic E2E response"}]}))


if __name__ == "__main__":
    main()
