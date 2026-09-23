"""Alembic environment configuration.

Uses the DATABASE_URL environment variable as-is so local/Cloud SQL can be
switched without code changes (10.5.4).
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# db/migrations/env.py -> <repo root>/backend. Two levels up, not one: one
# level up is db/, and db/backend doesn't exist — which went unnoticed wherever
# the backend was also installed into the environment (pip install -e), since
# `import models` then resolved through that instead.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

import models  # noqa: E402  (registers every model on Base.metadata as a side effect)
from models import Base  # noqa: E402

target_metadata = Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
