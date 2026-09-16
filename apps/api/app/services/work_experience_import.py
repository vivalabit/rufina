"""Attach immutable CV provenance and stable employer-local IDs to partial imports."""
from collections import Counter

from app.models.profile import ImportedExperienceEntry
from app.models.work_experience import DETAIL_MODELS
from app.services.candidate_profile import canonical_hash, stable_id


def source_experience_entries(entries: list[ImportedExperienceEntry], source_id: str) -> list[ImportedExperienceEntry]:
    result = []
    occurrences: Counter[str] = Counter()
    for entry in entries:
        data = entry.model_dump(mode="json")
        identity = canonical_hash({key: data[key] for key in ("company", "title", "start_date", "end_date", "is_current")})
        occurrences[identity] += 1
        data["id"] = stable_id("cv-experience", f"{source_id}:{identity}:{occurrences[identity]}")
        data["source_ids"] = [source_id]
        for block in DETAIL_MODELS:
            seen: Counter[str] = Counter()
            for detail in data[block]:
                content = {key: value for key, value in detail.items() if key not in ("id", "source_ids", "evidence_ids")}
                fingerprint = canonical_hash(content)
                seen[fingerprint] += 1
                detail["id"] = stable_id("cv-detail", f"{data['id']}:{block}:{fingerprint}:{seen[fingerprint]}")
                detail["source_ids"] = [source_id]
                # Partial extraction has no fragment catalog. The retained CV is
                # provenance; confirmation via profile save supplies current evidence.
                detail["evidence_ids"] = []
        result.append(ImportedExperienceEntry.model_validate(data))
    return result
