import pytest

from app.models.generation_workflow import DraftBundle
from app.models.resume import MasterResume
from app.services.generation_grounding import GenerationGroundingError, validate_grounded_bundle


def dated_resume(
    period: str,
    *,
    start: str = "06/2026",
    end: str = "",
    current: bool = True,
) -> tuple[MasterResume, DraftBundle]:
    evidence = [{"id": "source:role", "type": "source", "text": "Built data pipelines."}]
    bullets = [{"id": "bullet-1", "text": "Built data pipelines.", "evidenceIds": ["source:role"]}]
    common = {
        "id": "experience-1",
        "company": "Example AG",
        "title": "Engineer",
        "bullets": bullets,
    }
    master = MasterResume.model_validate(
        {
            "id": "master-1",
            "language": "English",
            "basics": {"fullName": "Ada Lovelace"},
            "experiences": [{**common, "startDate": start, "endDate": end, "isCurrent": current}],
            "evidence": evidence,
            "sectionOrder": ["experience"],
        }
    )
    bundle = DraftBundle.model_validate(
        {
            "resume": {
                "id": "tailored-1",
                "masterResumeId": master.id,
                "targetJobId": "job-1",
                "language": master.language,
                "basics": master.basics.model_dump(by_alias=True),
                "experiences": [{**common, "masterExperienceId": "experience-1", "period": period}],
                "evidence": evidence,
                "sectionOrder": ["experience"],
            }
        }
    )
    return master, bundle


@pytest.mark.parametrize(
    "period",
    [
        "06/2026–Present",
        "Jun 2026–Present",
        "June 2026 - Present",
        "06/2026 – Present",
        "06/2026—Present",
        "2026-06–present",
        "6/2026 - Current",
        "Jun. 2026\u00a0–\u202fPresent",
        "Juni 2026 bis heute",
    ],
)
def test_equivalent_current_role_dates_pass(period: str) -> None:
    master, bundle = dated_resume(period)
    validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")


@pytest.mark.parametrize(
    ("start", "end", "period"),
    [
        ("06/2025", "05/2026", "Jun 2025–May 2026"),
        ("11/2024", "06/2025", "Nov 2024–Jun 2025"),
        ("06/2025", "05/2026", "06/2025–05/2026"),
        ("2025-06", "2026-05", "2025-06-2026-05"),
        ("June 2025", "May 2026", "06/2025 – 05/2026"),
        ("03/2025", "12/2025", "März 2025 – Dez. 2025"),
        ("2025-06-01", "2026-05-31", "01.06.2025–31.05.2026"),
        ("2024", "2026", "2024–2026"),
        ("Summer 2024", "Autumn 2026", "Summer 2024 – Autumn 2026"),
        ("", "06/2026", "June 2026"),
        ("06/2026", "", "June 2026"),
    ],
)
def test_equivalent_completed_role_dates_keep_their_precision(
    start: str,
    end: str,
    period: str,
) -> None:
    master, bundle = dated_resume(period, start=start, end=end, current=False)
    validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")


@pytest.mark.parametrize(
    "period",
    [
        "05/2026–Present",
        "Jun 2025–Present",
        "June 2026–July 2026",
        "2026–Present",
        "2026-06-01–Present",
        "Present",
        "06/2026",
        "06/2026–Present (two years)",
        "06/2026–06/2026–Present",
        "13/2026–Present",
    ],
)
def test_changed_or_incomplete_current_role_dates_are_rejected(period: str) -> None:
    master, bundle = dated_resume(period)
    with pytest.raises(GenerationGroundingError, match="protected role dates"):
        validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")


@pytest.mark.parametrize(
    ("start", "end", "period"),
    [
        ("06/2025", "05/2026", "Jun 2025–Jun 2026"),
        ("06/2025", "05/2026", "Jun 2025–Present"),
        ("06/2025", "05/2026", "May 2026–Jun 2025"),
        ("06/2025", "05/2026", "2025–2026"),
        ("2025-06-01", "2026-05-31", "Jun 2025–May 2026"),
        ("2024", "2026", "Jan 2024–Jan 2026"),
        ("Summer 2024", "Autumn 2026", "Jun 2024–Sep 2026"),
        ("2024-02-29", "2025-02-28", "29.02.2024–29.02.2025"),
    ],
)
def test_real_changes_in_completed_role_dates_are_rejected(
    start: str,
    end: str,
    period: str,
) -> None:
    master, bundle = dated_resume(period, start=start, end=end, current=False)
    with pytest.raises(GenerationGroundingError, match="protected role dates"):
        validate_grounded_bundle(bundle, master_resume=master, target_job_id="job-1")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("company", "Another company", "protected employer or title"),
        ("title", "Director", "protected employer or title"),
        ("masterExperienceId", "unknown-role", "unknown experience"),
    ],
)
def test_date_format_tolerance_does_not_relax_other_protected_fields(
    field: str,
    value: str,
    message: str,
) -> None:
    master, bundle = dated_resume("Jun 2026–Present")
    data = bundle.model_dump(by_alias=True)
    data["resume"]["experiences"][0][field] = value
    with pytest.raises(GenerationGroundingError, match=message):
        validate_grounded_bundle(
            DraftBundle.model_validate(data),
            master_resume=master,
            target_job_id="job-1",
        )
