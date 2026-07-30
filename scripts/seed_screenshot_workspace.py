#!/usr/bin/env python3
"""Seed the isolated Rufina screenshot workspace with deterministic demo data."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.core.database import SessionLocal
from app.core.identity import DEFAULT_OWNER_ID, current_owner_id
from app.core.settings import Settings, get_settings
from app.models.applications import (
    StoredApplicationEventRecord,
    StoredApplicationRecord,
)
from app.models.jobs import (
    JobMatchFeedbackRecord,
    JobMatchRecord,
    StoredJobRecord,
)
from app.models.privacy import AiPrivacySettingsRecord
from app.models.profile import ProfilePayload, ProfileRecord
from app.services.ai_match import MATCHER_VERSION, MATCH_PROMPT_VERSION, WEIGHTS
from app.services.candidate_snapshot import get_candidate_match_snapshot
from app.services.job_match_store import build_match_record

DEMO_JOB_PREFIX = "manual-job-demo-"
DEMO_APPLICATION_PREFIX = "application-manual-job-demo-"
DEMO_EVENT_PREFIX = "demo-event-"


@dataclass(frozen=True)
class ScreenshotFixture:
    profile: dict[str, Any]
    jobs: list[dict[str, Any]]
    applications: list[dict[str, Any]]
    events: list[dict[str, Any]]


def iso_at(now: datetime, *, days: int = 0, hours: int = 0) -> str:
    return (now + timedelta(days=days, hours=hours)).isoformat()


def build_demo_resume_data_url() -> str:
    """Return a tiny valid one-page PDF without checking in personal files."""
    text = "Maya Keller - Senior Product Designer - Demo Resume"
    content = f"BT /F1 18 Tf 72 760 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        b"<< /Length " + str(len(content)).encode("ascii") + b" >>\nstream\n"
        + content
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    payload = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(payload))
        payload.extend(f"{number} 0 obj\n".encode("ascii"))
        payload.extend(body)
        payload.extend(b"\nendobj\n")

    xref_offset = len(payload)
    payload.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    payload.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        payload.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    payload.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    encoded = base64.b64encode(bytes(payload)).decode("ascii")
    return f"data:application/pdf;base64,{encoded}"


def build_profile(now: datetime) -> dict[str, Any]:
    experience = [
        {
            "id": "demo-experience-northstar",
            "title": "Senior Product Designer",
            "company": "Northstar Studio",
            "employment_type": "Full-time",
            "location": "Zurich, Switzerland",
            "start_date": "2022-03",
            "end_date": "",
            "is_current": True,
            "description": (
                "Led discovery and product design for a B2B analytics platform. "
                "Improved activation by 28% and reduced time-to-insight from 12 to 5 minutes."
            ),
        },
        {
            "id": "demo-experience-orbit",
            "title": "Product Designer",
            "company": "Orbit Works",
            "employment_type": "Full-time",
            "location": "Berlin, Germany",
            "start_date": "2019-01",
            "end_date": "2022-02",
            "is_current": False,
            "description": (
                "Designed onboarding, collaboration, and billing workflows for a SaaS product "
                "used by 18,000 teams. Established the first shared design system."
            ),
        },
    ]
    education = [
        {
            "id": "demo-education-zhdk",
            "institution": "Zurich University of the Arts",
            "credential": "BA",
            "field_of_study": "Interaction Design",
            "location": "Zurich, Switzerland",
            "start_date": "2015-09",
            "end_date": "2018-07",
            "is_current": False,
            "description": "Human-centred design, prototyping, and digital product strategy.",
        }
    ]
    preferences = {
        "desired_roles": ["Senior Product Designer", "Product Design Lead"],
        "seniority": ["Senior"],
        "locations": ["Zurich", "Remote Switzerland"],
        "work_formats": ["Hybrid", "Remote"],
        "employment_types": ["Full-time"],
        "industries": ["SaaS", "FinTech", "HealthTech"],
        "salary_min": "120000",
        "salary_currency": "CHF",
        "work_authorization": "Swiss permit",
        "swiss_permit_status": "C permit",
        "languages": ["English C1", "German B2"],
        "company_sizes": ["Scale-up", "Mid-size", "Enterprise"],
        "priorities": ["Learning", "Salary", "Remote"],
        "notes": "Interested in complex B2B products and mission-driven teams.",
        "no_preference": [],
    }
    return {
        "avatar_url": "/avatars/default-pug.png",
        "name": "Maya Keller",
        "current_role": "Lead Product Designer",
        "desired_role": "Product Design Lead",
        "location": "Zurich, Switzerland",
        "work_format": "Hybrid or remote",
        "headline": (
            "Product designer with 7+ years of experience turning complex workflows "
            "into clear, measurable customer outcomes."
        ),
        "linkedin": "linkedin.com/in/maya-keller-demo",
        "github": "",
        "portfolio": "maya-keller-demo.example",
        "personal_site": "",
        "experience": json.dumps(experience, ensure_ascii=False),
        "skills": "\n".join(
            [
                "Product Design",
                "User Research",
                "Figma",
                "Design Systems",
                "Prototyping",
                "Data-informed Design",
                "Workshop Facilitation",
                "Accessibility",
            ]
        ),
        "education": json.dumps(education, ensure_ascii=False),
        "job_preferences": json.dumps(preferences, ensure_ascii=False),
        "dealbreakers": "No onsite-only roles\nNo unpaid assignments longer than four hours",
        "additional_notes": "Available with one month's notice.",
        "documents": "",
        "resume_file_name": "Maya_Keller_Demo_Resume.pdf",
        "resume_file_size": "1 KB",
        "resume_updated_at": iso_at(now, days=-3),
        "resume_data_url": build_demo_resume_data_url(),
    }


def demo_job(
    now: datetime,
    *,
    slug: str,
    company: str,
    title: str,
    location: str,
    salary: str,
    posted: str,
    match: int,
    overview: str,
    skills: list[str],
    requirements: list[str],
    days_added: int,
) -> dict[str, Any]:
    job_id = f"{DEMO_JOB_PREFIX}{slug}"
    return {
        "id": job_id,
        "company": company,
        "title": title,
        "location": location,
        "type": "Full-time",
        "salary": salary,
        "posted": posted,
        "experience": "5+ years",
        "department": "Product Design",
        "match": match,
        "logo": "manual",
        "overview": overview,
        "responsibilities": [
            "Own discovery and product design from problem framing through delivery",
            "Partner closely with product, engineering, data, and customer teams",
            "Use qualitative and quantitative evidence to evaluate outcomes",
        ],
        "requirements": requirements,
        "skills": skills,
        "salaryAverage": salary,
        "salaryMin": salary.split("–")[0].strip(),
        "salaryMax": salary.split("–")[-1].strip(),
        "recommendations": [],
        "companyInfo": (
            f"{company} is a fictional company included only in Rufina's screenshot fixture."
        ),
        "reviews": [
            "Thoughtful product culture with direct access to customers.",
            "Cross-functional teams have clear ownership and regular design critique.",
        ],
        "similarJobs": [],
        "addedAt": iso_at(now, days=days_added),
    }


def build_jobs(now: datetime) -> list[dict[str, Any]]:
    return [
        demo_job(
            now,
            slug="novara",
            company="Novara",
            title="Senior Product Designer",
            location="Zurich · Hybrid",
            salary="CHF 125k – CHF 145k",
            posted="2h ago",
            match=94,
            overview=(
                "Shape a collaborative analytics workspace that helps operations teams "
                "understand complex data and act with confidence."
            ),
            skills=["Figma", "User Research", "Design Systems", "B2B SaaS"],
            requirements=[
                "5+ years of end-to-end product design experience",
                "Strong portfolio of complex B2B workflows",
                "Experience partnering with data and engineering teams",
            ],
            days_added=0,
        ),
        demo_job(
            now,
            slug="cirruspay",
            company="CirrusPay",
            title="Product Designer",
            location="Remote · Switzerland",
            salary="CHF 118k – CHF 138k",
            posted="6h ago",
            match=88,
            overview=(
                "Design transparent payment and treasury experiences for growing "
                "European businesses."
            ),
            skills=["Product Design", "FinTech", "Prototyping", "Accessibility"],
            requirements=[
                "Experience designing regulated or financial products",
                "Excellent interaction design and prototyping skills",
                "Ability to communicate decisions with senior stakeholders",
            ],
            days_added=-1,
        ),
        demo_job(
            now,
            slug="alpine-grid",
            company="Alpine Grid",
            title="Senior UX Designer",
            location="Baden · Hybrid",
            salary="CHF 120k – CHF 140k",
            posted="1d ago",
            match=83,
            overview=(
                "Simplify planning and monitoring tools used by renewable-energy operators "
                "across Switzerland."
            ),
            skills=["UX Design", "User Research", "Data Visualization", "Workshops"],
            requirements=[
                "Strong experience with data-rich enterprise interfaces",
                "Ability to run research with specialist users",
                "Professional English; German is an advantage",
            ],
            days_added=-2,
        ),
        demo_job(
            now,
            slug="luma-health",
            company="Luma Health",
            title="Senior Product Designer",
            location="Basel · Hybrid",
            salary="CHF 115k – CHF 135k",
            posted="2d ago",
            match=77,
            overview=(
                "Improve care-team coordination through accessible workflows for clinics "
                "and patients."
            ),
            skills=["Product Design", "Accessibility", "Design Systems", "HealthTech"],
            requirements=[
                "Portfolio demonstrating accessible product design",
                "Experience working across web and mobile surfaces",
                "Comfort operating in a regulated environment",
            ],
            days_added=-3,
        ),
        demo_job(
            now,
            slug="fieldnote",
            company="Fieldnote",
            title="Design Systems Designer",
            location="Remote · Europe",
            salary="CHF 110k – CHF 130k",
            posted="3d ago",
            match=71,
            overview=(
                "Evolve a multi-brand design system used by distributed product teams "
                "across Europe."
            ),
            skills=["Design Systems", "Figma", "Accessibility", "Documentation"],
            requirements=[
                "Hands-on experience maintaining a production design system",
                "Strong component, token, and documentation practice",
                "Comfort collaborating with frontend platform teams",
            ],
            days_added=-4,
        ),
        demo_job(
            now,
            slug="greenline",
            company="Greenline Mobility",
            title="Product Design Lead",
            location="Bern · On-site",
            salary="CHF 135k – CHF 155k",
            posted="5d ago",
            match=64,
            overview=(
                "Lead design for fleet-management products supporting lower-emission "
                "urban transport."
            ),
            skills=["Design Leadership", "Mobility", "Product Strategy", "Research"],
            requirements=[
                "2+ years leading or managing product designers",
                "Experience defining multi-year product design strategy",
                "Availability for four on-site days each week",
            ],
            days_added=-6,
        ),
    ]


def build_applications(
    now: datetime,
    jobs: list[dict[str, Any]],
    resume_data_url: str,
) -> list[dict[str, Any]]:
    by_slug = {job["id"].removeprefix(DEMO_JOB_PREFIX): job for job in jobs}
    resume = {
        "id": "demo-application-resume",
        "title": "Maya Keller Resume",
        "fileName": "Maya_Keller_Demo_Resume.pdf",
        "fileSize": "1 KB",
        "fileType": "application/pdf",
        "uploadedAt": iso_at(now, days=-12),
        "dataUrl": resume_data_url,
    }
    application_specs = [
        (
            "novara",
            "interview",
            -12,
            "Prepare the portfolio walkthrough for the hiring panel.",
            "Recruiter screen completed. The team wants to discuss the analytics case study.",
        ),
        (
            "cirruspay",
            "assessment",
            -8,
            "Submit the product critique by Friday.",
            "The assignment is limited to a two-hour written critique.",
        ),
        (
            "alpine-grid",
            "applied",
            -4,
            "Follow up with the recruiter next week.",
            "Applied through the company careers page.",
        ),
        (
            "luma-health",
            "rejected",
            -20,
            "Archive the application.",
            "Role was filled internally after the first interview.",
        ),
    ]
    return [
        {
            "id": f"{DEMO_APPLICATION_PREFIX}{slug}",
            "job": by_slug[slug],
            "status": status,
            "appliedAt": iso_at(now, days=days_ago),
            "nextStep": next_step,
            "notes": notes,
            "documents": [resume],
        }
        for slug, status, days_ago, next_step, notes in application_specs
    ]


def build_events(now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": f"{DEMO_EVENT_PREFIX}novara-screen",
            "applicationId": f"{DEMO_APPLICATION_PREFIX}novara",
            "type": "screening",
            "status": "completed",
            "outcome": "positive",
            "title": "Recruiter screen · Novara",
            "startsAt": iso_at(now, days=-2, hours=-1),
            "durationMinutes": 30,
            "timezone": "Europe/Zurich",
            "location": "Video call",
            "notes": "Discussed role scope, team structure, and availability.",
        },
        {
            "id": f"{DEMO_EVENT_PREFIX}novara-interview",
            "applicationId": f"{DEMO_APPLICATION_PREFIX}novara",
            "type": "interview",
            "status": "scheduled",
            "title": "Portfolio interview · Novara",
            "startsAt": iso_at(now, days=2, hours=2),
            "durationMinutes": 60,
            "timezone": "Europe/Zurich",
            "location": "Video call",
            "notes": "Present the B2B analytics case study and design-system work.",
        },
        {
            "id": f"{DEMO_EVENT_PREFIX}cirruspay-assessment",
            "applicationId": f"{DEMO_APPLICATION_PREFIX}cirruspay",
            "type": "assessment",
            "status": "scheduled",
            "title": "Product critique deadline · CirrusPay",
            "startsAt": iso_at(now, days=5, hours=4),
            "durationMinutes": 120,
            "timezone": "Europe/Zurich",
            "location": "Online",
            "notes": "Submit the written critique and annotated flow.",
        },
        {
            "id": f"{DEMO_EVENT_PREFIX}alpine-follow-up",
            "applicationId": f"{DEMO_APPLICATION_PREFIX}alpine-grid",
            "type": "follow_up",
            "status": "scheduled",
            "title": "Follow up · Alpine Grid",
            "startsAt": iso_at(now, days=8, hours=1),
            "durationMinutes": 15,
            "timezone": "Europe/Zurich",
            "location": "",
            "notes": "Send a short follow-up to the recruiter.",
        },
    ]


def build_fixture(now: datetime | None = None) -> ScreenshotFixture:
    resolved_now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    profile = build_profile(resolved_now)
    jobs = build_jobs(resolved_now)
    applications = build_applications(
        resolved_now,
        jobs,
        profile["resume_data_url"],
    )
    events = build_events(resolved_now)
    return ScreenshotFixture(
        profile=profile,
        jobs=jobs,
        applications=applications,
        events=events,
    )


def weighted_breakdown(score: int) -> dict[str, int]:
    exact = {key: score * weight / 100 for key, weight in WEIGHTS.items()}
    result = {key: int(value) for key, value in exact.items()}
    missing = score - sum(result.values())
    ranked = sorted(
        WEIGHTS,
        key=lambda key: exact[key] - result[key],
        reverse=True,
    )
    for key in ranked[:missing]:
        result[key] += 1
    return result


def demo_ai_match(
    job: dict[str, Any],
    *,
    profile_hash: str,
    now: datetime,
) -> dict[str, Any]:
    vacancy_hash = hashlib.sha256(
        json.dumps(job, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    cache_key = hashlib.sha256(
        f"{profile_hash}:{vacancy_hash}:screenshot-fixture-v1".encode()
    ).hexdigest()
    score = int(job["match"])
    return {
        "version": MATCHER_VERSION,
        "profileHash": profile_hash,
        "vacancyHash": vacancy_hash,
        "model": "screenshot-fixture",
        "backend": "openai_api",
        "promptVersion": MATCH_PROMPT_VERSION,
        "cacheKey": cache_key,
        "source": "openai_api",
        "score": score,
        "confidence": "high" if score >= 80 else "medium",
        "breakdown": weighted_breakdown(score),
        "reasons": [
            f"Strong overlap with {job['skills'][0]} and {job['skills'][1]}",
            "Relevant experience simplifying complex B2B workflows",
            "Location and working model align with the candidate's preferences",
        ],
        "gaps": (
            ["Leadership scope should be confirmed during the interview"]
            if "Lead" in job["title"]
            else ["Industry-specific experience is not fully demonstrated"]
        ),
        "heuristicScore": score,
        "updatedAt": iso_at(now, hours=-1),
    }


def delete_existing_demo_records(db: Session) -> None:
    db.query(StoredApplicationEventRecord).filter(
        StoredApplicationEventRecord.id.like(f"{DEMO_EVENT_PREFIX}%")
    ).delete(synchronize_session=False)
    db.query(StoredApplicationRecord).filter(
        StoredApplicationRecord.id.like(f"{DEMO_APPLICATION_PREFIX}%")
    ).delete(synchronize_session=False)
    db.query(JobMatchFeedbackRecord).filter(
        JobMatchFeedbackRecord.job_id.like(f"{DEMO_JOB_PREFIX}%")
    ).delete(synchronize_session=False)
    db.query(JobMatchRecord).filter(
        JobMatchRecord.job_id.like(f"{DEMO_JOB_PREFIX}%")
    ).delete(synchronize_session=False)
    db.query(StoredJobRecord).filter(
        StoredJobRecord.id.like(f"{DEMO_JOB_PREFIX}%")
    ).delete(synchronize_session=False)


def seed_database(
    db: Session,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, int | str]:
    fixture = build_fixture(now)
    profile_payload = ProfilePayload.model_validate(fixture.profile)
    resolved_now = (now or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    owner_token = current_owner_id.set(DEFAULT_OWNER_ID)
    try:
        delete_existing_demo_records(db)

        profile_record = db.get(ProfileRecord, "default")
        if profile_record:
            profile_record.data = profile_payload.model_dump()
        else:
            db.add(ProfileRecord(id="default", data=profile_payload.model_dump()))

        snapshot = get_candidate_match_snapshot(db, profile=profile_payload)
        for job in fixture.jobs:
            db.add(
                StoredJobRecord(
                    id=job["id"],
                    data=job,
                    status="active",
                )
            )
            db.add(
                build_match_record(
                    job["id"],
                    snapshot.profile_hash,
                    demo_ai_match(
                        job,
                        profile_hash=snapshot.profile_hash,
                        now=resolved_now,
                    ),
                )
            )

        for application in fixture.applications:
            db.add(
                StoredApplicationRecord(
                    id=application["id"],
                    data=application,
                )
            )

        for event in fixture.events:
            db.add(
                StoredApplicationEventRecord(
                    id=event["id"],
                    application_id=event["applicationId"],
                    data=event,
                )
            )

        privacy = db.get(AiPrivacySettingsRecord, DEFAULT_OWNER_ID)
        if privacy:
            privacy.consent_version = settings.ai_consent_version
            privacy.consent_backend = settings.ai_backend_mode
            privacy.consented_at = resolved_now
            privacy.retention_days = 30
            privacy.updated_at = resolved_now
        else:
            db.add(
                AiPrivacySettingsRecord(
                    owner_id=DEFAULT_OWNER_ID,
                    consent_version=settings.ai_consent_version,
                    consent_backend=settings.ai_backend_mode,
                    consented_at=resolved_now,
                    retention_days=30,
                    last_ai_activity_at=None,
                    ai_data_expires_at=None,
                    updated_at=resolved_now,
                )
            )

        db.commit()
        return {
            "profile": profile_payload.name,
            "jobs": len(fixture.jobs),
            "applications": len(fixture.applications),
            "events": len(fixture.events),
        }
    except Exception:
        db.rollback()
        raise
    finally:
        current_owner_id.reset(owner_token)


def main() -> None:
    if os.environ.get("RUFINA_SCREENSHOT_MODE") != "1":
        raise SystemExit(
            "Refusing to seed: RUFINA_SCREENSHOT_MODE=1 is required. "
            "Run `pnpm screenshots:seed` instead."
        )

    with SessionLocal() as db:
        summary = seed_database(db, get_settings())
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
