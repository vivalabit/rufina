from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.profile import ProfilePayload
from app.models.resume import ConfirmedProfileFactResponse
from app.services.candidate_profile import encode_entries, entries
from app.services.profile_migration import ensure_candidate_profile
from app.services.profile_versions import StaleProfileRevisionError, update_profile_data


class ProfileFactSyncError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def confirm_profile_fact(
    db: Session, *, master_resume_id: str, fact_text: str, expected_version: int,
    idempotency_key: str, source_run_id: str | None = None, experience_id: str | None = None,
) -> ConfirmedProfileFactResponse:
    """Save an explicit confirmation in the candidate's versioned profile."""
    profile = ensure_candidate_profile(db)
    payload = ProfilePayload.model_validate(profile.data)
    if master_resume_id != profile.id:
        raise ProfileFactSyncError('Candidate profile was not found', code='not_found')
    existing = next((item for item in payload.confirmed_facts
                     if item['idempotency_key'] == idempotency_key), None)
    if existing:
        if (existing['fact_text'], existing['source_run_id'], existing.get('experience_id')) != (
            fact_text, source_run_id, experience_id,
        ):
            raise ProfileFactSyncError('Idempotency key was already used for another fact', code='idempotency_conflict')
        return ConfirmedProfileFactResponse.model_validate_json(json.dumps(existing['response']))
    if profile.revision != expected_version:
        raise ProfileFactSyncError('Profile changed after the fact was reviewed', code='stale_version')
    data = payload.model_dump(mode='json')
    fact_id = uuid4().hex
    evidence_id = f'confirmation:{fact_id}'
    response = ConfirmedProfileFactResponse(
        id=fact_id, master_resume_id=profile.id, from_version=profile.revision,
        to_version=profile.revision + 1, evidence_id=evidence_id, fact_text=fact_text,
        source_run_id=source_run_id, created_at=datetime.now(UTC),
    )
    data['evidence'].append({'id': evidence_id, 'type': 'confirmation', 'text': fact_text,
                             'source_id': source_run_id})
    if experience_id:
        experiences = entries(payload.experience, 'experience')
        experience = next((item for item in experiences if item.get('id') == experience_id), None)
        if experience is None:
            raise ProfileFactSyncError('Target experience was not found', code='not_found')
        description = experience.get('description', '')
        experience['description'] = f'{description}\n{fact_text}' if description else fact_text
        experience['evidence_ids'] = [*experience.get('evidence_ids', []), evidence_id]
        data['experience'] = encode_entries(experiences)
    else:
        section = next((item for item in data['additional_sections'] if item['id'] == 'confirmed-facts'), None)
        if section is None:
            section = {'id': 'confirmed-facts', 'title': 'Confirmed facts', 'items': []}
            data['additional_sections'].append(section)
        section['items'].append({'id': f'confirmed-fact:{fact_id}', 'text': fact_text,
                                 'evidence_ids': [evidence_id]})
    data['confirmed_facts'].append({
        'idempotency_key': idempotency_key, 'experience_id': experience_id,
        'fact_text': fact_text, 'source_run_id': source_run_id,
        'response': response.model_dump(mode='json', by_alias=True),
    })
    validated = ProfilePayload.model_validate(data)
    try:
        update_profile_data(db, profile, data=validated.model_dump(mode='json'), reason='confirmed_fact')
        db.commit()
    except StaleProfileRevisionError as exc:
        raise ProfileFactSyncError('Profile changed after the fact was reviewed', code='stale_version') from exc
    return response


__all__ = ['ProfileFactSyncError', 'confirm_profile_fact']
