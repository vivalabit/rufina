"""Synthetic profile, vacancy and document fixtures for tailoring and rendering tests."""

from __future__ import annotations

from typing import Any

from app.models.resume import FinalResume, MasterResume

VACANCY_TEXT = """Backend Engineer (Python) 80-100%

Northwind Analytics AG builds data products for Swiss retailers.

Your responsibilities
- Design and operate Python services with FastAPI and PostgreSQL
- Build data pipelines that process large data volumes
- Run workloads on Kubernetes and AWS

Requirements
- 2+ years of experience with Python
- Solid knowledge of FastAPI, PostgreSQL and Docker
- Experience with Kubernetes
- Fluent English

Nice to have
- Kafka or Terraform
- Experience with LLM integrations

We offer flexible working hours and a modern office in Zurich.
"""

_ROLES: tuple[dict[str, Any], ...] = (
    {
        "id": "role-atlas",
        "company": "Atlas Data GmbH",
        "title": "Backend Developer",
        "location": "Zurich",
        "startDate": "06/2025",
        "endDate": "",
        "isCurrent": True,
        "stack": ("Python", "FastAPI", "PostgreSQL", "Docker", "Kubernetes"),
        "bullets": (
            "Cut report generation time by 40% by rebuilding the export service in "
            "Python with FastAPI and PostgreSQL.",
            "Processed 2 TB of retail data per month by building ingestion pipelines "
            "that run on Kubernetes.",
            "Reduced deployment time from 30 minutes to 5 minutes by containerizing "
            "services with Docker.",
            "Organized the weekly team lunch rota for 12 colleagues.",
        ),
    },
    {
        "id": "role-borealis",
        "company": "Borealis Shop AG",
        "title": "Software Engineering Intern",
        "location": "Bern",
        "startDate": "09/2024",
        "endDate": "05/2025",
        "isCurrent": False,
        "stack": ("Python", "Django", "Redis"),
        "bullets": (
            "Served 10,000+ requests per day by implementing a Django REST module "
            "with Redis caching.",
            "Blocked 100% of simulated brute-force attacks by adding rate limiting "
            "to the login flow.",
            "Wrote onboarding notes for new interns.",
        ),
    },
)

_SKILLS: tuple[tuple[str, str], ...] = (
    ("Python", "Languages"),
    ("TypeScript", "Languages"),
    ("SQL", "Languages"),
    ("FastAPI", "Frameworks"),
    ("Django", "Frameworks"),
    ("React", "Frameworks"),
    ("PostgreSQL", "Databases"),
    ("Redis", "Databases"),
    ("Docker", "Tools / DevOps"),
    ("Kubernetes", "Tools / DevOps"),
    ("AWS", "Tools / DevOps"),
    ("Git", "Tools / DevOps"),
)

_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("English", "Fluent (C1)"),
    ("German", "Intermediate (B1)"),
)


def master_resume_payload(*, extra_bullets_per_role: int = 0) -> dict[str, Any]:
    """A two-role backend profile; extra bullets make page fitting observable."""
    evidence: list[dict[str, Any]] = [
        {"id": "source:summary", "type": "source", "text": "Backend developer profile."},
        {"id": "source:education", "type": "source", "text": "BSc Computer Science."},
    ]
    experiences: list[dict[str, Any]] = []
    for role in _ROLES:
        texts = list(role["bullets"]) + [
            f"Maintained internal tool number {index + 1} used by the operations team "
            f"for daily reconciliation of supplier invoices."
            for index in range(extra_bullets_per_role)
        ]
        bullets = []
        for index, text in enumerate(texts, start=1):
            evidence_id = f"profile:{role['id']}-achievement-{index}"
            evidence.append(
                {
                    "id": evidence_id,
                    "type": "profile",
                    "text": text,
                    "claimType": "achievement",
                    "experienceId": role["id"],
                }
            )
            bullets.append(
                {"id": f"{role['id']}-bullet-{index}", "text": text, "evidenceIds": [evidence_id]}
            )
        stack = []
        for index, technology in enumerate(role["stack"], start=1):
            evidence_id = f"profile:{role['id']}-technology-{index}"
            evidence.append(
                {
                    "id": evidence_id,
                    "type": "profile",
                    "text": technology,
                    "claimType": "technology",
                    "experienceId": role["id"],
                }
            )
            stack.append(
                {
                    "id": f"{role['id']}-stack-{index}",
                    "technology": technology,
                    "context": "",
                    "evidence_ids": [evidence_id],
                }
            )
        experiences.append(
            {
                "id": role["id"],
                "company": role["company"],
                "title": role["title"],
                "location": role["location"],
                "startDate": role["startDate"],
                "endDate": role["endDate"],
                "isCurrent": role["isCurrent"],
                "bullets": bullets,
                "stack": stack,
            }
        )
    skills = []
    for index, (name, category) in enumerate(_SKILLS, start=1):
        evidence_id = f"source:skill-{index}"
        evidence.append({"id": evidence_id, "type": "source", "text": name})
        skills.append(
            {
                "id": f"skill-{index}",
                "name": name,
                "category": category,
                "evidenceIds": [evidence_id],
            }
        )
    languages = []
    for index, (name, proficiency) in enumerate(_LANGUAGES, start=1):
        evidence_id = f"source:language-{index}"
        evidence.append({"id": evidence_id, "type": "source", "text": f"{name} {proficiency}"})
        languages.append(
            {
                "id": f"language-{index}",
                "name": name,
                "proficiency": proficiency,
                "evidenceIds": [evidence_id],
            }
        )
    return {
        "schemaVersion": "1.0",
        "id": "master-1",
        "language": "en",
        "basics": {
            "fullName": "Mira Keller",
            "headline": "Backend Developer",
            "email": "mira.keller@example.com",
            "phone": "+41 44 555 01 23",
            "location": "Zurich, Switzerland",
            "workAuthorization": "Swiss Permit B",
            "linkedin": "https://www.linkedin.com/in/mira-keller-example",
            "github": "https://github.com/mira-keller-example",
        },
        "summary": {
            "text": "Backend developer who builds Python services and data pipelines.",
            "evidenceIds": ["source:summary"],
        },
        "experiences": experiences,
        "skills": skills,
        "education": [
            {
                "id": "education-1",
                "institution": "Example University of Applied Sciences",
                "credential": "BSc",
                "fieldOfStudy": "Computer Science",
                "location": "Zurich",
                "startDate": "2021",
                "endDate": "2025",
                "details": [
                    {
                        "id": "education-detail-1",
                        "text": "Thesis on streaming data pipelines.",
                        "evidenceIds": ["source:education"],
                    }
                ],
            }
        ],
        "languages": languages,
        "evidence": evidence,
        "sectionOrder": ["summary", "experience", "education", "languages", "skills"],
    }


def master_resume(*, extra_bullets_per_role: int = 0) -> MasterResume:
    return MasterResume.model_validate(
        master_resume_payload(extra_bullets_per_role=extra_bullets_per_role)
    )


def final_resume(*, extra_bullets_per_role: int = 0, language: str = "en") -> FinalResume:
    """The master content as a renderable tailored resume, without any rewriting."""
    master = master_resume_payload(extra_bullets_per_role=extra_bullets_per_role)
    experiences = [
        {
            "id": f"tailored-{role['id']}",
            "masterExperienceId": role["id"],
            "company": role["company"],
            "title": role["title"],
            "location": role["location"],
            "period": f"{role['startDate']} - {role['endDate'] or 'Present'}",
            "bullets": role["bullets"],
        }
        for role in master["experiences"]
    ]
    return FinalResume.model_validate(
        {
            "schemaVersion": "1.0",
            "id": "tailored-1",
            "masterResumeId": master["id"],
            "targetJobId": "job-1",
            "language": language,
            "basics": master["basics"],
            "summary": master["summary"],
            "experiences": experiences,
            "skills": master["skills"],
            "education": master["education"],
            "languages": master["languages"],
            "sectionOrder": master["sectionOrder"],
            "evidence": master["evidence"],
        }
    )


def cover_letter_payload(*, language: str = "en") -> dict[str, Any]:
    return {
        "id": "letter-1",
        "targetJobId": "job-1",
        "language": language,
        "recipient": "Northwind Analytics AG\nHiring Team\nLimmatstrasse 1\n8005 Zurich",
        "subject": "Application for Backend Engineer (Python)",
        "salutation": "Dear Hiring Team,",
        "paragraphs": [
            {
                "text": "Your posting for a Backend Engineer describes the work I do today: "
                "Python services with FastAPI and PostgreSQL that process retail data.",
                "evidenceIds": ["profile:role-atlas-achievement-1"],
            },
            {
                "text": "At Atlas Data GmbH I cut report generation time by 40% and built "
                "ingestion pipelines on Kubernetes that process 2 TB per month.",
                "evidenceIds": ["profile:role-atlas-achievement-2"],
            },
            {
                "text": "I would welcome a conversation about your data platform.",
                "evidenceIds": [],
            },
        ],
        "closing": "Kind regards,",
        "signature": "Mira Keller",
    }
