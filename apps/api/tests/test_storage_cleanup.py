import asyncio

import pytest

from app.services import storage_cleanup


def test_expiration_cleanup_runs_repeatedly_on_schedule(monkeypatch) -> None:
    cleanup_calls = 0

    class StopSchedule(Exception):
        pass

    def cleanup() -> tuple[int, int]:
        nonlocal cleanup_calls
        cleanup_calls += 1
        return 0, 0

    async def advance_schedule(_interval_seconds: int) -> None:
        if cleanup_calls >= 2:
            raise StopSchedule

    monkeypatch.setattr(storage_cleanup, "cleanup_expired_storage", cleanup)
    monkeypatch.setattr(storage_cleanup.asyncio, "sleep", advance_schedule)

    with pytest.raises(StopSchedule):
        asyncio.run(storage_cleanup.run_expiration_cleanup(300))

    assert cleanup_calls == 2
