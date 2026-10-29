#!/usr/bin/env python3
"""Retry saved failed screening, preserving the original search and each finished batch."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run-id", required=True)
    parser.add_argument("--recovery-run-id")
    parser.add_argument("--owner-id", default="local-owner")
    parser.add_argument("--model", required=True)
    parser.add_argument("--batch-size", type=int)
    parser.add_argument("--max-batches", type=int)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    # Load persisted settings before importing database.py, which builds its engine.
    from app.core.docker_entrypoint import load_runtime_settings
    load_runtime_settings(os.environ.get("TASKO_SETTINGS_FILE"))

    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from app.core.database import engine
    from app.core.identity import current_owner_id
    from app.core.settings import Settings, get_settings
    from app.services.job_screening_recovery import recover_failed_screening

    overrides = {"job_screening_model": args.model}
    if args.batch_size is not None:
        overrides["job_screening_batch_size"] = args.batch_size
    settings = Settings.model_validate({**get_settings().model_dump(), **overrides})
    token = current_owner_id.set(args.owner_id)
    lock_key = int.from_bytes(hashlib.sha256(
        f"screening-recovery:{args.owner_id}:{args.source_run_id}".encode()
    ).digest()[:8], "big", signed=True)
    try:
        with engine.connect() as connection:
            if connection.dialect.name == "postgresql":
                acquired = connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key})
                connection.commit()
                if not acquired:
                    raise RuntimeError("Another retry for this source search is already running")
            try:
                with Session(bind=connection, autoflush=False) as db:
                    result = recover_failed_screening(
                        db, source_run_id=args.source_run_id, recovery_run_id=args.recovery_run_id,
                        settings=settings, dry_run=args.dry_run, max_batches=args.max_batches,
                        workers=args.workers,
                        on_progress=lambda progress: print(json.dumps(progress), flush=True),
                    )
                    print(json.dumps(result), flush=True)
                    return 2 if result.get("errors") else 0
            finally:
                if connection.dialect.name == "postgresql":
                    connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
                    connection.commit()
    finally:
        current_owner_id.reset(token)


if __name__ == "__main__":
    raise SystemExit(main())
