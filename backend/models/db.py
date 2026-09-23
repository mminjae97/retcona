"""DB engine/session.

Changing only DATABASE_URL should be enough to switch between local (e2-micro)
and Cloud SQL (10.5.4).
"""

import logging
import os
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import Connection, create_engine, make_url
from sqlalchemy.orm import sessionmaker

import models  # every model module, registered on Base.metadata (for _missing_schema)

logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql+psycopg://retcona:retcona@localhost:5432/retcona")

# Without a connect timeout, an unreachable database host (one that drops
# packets rather than refusing) leaves every connection attempt waiting on the
# OS's TCP timeout, which can be minutes: startup's schema checks hang with no
# error instead of failing, and so does any request or purge pass that needs a
# new pooled connection. This applies to all of them, not only startup — a
# connection that can't be made in this long fails with OperationalError.
#
# Only a default: a connect_timeout already in DATABASE_URL, or a positive
# libpq PGCONNECT_TIMEOUT, wins (an explicit connect argument would override
# the latter). An empty or 0 PGCONNECT_TIMEOUT means "no timeout" to libpq —
# the indefinite hang this exists to prevent, and more likely a blank line in
# an env file than a decision — so it doesn't; `?connect_timeout=0` in
# DATABASE_URL still turns the timeout off on purpose. It's only passed to the
# libpq-based drivers, which are the ones that accept it.
DB_CONNECT_TIMEOUT_SECONDS = 10
_LIBPQ_DRIVERS = {"psycopg", "psycopg2"}


def _positive_env_timeout() -> bool:
    value = os.environ.get("PGCONNECT_TIMEOUT", "").strip()
    return value.isdigit() and int(value) > 0


def _connect_args(url: str) -> dict:
    parsed = make_url(url)
    if (
        parsed.get_backend_name() != "postgresql"
        or parsed.get_driver_name() not in _LIBPQ_DRIVERS
        or "connect_timeout" in parsed.query
        or _positive_env_timeout()
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


def _missing_schema(connection: Connection) -> list[str]:
    """Tables and columns this code's models declare that the database lacks,
    found by comparing Base.metadata against the live schema (the comparison
    `alembic revision --autogenerate` makes). Only what's missing counts:
    extra tables/columns, or differing types and indexes, don't stop this code
    from running, while a missing one is a 500 on first use.
    """
    diffs = compare_metadata(MigrationContext.configure(connection), models.Base.metadata)
    missing = []
    for diff in diffs:
        # Column modifications come grouped in lists; only the add_* tuples matter.
        if not isinstance(diff, tuple):
            continue
        if diff[0] == "add_table":
            missing.append(diff[1].name)
        elif diff[0] == "add_column":
            missing.append(f"{diff[2]}.{diff[3].name}")
    return sorted(missing)


def _require_schema(connection: Connection, context: str) -> None:
    missing = _missing_schema(connection)
    if missing:
        raise RuntimeError(
            f"{context}, and the database is missing {missing}, which this code needs — "
            "run this release's migrations (`alembic upgrade head` from db/) before starting."
        )


def check_schema_is_current(connection: Connection) -> None:
    """Fails loudly at startup if the database is behind the migrations this
    code ships with, instead of starting and then returning 500s
    (UndefinedColumn, UndefinedTable) on whichever request first touches what
    the missing migration would have added.

    Two cases can't be settled by revision alone, and fall back to checking
    the schema itself against the models (_missing_schema):
    - A revision this code doesn't know: what an older instance sees during a
      rolling deploy after the new release migrated (fine, and refusing would
      take the old instances down before the new ones are up), but also a
      revision from a branch that split off before this code's head (missing
      this code's newer migrations). With no script for it, its ancestry can't
      be checked, but whether the schema has everything this code needs can.
    - No db/migrations to compare against (a non-editable install), where the
      revision check can't run at all.
    """
    current = set(MigrationContext.configure(connection).get_current_heads())
    if not current:
        raise RuntimeError(
            "The database has no migrations applied — run `alembic upgrade head` (from db/), "
            "and check that DATABASE_URL points at the right database."
        )
    if not _MIGRATIONS_DIR.is_dir():
        _require_schema(connection, f"{_MIGRATIONS_DIR} not found, so revision {sorted(current)} can't be checked")
        logger.warning(
            "%s not found; checked the database schema against the models instead (nothing missing)",
            _MIGRATIONS_DIR,
        )
        return
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    expected = set(script.get_heads())
    if current == expected:
        return
    unknown = []
    for revision in sorted(current):
        try:
            if script.get_revision(revision) is None:
                unknown.append(revision)
        except CommandError:
            unknown.append(revision)
    if unknown:
        _require_schema(
            connection,
            f"The database is at revision {unknown}, which this code doesn't know (expected {sorted(expected)})",
        )
        logger.warning(
            "The database is at revision %s, which this code doesn't know (expected %s), but its schema "
            "has everything this code's models need — presumably a newer release's migration; starting anyway",
            unknown,
            sorted(expected),
        )
        return
    raise RuntimeError(
        f"The database is at revision {sorted(current)}, behind this code's {sorted(expected)} — "
        "run `alembic upgrade head` (from db/) before starting."
    )
