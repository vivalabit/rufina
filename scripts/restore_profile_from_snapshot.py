#!/usr/bin/env python3
"""Restore a Rufina profile from the richest stored candidate-match snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

API_ROOT = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.models.profile import (  # noqa: E402
    CandidateMatchSnapshotRecord,
    ProfilePayload,
)
from app.services.profile_versions import (  # noqa: E402
    create_profile_record,
    get_profile_record,
    update_profile_data,
)


def list_value(data: dict[str, Any], field: str) -> list[str]:
    value = data.get(field)
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def snapshot_richness(record: CandidateMatchSnapshotRecord) -> int:
    data = record.data
    return (
        len(list_value(data, "skills"))
        + 10 * len(data.get("experience") or [])
        + 5 * len(data.get("education") or [])
        + 2 * len(list_value(data, "roles"))
    )


def serialize_experience(data: dict[str, Any], snapshot_id: str) -> str:
    entries = []
    for index, raw_entry in enumerate(data.get("experience") or [], start=1):
        if not isinstance(raw_entry, dict):
            continue
        entries.append(
            {
                "id": f"restored-{snapshot_id}-experience-{index}",
                "title": str(raw_entry.get("title") or ""),
                "company": str(raw_entry.get("company") or ""),
                "employment_type": str(raw_entry.get("employment_type") or "Full-time"),
                "location": str(raw_entry.get("location") or ""),
                "start_date": str(raw_entry.get("start_date") or ""),
                "end_date": "" if raw_entry.get("is_current") else str(raw_entry.get("end_date") or ""),
                "is_current": bool(raw_entry.get("is_current")),
                "description": str(raw_entry.get("description") or ""),
            }
        )
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def serialize_education(data: dict[str, Any], snapshot_id: str) -> str:
    entries = []
    for index, raw_entry in enumerate(data.get("education") or [], start=1):
        if not isinstance(raw_entry, dict):
            continue
        entries.append(
            {
                "id": f"restored-{snapshot_id}-education-{index}",
                "institution": str(raw_entry.get("institution") or ""),
                "credential": str(raw_entry.get("credential") or ""),
                "field_of_study": str(raw_entry.get("field_of_study") or ""),
                "location": str(raw_entry.get("location") or ""),
                "start_date": str(raw_entry.get("start_date") or ""),
                "end_date": "" if raw_entry.get("is_current") else str(raw_entry.get("end_date") or ""),
                "is_current": bool(raw_entry.get("is_current")),
                "description": str(raw_entry.get("description") or ""),
            }
        )
    return json.dumps(entries, ensure_ascii=False, separators=(",", ":"))


def serialize_preferences(data: dict[str, Any]) -> str:
    work_authorization = str(data.get("work_authorization") or "").strip()
    swiss_permit_status = ""
    if work_authorization.lower().startswith("swiss permit"):
        swiss_permit_status = work_authorization[len("Swiss permit") :].strip()
        work_authorization = "Swiss permit"

    salary_min = data.get("salary_min")
    preferences = {
        "desired_roles": list_value(data, "roles"),
        "seniority": list_value(data, "seniority"),
        "locations": list_value(data, "locations"),
        "work_formats": list_value(data, "work_formats"),
        "employment_types": list_value(data, "employment_types"),
        "industries": list_value(data, "industries"),
        "salary_min": str(salary_min) if isinstance(salary_min, (int, float)) and salary_min > 0 else "",
        "salary_currency": str(data.get("salary_currency") or "CHF"),
        "work_authorization": work_authorization,
        "swiss_permit_status": swiss_permit_status,
        "languages": list_value(data, "languages"),
        "company_sizes": list_value(data, "company_sizes"),
        "priorities": list_value(data, "priorities"),
        "notes": str(data.get("preference_notes") or ""),
        "no_preference": list_value(data, "no_preference"),
    }
    return json.dumps(preferences, ensure_ascii=False, separators=(",", ":"))


def restore_payload(
    current: ProfilePayload,
    snapshot: CandidateMatchSnapshotRecord,
) -> ProfilePayload:
    data = snapshot.data
    locations = list_value(data, "locations")
    work_formats = list_value(data, "work_formats")
    return current.model_copy(
        update={
            "current_role": str(data.get("current_role") or ""),
            "desired_role": str(data.get("desired_role") or ""),
            "location": locations[0] if locations else current.location,
            "work_format": ", ".join(work_formats),
            "headline": str(data.get("headline") or ""),
            "experience": serialize_experience(data, snapshot.id),
            "skills": "\n".join(list_value(data, "skills")),
            "education": serialize_education(data, snapshot.id),
            "job_preferences": serialize_preferences(data),
            "dealbreakers": "\n".join(list_value(data, "dealbreakers")),
            "additional_notes": str(data.get("additional_notes") or ""),
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Persist the restored profile")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        snapshots = list(db.scalars(select(CandidateMatchSnapshotRecord)).all())
        if not snapshots:
            raise SystemExit("No candidate snapshots are available")
        snapshot = max(snapshots, key=snapshot_richness)
        profile_record = get_profile_record(db)
        current = ProfilePayload.model_validate(profile_record.data) if profile_record else ProfilePayload()
        restored = restore_payload(current, snapshot)

        print(
            json.dumps(
                {
                    "snapshot_created_at": snapshot.created_at.isoformat(),
                    "headline": restored.headline,
                    "skills": len(restored.skills.splitlines()),
                    "experience": len(json.loads(restored.experience)),
                    "education": len(json.loads(restored.education)),
                    "applied": args.apply,
                },
                ensure_ascii=False,
            )
        )
        if not args.apply:
            return 0

        if profile_record:
            update_profile_data(
                db,
                profile_record,
                data=restored.model_dump(),
                reason="snapshot_restore",
            )
        else:
            db.add(create_profile_record(restored.model_dump()))
        db.commit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
