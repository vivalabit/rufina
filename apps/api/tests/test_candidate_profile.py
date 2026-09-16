import json

from app.models.profile import ProfilePayload
from app.services.candidate_profile import apply_form_update, profile_resume


def test_existing_form_roundtrip_keeps_full_descriptions_and_rich_fields():
    description = 'Long detailed achievement.\n' * 1200
    profile = ProfilePayload(
        name='Ada', email='ada@example.org', phone='+41 123',
        experience=json.dumps([{'id': 'job-1', 'company': 'Example', 'title': 'Engineer',
                                'description': description, 'source_ids': ['source-1']}]),
        education='Historical education text', skills='Python\nSQL',
        sources=[{'id': 'source-1', 'sha256': 'original'}],
    )
    # Simulate an old client which knows nothing about the extended fields.
    form = ProfilePayload(name='Ada Updated', experience=profile.experience,
                          education=profile.education, skills=profile.skills)
    saved = apply_form_update(profile, form)
    assert saved.email == profile.email
    assert saved.sources == profile.sources
    assert saved.experience == profile.experience
    projected = profile_resume(saved, 'default')
    assert ''.join(b.text for b in projected.experiences[0].bullets) == description.rstrip('\n')
    assert projected.basics.email == profile.email


def test_form_description_edit_keeps_provenance_but_replaces_text():
    profile = ProfilePayload(experience=json.dumps([{
        'id': 'job-1', 'title': 'Engineer', 'company': 'Example',
        'description': 'Old', 'source_ids': ['source-1'],
    }]))
    updated = apply_form_update(profile, ProfilePayload(experience=json.dumps([{
        'id': 'job-1', 'title': 'Engineer', 'company': 'Example', 'description': 'New',
    }])))
    item = json.loads(updated.experience)[0]
    assert item['description'] == 'New'
    assert item['source_ids'] == ['source-1']
    assert profile_resume(updated, 'default').experiences[0].bullets[0].text == 'New'


def test_archived_evidence_does_not_authorize_deleted_profile_claims():
    profile = ProfilePayload(name='Ada', evidence=[{
        'id': 'source:old', 'type': 'source', 'text': 'Old employer and unsupported metric',
    }], experience=json.dumps([{
        'id': 'job-1', 'company': 'Corrected employer', 'title': 'Engineer',
        'description': 'Corrected achievement',
    }]))
    projection = profile_resume(profile, 'default')
    assert all(item.id != 'source:old' for item in projection.evidence)
    assert profile.evidence[0].id == 'source:old'
    assert any(item.text == 'Corrected achievement' for item in projection.evidence)


def test_editing_summary_in_existing_form_replaces_imported_summary_for_generation():
    profile = ProfilePayload(name='Ada', headline='Imported summary',
        summary={'text': 'Imported summary', 'evidenceIds': ['source:summary']},
        evidence=[{'id': 'source:summary', 'type': 'source', 'text': 'Imported summary'}])
    updated = apply_form_update(profile, ProfilePayload(name='Ada', headline='Corrected summary'))
    generated = profile_resume(updated, 'default')
    assert generated.summary.text == 'Corrected summary'
    assert all(item.id != 'source:summary' for item in generated.evidence)
