import json
from copy import deepcopy

from sqlalchemy import create_engine, delete
from sqlalchemy.orm import sessionmaker
from test_generation_input import build_input, seed_complete_sources
from test_generation_snapshot import runtime_settings

from app.core.database import Base
from app.models.generation import GenerationStartRequest
from app.models.profile import ProfileRecord
from app.models.resume import ResumeMasterRecord, ResumeMasterVersionRecord
from app.services.candidate_profile import canonical_hash, encode_entries
from app.services.generation_snapshot import build_generation_run_snapshot
from app.services.generation_workflow import _snapshot_resume
from app.services.profile_versions import update_profile_data


def test_generation_freezes_full_profile_and_next_run_sees_edit_without_master():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    seed_complete_sources(sessions)
    start = GenerationStartRequest(documentTypes=('tailored_resume',), language='English',
                                   formattingParameters={}, userPreferences='')
    with sessions() as db:
        db.execute(delete(ResumeMasterVersionRecord))
        db.execute(delete(ResumeMasterRecord))
        profile = db.get(ProfileRecord, 'default')
        data = deepcopy(profile.data)
        detail = 'Full detailed experience\n' * 1200
        data['experience'] = encode_entries([{'id': 'experience-one', 'company': 'Example',
                                             'title': 'Engineer', 'description': detail}])
        update_profile_data(db, profile, data=data, reason='manual_edit')
        db.commit()
        first = build_generation_run_snapshot(db, application_id='application-1', start=start,
                                              settings=runtime_settings())
        frozen = first.model_dump(mode='json', by_alias=True)
        first_hash = first.request.master_profile_version.content_sha256
        assert json.loads(first.request.master_profile_version.data['experience'])[0]['description'] == detail
        data = deepcopy(profile.data)
        data['experience'] = encode_entries([{'id': 'experience-one', 'company': 'Example',
                                             'title': 'Lead Engineer', 'description': 'Edited experience'}])
        update_profile_data(db, profile, data=data, reason='next_manual_edit')
        db.commit()
        second = build_input(db)
        assert second.master_profile_version.version == first.request.master_profile_version.version + 1
        assert second.master_profile_version.content_sha256 != first_hash
        assert second.master_profile_version.data['experience'] == data['experience']
        assert first.model_dump(mode='json', by_alias=True) == frozen
        assert canonical_hash(first.request.master_profile_version.data) == first_hash
        assert _snapshot_resume(first.request).experiences[0].title == 'Engineer'


def test_old_master_snapshot_keeps_its_original_hash_and_data():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    seed_complete_sources(sessions)
    with sessions() as db:
        start = GenerationStartRequest(documentTypes=('tailored_resume',), language='English',
                                       formattingParameters={}, userPreferences='')
        snapshot = build_generation_run_snapshot(db, application_id='application-1', start=start,
                                                 settings=runtime_settings())
        legacy = db.get(ResumeMasterVersionRecord, 'master-profile-version-1')
        source = snapshot.request.master_profile_version.model_copy(update={
            'id': legacy.resume_master_id, 'version': legacy.version,
            'data': deepcopy(legacy.data), 'content_sha256': legacy.content_sha256,
        })
        snapshot = snapshot.model_copy(update={'request': snapshot.request.model_copy(update={'master_profile_version': source})})
        before = snapshot.model_dump(mode='json', by_alias=True)
        assert _snapshot_resume(snapshot.request).basics.headline == 'Engineer'
        assert snapshot.model_dump(mode='json', by_alias=True) == before
        assert source.content_sha256 == canonical_hash(legacy.data)
