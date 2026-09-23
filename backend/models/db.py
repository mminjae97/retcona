"""DB engine/session.

Changing only DATABASE_URL should be enough to switch between local (e2-micro)
and Cloud SQL (10.5.4).
"""

import logging
import os
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Connection, create_engine, make_url
from sqlalchemy.orm import sessionmaker

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://retcona:retcona@localhost:5432/retcona")

# Without a connect timeout, an unreachable database host (one that drops
# packets rather than refusing) leaves every connection attempt waiting on the
# OS's TCP timeout, which can be minutes: startup's schema checks hang with no
# error instead of failing, and so does any request or purge pass that needs a
# new pooled connection. This applies to all of them, not only startup — a
# connection that can't be made in this long fails with OperationalError.
#
# Only a default: a connect_timeout already in DATABASE_URL or in libpq's
# PGCONNECT_TIMEOUT wins (an explicit connect argument would override the
# latter), and it's only passed to the libpq-based drivers, which are the ones
# that accept it.
DB_CONNECT_TIMEOUT_SECONDS = 10
_LIBPQ_DRIVERS = {"psycopg", "psycopg2"}


def _connect_args(url: str) -> dict:
    parsed = make_url(url)
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.get_driver_name() not in _LIBPQ_DRIVERS
        or "connect_timeout" in parsed.query
        or "PGCONNECT_TIMEOUT" in os.environ
    ):
        return {}
    return {"connect_timeout": DB_CONNECT_TIMEOUT_SECONDS}


engine = create_engine(DATABASE_URL, connect_args=_connect_args(DATABASE_URL))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Repo-root db/migrations, like shared/nickname-rules.json outside what
# pyproject.toml packages: present in a repo checkout (how this app runs today),
# not necessarily in a non-editable install.
_MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "db" / "migrations"


def check_schema_is_current(connection: Connection) -> None:
    """Fails loudly at startup if the database is behind the migrations this
    code ships with, instead of starting and then returning 500s
    (UndefinedColumn, UndefinedTable) on whichever request first touches what
    the missing migration would have added.

    A database revision this code doesn't know at all is allowed, with a
    warning: that's what an older instance sees during a rolling deploy after
    the new release's migration has already run, and refusing to start there
    would take the old instances down before the new ones are up.
    """
    if not _MIGRATIONS_DIR.is_dir():
        logger.warning("%s not found; skipping the database migration check", _MIGRATIONS_DIR)
        return
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    expected = set(script.get_heads())
    current = set(MigrationContext.configure(connection).get_current_heads())
    if current == expected:
        return
    if not current:
        raise RuntimeError(
            "The database has no migrations applied — run `alembic upgrade head` (from db/), "
            "and check that DATABASE_URL points at the right database."
        )
    for revision in current:
        try:
            known = script.get_revision(revision) is not None
        except CommandError:
            known = False
        if not known:
            logger.warning(
                "The database is at revision %s, which this code doesn't know (expected %s) — "
                "presumably a newer release's migration; starting anyway",
                revision,
                sorted(expected),
            )
            return
    raise RuntimeError(
        f"The database is at revision {sorted(current)}, behind this code's {sorted(expected)} — "
        "run `alembic upgrade head` (from db/) before starting."
    )
