"""DB engine/session: one SQLite file in the app's data folder (design doc 10.1).

DATABASE_URL names another file (sqlite:///C:/path/to/file.db), for tests and
development. Only SQLite is supported.

Transactions: SQLite lets one writer at a time into a database. A transaction
that reads and then writes, begun the default way, can find another one
wrote meanwhile and fail at its first write ("database is locked") instead of
waiting. So every transaction here begins with BEGIN IMMEDIATE, taking the
database's write lock at once; another one waits for it (up to
BUSY_TIMEOUT_SECONDS). One transaction runs at a time, which also gives what
the code's SELECT ... FOR UPDATE asked for under PostgreSQL (SQLite ignores
it): nothing else writes between a transaction's read and its write. It's
why jobs don't hold a session while a model runs (pipeline/validate_episode.py,
...). In WAL mode, a transaction left waiting doesn't block programs that only
read the file (a backup).
"""

import functools
import json
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import IO

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.util import CommandError
from sqlalchemy import URL, Connection, Engine, create_engine, event, make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

import models  # every model module, registered on Base.metadata (for _missing_schema)

if os.name == "nt":
    import msvcrt
else:
    import fcntl

logger = logging.getLogger(__name__)


def _data_dir() -> Path:
    """%LOCALAPPDATA%\\Retcona (10.1); elsewhere than Windows, the XDG data folder."""
    if local := os.environ.get("LOCALAPPDATA"):
        return Path(local) / "Retcona"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "retcona"


# Built, not pasted into a string: a % in the path (a Windows user name can
# have one) is quoted, not read as an escape.
DATABASE_URL = os.environ.get("DATABASE_URL") or URL.create(
    "sqlite", database=(_data_dir() / "retcona.db").as_posix()
).render_as_string()

# How long a transaction waits for another one's write lock before failing
# ("database is locked"). Writes are short; a validation run writes its
# results in one transaction at the end.
BUSY_TIMEOUT_SECONDS = 30.0


def database_path() -> Path:
    url = make_url(DATABASE_URL)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise RuntimeError(f"DATABASE_URL must name a SQLite file (sqlite:///path/to/file.db), not {DATABASE_URL!r}")
    path = Path(url.database)
    # Relative, it would be a different file from backend/ (the API server)
    # than from db/ (alembic).
    if not path.is_absolute():
        raise RuntimeError(f"DATABASE_URL must name the SQLite file by its full path, not {url.database!r}")
    return path


def runner_lock_path() -> Path:
    """The file the one backend process running this database's jobs holds a
    lock on (infra/queue_client.py), beside the database."""
    path = database_path()
    return path.with_name(f"{path.name}.runner-lock")


def lock_file(path: Path) -> IO[bytes] | None:
    """The file opened with an exclusive lock on it, held until it's closed —
    which the OS does when the process ends, however it ends. None if
    another holds it."""
    file = open(path, "a+b")  # noqa: SIM115 (returned open, holding the lock)
    try:
        if os.name == "nt":
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        file.close()
        return None
    return file


def unlock_file(file: IO[bytes]) -> None:
    """Releases a lock_file lock now and closes the file. Unlocked first:
    Windows may release a lock left to the close a little later, and the
    process that let it go may want it again straight away (the runner
    after an upgrade)."""
    try:
        if os.name == "nt":
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_UN)
    finally:
        file.close()


def sqlite_engine(*, foreign_keys: bool = True, **kwargs) -> Engine:
    """An engine on the database file, whose folder is made if missing when it
    first connects. foreign_keys off: for migrations only, which rebuild
    tables (batch mode) and would otherwise cascade the old table's drop to
    its children."""
    folder = database_path().parent
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_SECONDS},
        # Korean as it is, not \uXXXX escapes: readable in the file.
        json_serializer=functools.partial(json.dumps, ensure_ascii=False),
        **kwargs,
    )

    @event.listens_for(engine, "do_connect")
    def _make_folder(*_) -> None:
        folder.mkdir(parents=True, exist_ok=True)

    @event.listens_for(engine, "connect")
    def _configure(dbapi_connection: sqlite3.Connection, _record) -> None:
        # The driver's own transaction handling off: SQLAlchemy begins them (below).
        dbapi_connection.isolation_level = None
        with closing(dbapi_connection.cursor()) as cursor:
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute(f"PRAGMA foreign_keys = {'ON' if foreign_keys else 'OFF'}")

    @event.listens_for(engine, "begin")
    def _begin(connection: Connection) -> None:
        connection.exec_driver_sql("BEGIN IMMEDIATE")

    return engine


engine = sqlite_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Repo-root db/migrations, outside what
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
        raise RuntimeError(f"{context}, and the database is missing {missing}, which this code needs.")


def _unknown_revisions(script: ScriptDirectory, revisions: set[str]) -> list[str]:
    unknown = []
    for revision in sorted(revisions):
        try:
            if script.get_revision(revision) is None:
                unknown.append(revision)
        except CommandError:
            unknown.append(revision)
    return unknown


def check_schema_is_current(connection: Connection) -> None:
    """Fails loudly at startup if the database is behind the migrations this
    code ships with, instead of starting and then returning 500s on whichever
    request first touches what the missing migration would have added.

    Two cases can't be settled by revision alone, and fall back to checking
    the schema itself against the models (_missing_schema):
    - A revision this code doesn't know: a newer version of the app migrated
      the database, and this older one was installed again. Fine if the
      schema still has everything this code needs (a newer version adds
      tables and columns), but it could also be a revision from a branch that
      split off before this code's head (missing this code's newer
      migrations). With no script for it, its ancestry can't be checked, but
      whether the schema has everything this code needs can.
    - No db/migrations to compare against (a non-editable install), where the
      revision check can't run at all.
    """
    current = set(MigrationContext.configure(connection).get_current_heads())
    if not current:
        raise RuntimeError(
            f"The database has no migrations applied, and {_MIGRATIONS_DIR} has none to apply "
            "— an install has to ship db/migrations with its versions."
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
    if unknown := _unknown_revisions(script, current):
        _require_schema(
            connection,
            f"The database is at revision {unknown}, which this code doesn't know (expected {sorted(expected)})",
        )
        logger.warning(
            "The database is at revision %s, which this code doesn't know (expected %s), but its schema "
            "has everything this code's models need — presumably a newer version's migration; starting anyway",
            unknown,
            sorted(expected),
        )
        return
    raise RuntimeError(f"The database is at revision {sorted(current)}, behind this code's {sorted(expected)}.")


def backup_path() -> Path:
    """Where the database is copied before an upgrade: beside it, replacing
    the copy an earlier upgrade made."""
    path = database_path()
    return path.with_name(f"{path.stem}.before-upgrade{path.suffix}")


def _back_up() -> Path:
    # SQLite's backup API: a consistent copy, the WAL's latest writes included.
    backup = backup_path()
    with closing(sqlite3.connect(database_path())) as source, closing(sqlite3.connect(backup)) as target:
        source.backup(target)
    return backup


def upgrade_database() -> None:
    """Brings the database up to this code's migrations (10.5.4): creates it on
    the first start, and upgrades it after the app is updated — copying it
    aside first (backup_path). All of it in one transaction, holding the
    write lock from the revision check to the commit: an upgrade that fails
    changes nothing (SQLite's schema changes are transactional), and a second
    app starting meanwhile waits, then finds the database upgraded — it
    neither upgrades it again nor copies the upgraded one over the copy. The
    copy is for an upgrade that succeeded and turns out wrong. Not while
    another backend process runs on the database (the one holding the runner
    lock — an older version left open), which would carry on against the
    tables this rebuilds. A database at a revision this code doesn't know is
    left for check_schema_is_current."""
    if not _MIGRATIONS_DIR.is_dir():
        return
    script = ScriptDirectory(str(_MIGRATIONS_DIR))
    expected = set(script.get_heads())
    migrations = sqlite_engine(foreign_keys=False, poolclass=NullPool)
    try:
        with migrations.connect() as connection:
            # Begins the transaction (BEGIN IMMEDIATE), left open until the commit below.
            current = set(MigrationContext.configure(connection).get_current_heads())
            if current == expected or _unknown_revisions(script, current):
                return
            runner_lock = lock_file(runner_lock_path())
            if runner_lock is None:
                raise RuntimeError(
                    "Another backend process is running on this database: close it, then start this one "
                    f"again to upgrade the database from {sorted(current)} to {sorted(expected)}."
                )
            try:
                if current:
                    # Another connection reads it meanwhile, as WAL lets it.
                    backup = _back_up()
                    logger.info("Upgrading the database from %s; copied it to %s first", sorted(current), backup)
                config = Config()
                # A % in the path doubled: alembic's config reads % as interpolation.
                config.set_main_option("script_location", str(_MIGRATIONS_DIR).replace("%", "%%"))
                # env.py migrates on this connection, in its transaction, rather than opening its own.
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
                connection.commit()
            finally:
                # The runner (api/main.py) takes it next, in this process.
                unlock_file(runner_lock)
        logger.info("The database is at %s (%s)", sorted(expected), database_path())
    finally:
        migrations.dispose()


def check_database() -> None:
    """The startup check, after upgrade_database: every entry point that talks
    to the database (the API server's lifespan) runs both before doing
    anything else. Blocking — the API server runs them in a thread.
    """
    with engine.connect() as connection:
        check_schema_is_current(connection)
