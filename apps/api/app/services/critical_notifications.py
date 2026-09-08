import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.vacancy_sources import direct_company_definition
from app.models.notifications import CriticalNotificationRecord
from app.services.parser_validation import PARTIAL_PARSER_RESULT_PREFIX

logger = logging.getLogger("uvicorn.error")


def create_parser_failure_notifications(
    db: Session,
    *,
    run_id: str,
    source_errors: dict[str, str],
    source_attempts: dict[str, int],
) -> list[CriticalNotificationRecord]:
    records: list[CriticalNotificationRecord] = []
    for source, error in source_errors.items():
        existing = db.scalar(
            select(CriticalNotificationRecord).where(
                CriticalNotificationRecord.run_id == run_id,
                CriticalNotificationRecord.source == source,
            )
        )
        if existing is not None:
            records.append(existing)
            continue

        attempts = max(1, source_attempts.get(source, 1))
        source_name = source_display_name(source)
        partial = error.startswith(PARTIAL_PARSER_RESULT_PREFIX)
        record = CriticalNotificationRecord(
            severity="critical",
            category="parser_partial" if partial else "parser_failure",
            source=source,
            title=f"{source_name} parser returned partial results"
            if partial
            else f"{source_name} parser failed",
            description=error[:4_000],
            attempts=attempts,
            run_id=run_id,
        )
        db.add(record)
        records.append(record)
        logger.error(
            json.dumps(
                {
                    "event": "critical_notification.created",
                    "message": "Persistent parser failure notification created",
                    "source": source,
                    "sourceName": source_name,
                    "attempts": attempts,
                    "runId": run_id,
                    "error": error[:500],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
    return records


def source_display_name(source: str) -> str:
    normalized = "jobs_ch" if source in {"jobs_ch", "jobs.ch"} else source
    aggregator_name = {
        "linkedin": "LinkedIn",
        "indeed": "Indeed",
        "jobs_ch": "jobs.ch",
    }.get(normalized)
    if aggregator_name:
        return aggregator_name
    company = direct_company_definition(normalized)
    return company.name if company else source
