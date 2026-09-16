"""Lossless adapters between candidate data, the existing forms and resume consumers.

There is no persisted resume projection. ProfileRecord and its versions own all
candidate data; MasterResume is retained as an import/document wire contract.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from app.models.profile import ProfilePayload
from app.models.resume import MasterResume

FORM_FIELDS = frozenset({
    "avatar_url", "name", "current_role", "desired_role", "location", "work_format",
    "headline", "linkedin", "github", "portfolio", "personal_site", "experience",
    "skills", "education", "job_preferences", "dealbreakers", "additional_notes",
    "resume_file_name", "resume_file_size", "resume_updated_at",
})


def canonical_hash(data: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(
        data, ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode()).hexdigest()


def stable_id(kind: str, value: str) -> str:
    return f"{kind}:{hashlib.sha256(value.encode()).hexdigest()[:24]}"


def entries(value: str, section: str) -> list[dict[str, Any]]:
    if not value.strip():
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
            return deepcopy(parsed)
    except (ValueError, TypeError):
        pass
    title_field = "title" if section == "experience" else "credential"
    return [
        {"id": f"legacy-{section}-{index}", title_field: text, "description": text}
        for index, text in enumerate(value.splitlines()) if text.strip()
    ]


def encode_entries(items: list[dict[str, Any]]) -> str:
    return json.dumps(items, ensure_ascii=False)


def apply_form_update(current: ProfilePayload, submitted: ProfilePayload) -> ProfilePayload:
    """Old clients cannot erase fields they do not know about.

    A changed description is authoritative user text. Source references remain
    provenance, while generation derives fresh profile evidence for edited text.
    """
    data = current.model_dump(mode="json")
    incoming = submitted.model_dump(mode="json")
    for field in FORM_FIELDS | submitted.model_fields_set:
        if field in incoming:
            data[field] = incoming[field]
    data["import_source_ids"] = list(dict.fromkeys([*current.import_source_ids, *submitted.import_source_ids]))
    for section in ("experience", "education"):
        if data[section] == getattr(current, section):
            continue
        old = {item.get("id"): item for item in entries(getattr(current, section), section)}
        try:
            parsed = json.loads(data[section])
        except ValueError:
            continue
        if not isinstance(parsed, list):
            continue
        merged = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            prior = old.get(item.get("id"), {})
            # Preserve provenance omitted by older clients, but not old wording.
            merged.append({**prior, **item})
        data[section] = encode_entries(merged)
    return ProfilePayload.model_validate(data)


def profile_resume(profile: ProfilePayload, profile_id: str) -> MasterResume:
    """Derive the document/grounding contract from a complete profile version."""
    evidence = [item.model_dump(mode="json", by_alias=True) for item in profile.evidence]
    known = {item["id"] for item in evidence}

    def proof(text: str, key: str) -> list[str]:
        identifier = stable_id("profile", f"{key}:{text}")
        if identifier not in known:
            evidence.append({"id": identifier, "type": "profile", "text": text})
            known.add(identifier)
        return [identifier]

    def bullets(text: str, key: str) -> list[dict[str, Any]]:
        # Split only to satisfy the document contract, never truncate source text.
        return [{"id": stable_id("item", f"{key}:{index}"), "text": part,
                 "evidenceIds": proof(part, f"{key}:{index}")}
                for index, part in enumerate(text[i:i + 20_000]
                                             for i in range(0, len(text), 20_000))
                if part.strip()]

    experiences = []
    for item in entries(profile.experience, "experience"):
        identifier = item.get("id") or stable_id("experience", json.dumps(item, sort_keys=True))
        # Incomplete legacy entries still remain in the full profile context and
        # evidence catalog; do not invent an employer or title to render them.
        description = str(item.get("description") or "")
        if not item.get("company") or not item.get("title"):
            bullets(description or str(item.get("title") or ""), identifier)
            continue
        experiences.append({
            "id": identifier, "company": item["company"], "title": item["title"],
            "employmentType": item.get("employment_type", ""),
            "location": item.get("location", ""), "startDate": item.get("start_date", ""),
            "endDate": "" if item.get("is_current") else item.get("end_date", ""),
            "isCurrent": bool(item.get("is_current")),
            "bullets": bullets(description or f'{item["title"]} at {item["company"]}', identifier),
        })
    education = []
    for item in entries(profile.education, "education"):
        identifier = item.get("id") or stable_id("education", json.dumps(item, sort_keys=True))
        description = str(item.get("description") or "")
        if not item.get("institution") or not item.get("credential"):
            bullets(description or str(item.get("credential") or ""), identifier)
            continue
        education.append({
            "id": identifier, "institution": item["institution"], "credential": item["credential"],
            "fieldOfStudy": item.get("field_of_study", ""), "location": item.get("location", ""),
            "startDate": item.get("start_date", ""), "endDate": item.get("end_date", ""),
            "details": bullets(description, identifier),
        })
    skills = []
    for name in dict.fromkeys(line.strip() for line in profile.skills.splitlines() if line.strip()):
        metadata = profile.skill_metadata.get(name.casefold(), {})
        skills.append({"id": stable_id("skill", name.casefold()), "name": name,
                       "category": metadata.get("category", ""),
                       "evidenceIds": proof(name, "skill")})
    additional = [s.model_dump(mode="json", by_alias=True) for s in profile.additional_sections]
    # Notes are candidate-provided facts too, available for both documents.
    for field in ("additional_notes", "personal_site"):
        text = getattr(profile, field)
        if text.strip():
            additional.append({"id": f"profile-{field}", "title": field.replace("_", " "),
                               "items": bullets(text, field)})
    summary = profile.summary.model_dump(mode="json", by_alias=True) if profile.summary else None
    if summary is None and profile.headline.strip():
        summary = {"text": profile.headline, "evidenceIds": proof(profile.headline, "headline")}
    data = {
        "id": profile_id, "language": profile.resume_language,
        "basics": {"fullName": profile.name or "Candidate", "headline": profile.current_role,
                   "email": profile.email, "phone": profile.phone, "location": profile.location,
                   "workAuthorization": profile.work_authorization, "linkedin": profile.linkedin,
                   "github": profile.github, "portfolio": profile.portfolio},
        "summary": summary, "experiences": experiences, "skills": skills, "education": education,
        "projects": [i.model_dump(mode="json", by_alias=True) for i in profile.projects],
        "certifications": [i.model_dump(mode="json", by_alias=True) for i in profile.certifications],
        "languages": [i.model_dump(mode="json", by_alias=True) for i in profile.languages],
        "additionalSections": additional, "evidence": evidence,
    }
    data["sectionOrder"] = [name for name, key in (
        ("summary", "summary"), ("experience", "experiences"), ("skills", "skills"),
        ("education", "education"), ("projects", "projects"), ("certifications", "certifications"),
        ("languages", "languages"), ("additional", "additionalSections"),
    ) if data[key]]
    return MasterResume.model_validate(data)
