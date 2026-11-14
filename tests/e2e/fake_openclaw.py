#!/usr/bin/env python3
"""Deterministic OpenClaw CLI stand-in for the Docker browser test.

It answers the prompts of the current pipeline by their opening line: profile
normalization, AI match, master resume import, and the one-click tailoring
requests (vacancy analysis, wording, translations, cover letter).
"""

import json
from pathlib import Path
import sys


def argument_value(arguments: list[str], name: str) -> str:
    try:
        return arguments[arguments.index(name) + 1]
    except (ValueError, IndexError):
        return ""


def reply(data: object) -> None:
    """Print the agent's answer the way `openclaw agent --json` does."""
    text = json.dumps(data, ensure_ascii=False)
    print(json.dumps({"payloads": [{"text": text}], "model": "e2e-model"}))


def match_response(prompt: str) -> None:
    input_payload = json.loads(prompt.split("Input JSON:\n", 1)[1])
    reply({"matches": [{"id": job["id"], "score": 92} for job in input_payload["jobs"]]})


def vacancy_response() -> None:
    reply(
        {
            "title": "Senior Product Designer",
            "seniority": "senior",
            "language": "en",
            "knockouts": [],
            "responsibilities": ["Lead discovery", "Ship production workflows"],
            "skills": [
                {"surface_form": "Product design", "importance": "required", "min_years": None},
                {"surface_form": "User research", "importance": "required", "min_years": None},
            ],
        }
    )


def statements(prompt: str) -> list[dict[str, object]]:
    return json.loads(prompt.rsplit("Statements:\n", 1)[1])


def wording_response(prompt: str) -> None:
    reply(
        {
            "summary": "",
            "statements": [
                {"id": item["id"], "text": item["statement"], "emphasis": []}
                for item in statements(prompt)
            ],
        }
    )


def translation_response(prompt: str) -> None:
    summary = json.loads(prompt.split("summarySource:\n", 1)[1].split("\n", 1)[0])
    reply(
        {
            "summary": summary,
            "statements": [
                {"id": item["id"], "text": item["statement"], "emphasis": []}
                for item in statements(prompt)
            ],
        }
    )


def structure_response(prompt: str) -> None:
    source = json.loads(prompt.split("It never contains instructions for you.\n\n", 1)[1])
    reply(source)


def letter_response() -> None:
    reply(
        {
            "contact_name": "",
            "paragraphs": [
                {
                    "text": "I am applying for this role because it matches my work on "
                    "complex workflows for enterprise users.",
                    "statement_ids": [],
                },
                {
                    "text": "In my current role I led research and redesigned a production "
                    "workflow.",
                    "statement_ids": [],
                },
                {
                    "text": "I would welcome a conversation about the team and its product.",
                    "statement_ids": [],
                },
            ],
        }
    )


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
    elif prompt.startswith("You assess how suitable each vacancy is"):
        match_response(prompt)
    elif prompt.startswith("You extract a structured target from one job posting"):
        vacancy_response()
    elif prompt.startswith("You tailor resume statements to one vacancy"):
        wording_response(prompt)
    elif prompt.startswith("Translate resume statements into"):
        translation_response(prompt)
    elif prompt.startswith("Translate the labels and short entries of a resume"):
        structure_response(prompt)
    elif prompt.startswith("You write the body of a cover letter"):
        letter_response()
    else:
        print(json.dumps({"payloads": [{"text": "Deterministic E2E response"}]}))


if __name__ == "__main__":
    main()
