from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine
from sqlalchemy import pool

import app.models.assistant  # noqa: F401
import app.models.applications  # noqa: F401
import app.models.conversations  # noqa: F401
import app.models.documents  # noqa: F401
import app.models.job_screening  # noqa: F401
import app.models.job_search  # noqa: F401
import app.models.jobs  # noqa: F401
import app.models.profile  # noqa: F401
import app.models.resume  # noqa: F401
from app.core.database import Base
from app.core.settings import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def get_database_url() -> str:
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    existing_connection = config.attributes.get("connection")
    if existing_connection is not None:
        run_migrations(existing_connection)
        return

    connectable = create_engine(get_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
