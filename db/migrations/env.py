"""Alembic environment configuration.

Migrates the app's database (backend/models/db.py: the data folder's SQLite
file, or DATABASE_URL) — or, when the app upgrades it at startup
(models.db.upgrade_database), the connection it passes in. Batch mode, as
SQLite can't alter most of a table in place (10.5.4), and in one transaction,
so a migration that fails leaves the database as it was.
"""

import os
import sys
from collections import Counter
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, text
from sqlalchemy.pool import NullPool

# db/migrations/env.py -> <repo root>/backend. Two levels up, not one: one
# level up is db/, and db/backend doesn't exist — which went unnoticed wherever
# the backend was also installed into the environment (pip install -e), since
# `import models` then resolved through that instead.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))

from models import Base  # noqa: E402  (registers every model on Base.metadata as a side effect)
from models.base import UtcDateTime  # noqa: E402
from models.db import DATABASE_URL, sqlite_engine  # noqa: E402

target_metadata = Base.metadata

config = context.config
# Not when the app runs it: the app's own logging stays as it is.
if config.config_file_name is not None and "connection" not in config.attributes:
    fileConfig(config.config_file_name)


def _render_item(type_: str, obj: object, autogen_context) -> str | bool:
    # A migration states the column as stored, with no import of the models.
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime()"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def _broken_foreign_keys(connection: Connection) -> Counter:
    """How many rows' foreign keys point at nothing, per (table, parent table):
    counted, as a rebuilt table's rows get new rowids."""
    return Counter((table, parent) for table, _, parent, _ in connection.execute(text("PRAGMA foreign_key_check")))


def _migrate(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        render_item=_render_item,
        transactional_ddl=True,
    )
    # A transaction of its own, or (the app upgrading at startup) the caller's,
    # which it commits.
    with context.begin_transaction():
        # Foreign keys are off while tables are rebuilt; checked before
        # committing — only for rows the migration broke: one that was already
        # (put there by another tool) shouldn't stop every upgrade after it.
        before = _broken_foreign_keys(connection)
        context.run_migrations()
        if broken := _broken_foreign_keys(connection) - before:
            raise RuntimeError(f"The migration left rows whose foreign keys point at nothing: {dict(broken)}")


def run_migrations_online() -> None:
    if (connection := config.attributes.get("connection")) is not None:
        _migrate(connection)
        return
    engine = sqlite_engine(foreign_keys=False, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            _migrate(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
