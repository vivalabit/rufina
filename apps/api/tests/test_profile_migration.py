import json
from copy import deepcopy

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.main import app  # noqa: F401 - register all mapped tables
from app.models.profile import ProfilePayload, ProfileRecord, ProfileVersionRecord
from app.models.resume import MasterResume, ResumeMasterRecord, ResumeMasterVersionRecord
from app.services.candidate_profile import canonical_hash, profile_resume
from app.services.profile_migration import ensure_candidate_profile, merge_master_into_profile


def master_fixture():
    return MasterResume.model_validate({
        'id': 'legacy', 'language': 'English',
        'basics': {'fullName': 'Imported Name', 'email': 'ada@example.org'},
        'experiences': [{'id': 'job', 'company': 'Example', 'title': 'Engineer',
                         'startDate': '2020-01', 'endDate': '2023-01',
                         'bullets': [{'id': 'bullet', 'text': 'Imported achievement ' * 200,
                                      'evidenceIds': ['source:one']}]}],
        'projects': [{'id': 'project', 'name': 'Project', 'url': 'https://example.org',
                      'bullets': [{'id': 'project-bullet', 'text': 'Project achievement',
                                   'evidenceIds': ['source:one']}]}],
        'evidence': [{'id': 'source:one', 'type': 'source', 'text': 'Source fragment'}],
        'sectionOrder': ['experience', 'projects'],
    })


def test_migration_is_lossless_repeatable_and_does_not_touch_history():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    legacy = master_fixture().model_dump(mode='json', by_alias=True)
    original = deepcopy(legacy)
    manual = {'id': 'manual-job', 'company': 'Example', 'title': 'Engineer',
              'start_date': '2020-01', 'end_date': '2023-01',
              'description': 'Manual correction\n' + 'Detailed contribution ' * 1500}
    with Session(engine) as db:
        db.add_all([
            ProfileRecord(id='default', data=ProfilePayload(name='Manual Name',
                experience=json.dumps([manual])).model_dump()),
            ResumeMasterRecord(id='legacy', name='Imported Name', language='English', current_version=1),
            ResumeMasterVersionRecord(id='version', resume_master_id='legacy', version=1,
                                      data=legacy, content_sha256=canonical_hash(legacy)),
        ])
        db.commit()
        profile = ensure_candidate_profile(db)
        db.commit()
        saved = deepcopy(profile.data)
        revision = profile.revision
        ensure_candidate_profile(db)
        db.commit()
        assert profile.data == saved and profile.revision == revision
        assert profile.data['name'] == 'Manual Name'
        assert profile.data['email'] == 'ada@example.org'
        items = json.loads(profile.data['experience'])
        assert len(items) == 1 and items[0]['id'] == 'manual-job'
        assert items[0]['description'].startswith(manual['description'])
        assert 'Imported achievement' in items[0]['description']
        assert profile.data['projects'][0]['name'] == 'Project'
        assert db.get(ResumeMasterVersionRecord, 'version').data == original
        assert db.get(ResumeMasterVersionRecord, 'version').content_sha256 == canonical_hash(original)
        versions = db.scalars(select(ProfileVersionRecord).order_by(ProfileVersionRecord.revision)).all()
        assert [v.revision for v in versions] == [1, 2]
        assert versions[-1].data == saved
        assert profile_resume(ProfilePayload(**saved), profile.id).projects


def test_ambiguous_roles_are_not_merged():
    item = {'company': 'Example', 'title': 'Engineer', 'start_date': '2020-01',
            'end_date': '2023-01', 'description': 'Manual'}
    profile = ProfilePayload(experience=json.dumps([{**item, 'id': 'a'}, {**item, 'id': 'b'}]))
    imported = merge_master_into_profile(profile, master_fixture(), source_key='source',
                                        source_file_id='file', content_sha256='hash')
    assert len(json.loads(imported.experience)) == 3
    assert imported.sources[0]['conflicts'][-1]['reason'] == 'ambiguous_match'


def test_other_owner_legacy_data_is_not_imported():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        master = master_fixture()
        data = master.model_dump(mode='json', by_alias=True)
        db.add_all([
            ResumeMasterRecord(id=master.id, owner_id='another-owner', name='Other', current_version=1),
            ResumeMasterVersionRecord(id='version', owner_id='another-owner', resume_master_id=master.id,
                                      version=1, data=data, content_sha256=canonical_hash(data)),
        ])
        db.commit()
        profile = ensure_candidate_profile(db)
        assert not profile.data['experience']
        assert not profile.data['sources']


def test_alembic_backfill_persists_complete_profile_and_preserves_source_hash(tmp_path):
    from alembic import command

    from app.core.migrations import get_alembic_config, upgrade_database

    url = f'sqlite:///{tmp_path / "legacy.sqlite"}'
    command.upgrade(get_alembic_config(url), '20260913_0059')
    engine = create_engine(url)
    data = master_fixture().model_dump(mode='json', by_alias=True)
    digest = canonical_hash(data)
    with Session(engine) as db:
        db.add(ResumeMasterRecord(id='legacy', name='Imported Name', current_version=1))
        db.add(ResumeMasterVersionRecord(id='version', resume_master_id='legacy', version=1,
                                        data=data, content_sha256=digest))
        db.commit()
    upgrade_database(url)
    upgrade_database(url)
    with Session(engine) as db:
        profile = db.get(ProfileRecord, 'default')
        assert profile.data['email'] == 'ada@example.org'
        assert profile.revision == 2
        assert len(profile.data['sources']) == 1
        assert db.get(ResumeMasterVersionRecord, 'version').content_sha256 == digest
        assert db.get(ResumeMasterVersionRecord, 'version').data == data
