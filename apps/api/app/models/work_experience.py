"""Optional, employer-local work details shared by profile forms and CV imports."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

DetailText = Annotated[str, Field(max_length=2_000_000)]


class WorkDetail(BaseModel):
    id: str = Field(default="", max_length=160, pattern=r"^[A-Za-z0-9._:/-]*$")
    source_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    model_config = ConfigDict(extra="forbid")


class WorkTechnology(WorkDetail):
    technology: DetailText = ""
    context: DetailText = ""


class WorkResponsibility(WorkDetail):
    responsibility: DetailText = ""
    decisions: DetailText = ""


class WorkProject(WorkDetail):
    name: DetailText = ""
    description: DetailText = ""
    project_type: DetailText = ""
    team: DetailText = ""
    systems: DetailText = ""
    users: DetailText = ""
    load: DetailText = ""


DETAIL_MODELS = {"stack": WorkTechnology, "responsibilities": WorkResponsibility, "projects": WorkProject}


def normalize_work_details(entry: dict[str, Any]) -> dict[str, Any]:
    """Validate present blocks only; omitted blocks remain omitted for old clients."""
    result = deepcopy(entry)
    identifiers: set[str] = set()
    employer = str(entry.get("id") or json.dumps(
        {key: entry.get(key) for key in ("company", "title", "start_date", "end_date")}, sort_keys=True,
    ))
    for block, model in DETAIL_MODELS.items():
        if block not in entry:
            continue
        if not isinstance(entry[block], list):
            raise ValueError(f"{block} must be a list")  # noqa: TRY004 - Pydantic validation error
        result[block] = []
        for index, value in enumerate(entry[block]):
            detail = model.model_validate(value).model_dump(exclude_unset=True)
            if not detail.get("id"):
                digest = hashlib.sha256(f"{employer}:{block}:{index}:{json.dumps(detail, sort_keys=True)}".encode())
                detail["id"] = f"work-{block}:{digest.hexdigest()[:24]}"
            if detail["id"] in identifiers:
                raise ValueError("Work detail IDs must be unique within an experience")
            identifiers.add(detail["id"])
            result[block].append(detail)
    return result


def validate_experience_json(value: str) -> str:
    try:
        parsed = json.loads(value)
    except ValueError:
        return value  # Historical free-text profiles are still valid.
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        return value
    normalized = [normalize_work_details(item) for item in parsed]
    return value if normalized == parsed else json.dumps(normalized, ensure_ascii=False)


def merge_work_detail_update(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = {**previous, **incoming}
    for block in DETAIL_MODELS:
        if block not in incoming:
            continue
        old = {item["id"]: item for item in previous.get(block, [])}
        # Explicit [] deletes the block; missing per-item metadata is preserved.
        result[block] = [{**old.get(item["id"], {}), **item} for item in incoming[block]]
    return result


def merge_imported_work_details(current: list[dict], incoming: list[dict]) -> list[dict]:
    """Deduplicate exact details; keep differing wording as separate, reviewable facts."""
    result = deepcopy(current)

    def content(item: dict) -> dict:
        return {key: value for key, value in item.items() if key not in ("id", "source_ids", "evidence_ids") and value}

    for item in incoming:
        match = next((old for old in result if old["id"] == item["id"] or content(old) == content(item)), None)
        if match is None:
            result.append(deepcopy(item))
        else:
            # A user's correction to an imported item wins on repeated import.
            for key in ("source_ids", "evidence_ids"):
                if key in match or key in item:
                    match[key] = list(dict.fromkeys([*match.get(key, []), *item.get(key, [])]))
    return result
