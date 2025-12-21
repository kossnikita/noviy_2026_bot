from __future__ import annotations

import os
import logging
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from api.db_sa import Base, build_database_url


config = context.config

if config.config_file_name is not None:
    if not logging.getLogger().handlers:
        fileConfig(config.config_file_name, disable_existing_loggers=False)


target_metadata = Base.metadata


def _get_url() -> str:
    database_url = os.getenv("DATABASE_URL", "").strip()
    db_path = os.getenv("DB_PATH", "database.sqlite3").strip()
    return build_database_url(database_url, db_path)


def run_migrations_offline() -> None:
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _get_url()

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
