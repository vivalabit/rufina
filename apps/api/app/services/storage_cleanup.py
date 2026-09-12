import asyncio
import logging

from app.core.database import SessionLocal
from app.services.ai_privacy import cleanup_expired_ai_data

logger = logging.getLogger(__name__)


async def run_expiration_cleanup(interval_seconds: int) -> None:
    while True:
        try:
            expired_owners, deleted_ai_records = await asyncio.to_thread(cleanup_expired_storage)
            if expired_owners:
                logger.info(
                    "Expired AI storage cleaned up: owners=%d records=%d",
                    expired_owners,
                    deleted_ai_records,
                )
        except Exception:
            logger.exception("Scheduled storage cleanup failed")
        await asyncio.sleep(interval_seconds)


def cleanup_expired_storage() -> tuple[int, int]:
    with SessionLocal() as db:
        return cleanup_expired_ai_data(db)
