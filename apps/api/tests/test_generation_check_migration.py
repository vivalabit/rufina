from alembic import command
from sqlalchemy import Text, create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from test_generation_input import seed_complete_sources
from test_generation_store import _request, _settings

from app.core.migrations import get_alembic_config
from app.models.generation_runs import ApplicationGenerationRunRecord, GenerationRunCheckRecord
from app.services.generation_store import create_generation_run, persist_run_check


def test_check_name_migration_preserves_existing_checks_and_full_source_ids(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'check-names.sqlite'}"
    config = get_alembic_config(database_url)
    command.upgrade(config, "20260916_0060")
    engine = create_engine(database_url)
    sessions = sessionmaker(bind=engine, autoflush=False)
    try:
        seed_complete_sources(sessions)
        with sessions() as db:
            run = create_generation_run(
                db, application_id="application-1", request=_request("long-check-name"),
                settings=_settings(),
            )
            run_id = run.id
            persist_run_check(db, run=run, check_type="pdf_readable", status="passed")
            db.commit()

        command.upgrade(config, "20260923_0061")
        column = next(c for c in inspect(engine).get_columns("generation_run_checks")
                      if c["name"] == "check_type")
        assert isinstance(column["type"], Text)
        assert column["nullable"] is False

        names = ["role_dates:restored-" + "source-id-" * 12 + suffix for suffix in ("1", "2")]
        with sessions() as db:
            run = db.get(ApplicationGenerationRunRecord, run_id)
            for name in names:
                persist_run_check(db, run=run, check_type=name, status="passed")
            db.commit()
        with sessions() as db:
            assert set(db.scalars(select(GenerationRunCheckRecord.check_type))) == {
                "pdf_readable", *names,
            }
    finally:
        engine.dispose()
