"""Repeatable, owner-scoped backfill of legacy master data into profiles.

Legacy versions, source bytes and generation snapshots are read-only. Matching
requires a complete identity and exactly one candidate on each side. Conflicts
remain explicit provenance; existing manual values always take precedence.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import ProfilePayload, ProfileRecord
from app.models.resume import MasterResume, ResumeMasterRecord, ResumeMasterVersionRecord
from app.services.candidate_profile import canonical_hash, encode_entries, entries, stable_id
from app.services.profile_versions import (
    create_profile_record,
    get_profile_record,
    record_profile_version,
    update_profile_data,
)


def _normalized(value: Any) -> str:
    return ' '.join(str(value or '').casefold().split())


def _identity(item: dict, fields: tuple[str, ...]) -> tuple[str, ...] | None:
    values = tuple(_normalized('(current)' if field == 'end_date' and item.get('is_current') else item.get(field)) for field in fields)
    return values if all(values) else None


def _merge_text(current: str, incoming: str) -> str:
    if not incoming or incoming in current:
        return current
    if not current:
        return incoming
    # Keep the original description verbatim and append only missing paragraphs.
    additions = [line for line in incoming.splitlines() if line and line not in current.splitlines()]
    return current + ('\n' + '\n'.join(additions) if additions else '')


def merge_master_into_profile(
    profile: ProfilePayload, master: MasterResume, *, source_key: str,
    source_file_id: str | None, content_sha256: str,
) -> ProfilePayload:
    """Import missing facts without replacing user-authored values."""
    if any(item.get('key') == source_key for item in profile.sources):
        return profile
    data = profile.model_dump(mode='json')
    source: dict[str, Any] = {
        'key': source_key, 'master_id': master.id, 'source_file_id': source_file_id,
        'content_sha256': content_sha256, 'entry_map': {}, 'conflicts': [],
        'download_url': f'/profile/sources/{source_file_id}' if source_file_id else None,
    }
    # Imported IDs live in a stable namespace, so unrelated CVs cannot collide.
    def imported_id(value: str) -> str:
        return stable_id('import', f'{master.id}:{value}')

    raw = master.model_dump(mode='json', by_alias=True)
    evidence_map = {item['id']: f"{item['type']}:{imported_id(item['id'])}" for item in raw['evidence']}

    def remap(value: Any) -> Any:
        if isinstance(value, list):
            return [remap(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: remap(item) for key, item in value.items()}
        if 'id' in result:
            result['id'] = evidence_map.get(result['id'], imported_id(result['id']))
        if 'evidenceIds' in result:
            result['evidenceIds'] = [evidence_map[item] for item in value['evidenceIds']]
        if result.get('experienceId'):
            result['experienceId'] = imported_id(result['experienceId'])
        return result

    imported = remap(raw)
    for target, value in {
        'name': master.basics.full_name, 'current_role': master.basics.headline,
        'headline': master.summary.text if master.summary else master.basics.headline,
        'email': master.basics.email, 'phone': master.basics.phone,
        'location': master.basics.location, 'work_authorization': master.basics.work_authorization,
        'linkedin': master.basics.linkedin, 'github': master.basics.github,
        'portfolio': master.basics.portfolio,
    }.items():
        if not data[target]:
            data[target] = value
        elif value and data[target] != value:
            source['conflicts'].append({'field': target, 'imported_value': value})
    if not profile.sources:
        data['resume_language'] = master.language
    if not data['summary'] and (not profile.headline or (master.summary and profile.headline == master.summary.text)):
        data['summary'] = imported['summary']
    elif imported['summary'] and (not data['summary'] or data['summary']['text'] != imported['summary']['text']):
        source['conflicts'].append({'field': 'summary', 'imported_value': imported['summary']})

    for section, items, identity_fields in (
        ('experience', imported['experiences'], ('company', 'title', 'start_date', 'end_date')),
        ('education', imported['education'], ('institution', 'credential', 'start_date', 'end_date')),
    ):
        current = entries(data[section], section)
        converted = []
        for item in items:
            details = item.get('bullets', item.get('details', []))
            entry = {key: value for key, value in item.items() if key not in ('bullets', 'details')}
            for old, new in (('employmentType', 'employment_type'), ('fieldOfStudy', 'field_of_study'),
                             ('startDate', 'start_date'), ('endDate', 'end_date'), ('isCurrent', 'is_current')):
                if old in entry:
                    entry[new] = entry.pop(old)
            entry['description'] = '\n'.join(b['text'] for b in details)
            entry['evidence_ids'] = list(dict.fromkeys(e for b in details for e in b['evidenceIds']))
            entry['source_ids'] = [source_key]
            converted.append(entry)
        for entry in converted:
            key = _identity(entry, identity_fields)
            candidates = [item for item in current if key and _identity(item, identity_fields) == key]
            incoming_count = sum(_identity(item, identity_fields) == key for item in converted)
            exact_id = next((item for item in current if item.get('id') == entry['id']), None)
            match = exact_id or (candidates[0] if len(candidates) == incoming_count == 1 else None)
            if match is None:
                current.append(entry)
                source['entry_map'][entry['id']] = entry['id']
                if candidates:
                    source['conflicts'].append({'field': section, 'entry_id': entry['id'],
                                                'reason': 'ambiguous_match'})
                continue
            source['entry_map'][entry['id']] = match['id']
            match['description'] = _merge_text(match.get('description', ''), entry['description'])
            for field, value in entry.items():
                if field in ('id', 'description'):
                    continue
                if field in ('evidence_ids', 'source_ids'):
                    match[field] = list(dict.fromkeys([*match.get(field, []), *value]))
                elif match.get(field) in (None, ''):
                    match[field] = value
                elif value and match[field] != value:
                    source['conflicts'].append({'field': f'{section}.{match["id"]}.{field}',
                                                'imported_value': value})
        if converted:
            data[section] = encode_entries(current)

    skill_names = [line for line in data['skills'].splitlines() if line.strip()]
    seen_names = {_normalized(name) for name in skill_names}
    for item in imported['skills']:
        key = _normalized(item['name'])
        if key not in seen_names:
            skill_names.append(item['name'])
            seen_names.add(key)
        data['skill_metadata'].setdefault(key, {
            'id': item['id'], 'category': item['category'], 'evidence_ids': item['evidenceIds'],
        })
    if imported['skills']:
        data['skills'] = '\n'.join(skill_names)
    for section, raw_key in (
        ('projects', 'projects'), ('certifications', 'certifications'),
        ('languages', 'languages'), ('additional_sections', 'additionalSections'),
    ):
        # Model serialization uses snake_case; validate imports into that shape.
        incoming = ProfilePayload.model_validate({section: imported[raw_key]}).model_dump(mode='json')[section]
        current = data[section]
        for item in incoming:
            if any(old.get('id') == item['id'] for old in current):
                continue
            fields = ('name', 'url') if section == 'projects' else ()
            key = _identity(item, fields) if fields else None
            matches = [old for old in current if key and _identity(old, fields) == key]
            incoming_count = sum(_identity(other, fields) == key for other in incoming) if key else 0
            if section == 'projects' and len(matches) == incoming_count == 1:
                existing = matches[0]
                source['entry_map'][item['id']] = existing['id']
                for bullet in item['bullets']:
                    if not any(old['text'] == bullet['text'] for old in existing['bullets']):
                        existing['bullets'].append(bullet)
                for field in ('role',):
                    if not existing.get(field):
                        existing[field] = item[field]
                    elif item[field] and item[field] != existing[field]:
                        source['conflicts'].append({'field': f'projects.{existing["id"]}.{field}',
                                                    'imported_value': item[field]})
            else:
                current.append(item)
    known = {item['id'] for item in data['evidence']}
    for item in imported['evidence']:
        if item.get('experienceId') in source['entry_map']:
            item['experienceId'] = source['entry_map'][item['experienceId']]
        if item['id'] not in known:
            data['evidence'].append(item)
    data['sources'].append(source)
    return ProfilePayload.model_validate(data)


def ensure_candidate_profile(db: Session, *, owner_id: str | None = None) -> ProfileRecord:
    """Migrate on first access too, including installations upgraded without CLI backfill."""
    profile = get_profile_record(db, owner_id=owner_id)
    created = profile is None
    if profile is None:
        profile = create_profile_record(ProfilePayload().model_dump(mode='json'), owner_id=owner_id)
        db.add(profile)
        db.flush()
    payload = ProfilePayload.model_validate(profile.data)
    if payload.migration.get('master_resume_v1_complete'):
        return profile
    masters = db.scalars(select(ResumeMasterRecord).where(
        ResumeMasterRecord.owner_id == profile.owner_id,
    ).order_by(ResumeMasterRecord.updated_at.desc(), ResumeMasterRecord.id)).all()
    for master in masters:
        version = db.scalar(select(ResumeMasterVersionRecord).where(
            ResumeMasterVersionRecord.owner_id == profile.owner_id,
            ResumeMasterVersionRecord.resume_master_id == master.id,
            ResumeMasterVersionRecord.version == master.current_version,
        ))
        if version is None or canonical_hash(version.data) != version.content_sha256:
            raise ValueError(f'Legacy resume {master.id} failed its integrity check')
        payload = merge_master_into_profile(
            payload, MasterResume.model_validate(version.data),
            source_key=f'legacy:{master.id}:{version.version}',
            source_file_id=version.source_file_id, content_sha256=version.content_sha256,
        )
    data = payload.model_dump(mode='json')
    data['migration']['master_resume_v1_complete'] = True
    if masters or not created:
        update_profile_data(db, profile, data=data, reason='master_resume_migration')
    else:
        # No user-data change: initialize the marker in the initial version only.
        profile.data = data
        db.flush()
        record_profile_version(db, profile, reason='initial')
    db.flush()
    return profile
