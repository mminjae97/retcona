"""The SQLite database (models/db.py, models/base.py): upgrading it at
startup, its timestamps, and one writer at a time."""

import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, update
from sqlalchemy.exc import IntegrityError, StatementError

from models import db as models_db
from models.db import SessionLocal
from models.episode import Episode
from models.novel import Novel

_REVISION = '''"""{name}"""
from alembic import op
import sqlalchemy as sa

revision = "{revision}"
down_revision = "{down}"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("{name}", sa.Column("id", sa.Integer(), primary_key=True))
    {then}


def downgrade() -> None:
    op.drop_table("{name}")
'''


@pytest.fixture
def scratch_database(tmp_path, monkeypatch):
    """A database of its own, and a copy of db/migrations to add revisions to."""
    migrations = tmp_path / "migrations"
    shutil.copytree(models_db._MIGRATIONS_DIR, migrations, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(models_db, "_MIGRATIONS_DIR", migrations)
    monkeypatch.setattr(models_db, "DATABASE_URL", f"sqlite:///{(tmp_path / 'app.db').as_posix()}")
    return migrations


def _head() -> str:
    return next(iter(models_db.ScriptDirectory(str(models_db._MIGRATIONS_DIR)).get_heads()))


def _add_revision(migrations: Path, name: str, then: str = "pass") -> str:
    revision = uuid.uuid4().hex[:12]
    down = _head()
    (migrations / "versions" / f"{revision}_{name}.py").write_text(
        _REVISION.format(name=name, revision=revision, down=down, then=then), encoding="utf-8"
    )
    return revision


def _state() -> tuple[set[str], set[str]]:
    engine = models_db.sqlite_engine()
    try:
        with engine.connect() as connection:
            return set(MigrationContext.configure(connection).get_current_heads()), set(
                inspect(connection).get_table_names()
            )
    finally:
        engine.dispose()


def test_the_first_start_creates_the_database_with_no_copy(scratch_database):
    models_db.upgrade_database()
    revisions, tables = _state()
    assert revisions == {_head()}
    assert {"novels", "episodes", "jobs"} <= tables
    assert not models_db.backup_path().exists()


def test_an_upgrade_copies_the_database_aside_first(scratch_database):
    models_db.upgrade_database()
    revision = _add_revision(scratch_database, "added_later")
    models_db.upgrade_database()
    revisions, tables = _state()
    assert revisions == {revision}
    assert "added_later" in tables
    # The copy is the database as it was before.
    with closing(sqlite3.connect(models_db.backup_path())) as copy:
        copied = {name for (name,) in copy.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "novels" in copied and "added_later" not in copied


def test_two_apps_starting_together_upgrade_once_and_keep_the_copy_from_before(scratch_database):
    models_db.upgrade_database()
    revision = _add_revision(scratch_database, "added_later")
    errors = []

    def start() -> None:
        try:
            models_db.upgrade_database()
        except Exception as exc:  # noqa: BLE001 (reported by the assert below)
            errors.append(exc)

    apps = [threading.Thread(target=start) for _ in range(2)]
    for app in apps:
        app.start()
    for app in apps:
        app.join(30)
    assert errors == []
    assert _state()[0] == {revision}
    # The second waited for the first's upgrade, and copied nothing over its copy.
    with closing(sqlite3.connect(models_db.backup_path())) as copy:
        copied = {name for (name,) in copy.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "added_later" not in copied


def test_no_upgrade_while_another_backend_process_runs_on_the_database(scratch_database):
    models_db.upgrade_database()
    before = _state()
    _add_revision(scratch_database, "added_later")
    # An older version still open: it holds the runner lock.
    running = models_db.lock_file(models_db.runner_lock_path())
    try:
        with pytest.raises(RuntimeError, match="Another backend process"):
            models_db.upgrade_database()
        assert _state() == before
    finally:
        models_db.unlock_file(running)
    models_db.upgrade_database()
    assert "added_later" in _state()[1]


def test_the_database_is_named_by_its_full_path(tmp_path, monkeypatch):
    monkeypatch.setattr(models_db, "DATABASE_URL", "sqlite:///retcona.db")
    with pytest.raises(RuntimeError, match="full path"):
        models_db.database_path()
    # A % in the folder's name stays a %.
    path = tmp_path / "a%20b" / "r.db"
    monkeypatch.setattr(models_db, "DATABASE_URL", models_db.URL.create("sqlite", database=path.as_posix()).render_as_string())
    assert models_db.database_path() == path


def test_the_folder_is_made_when_the_database_is_first_opened_not_before(tmp_path, monkeypatch):
    folder = tmp_path / "not yet"
    monkeypatch.setattr(models_db, "DATABASE_URL", f"sqlite:///{(folder / 'app.db').as_posix()}")
    engine = models_db.sqlite_engine()
    try:
        assert not folder.exists()
        with engine.connect():
            pass
        assert (folder / "app.db").exists()
    finally:
        engine.dispose()


def test_an_upgrade_that_fails_changes_nothing(scratch_database):
    models_db.upgrade_database()
    before = _state()
    _add_revision(scratch_database, "half_done", then='raise RuntimeError("the migration fails")')
    with pytest.raises(RuntimeError, match="the migration fails"):
        models_db.upgrade_database()
    # Rolled back as a whole: not even the table it made before failing.
    assert _state() == before


def test_a_database_a_newer_version_upgraded_is_left_as_it_is(scratch_database):
    _add_revision(scratch_database, "from_a_newer_version")
    models_db.upgrade_database()
    newer = _state()
    # This version doesn't have the newer revision.
    for script in (scratch_database / "versions").glob("*_from_a_newer_version.py"):
        script.unlink()
    models_db.upgrade_database()
    assert _state() == newer


def test_times_are_utc_with_microseconds_and_a_naive_one_is_refused():
    with SessionLocal() as db:
        novel = Novel(title="시간 시험")
        db.add(novel)
        db.commit()
        db.refresh(novel)
        # Set by the database: UTC, finer than whole seconds.
        assert novel.created_at.tzinfo == UTC
        assert abs(novel.created_at - datetime.now(UTC)) < timedelta(seconds=5)
        # Any zone in: the same moment out, in UTC.
        seoul = datetime(2026, 10, 29, 3, 0, 0, 123456, tzinfo=timezone(timedelta(hours=9)))
        novel.deleted_at = seoul
        db.commit()
        db.refresh(novel)
        assert novel.deleted_at == seoul
        assert novel.deleted_at.tzinfo == UTC
        novel.deleted_at = datetime(2026, 10, 28, 18, 0, 0)
        with pytest.raises(StatementError, match="no time zone"):
            db.commit()
        db.rollback()
        db.delete(novel)
        db.commit()


def test_two_saves_in_one_second_have_different_times_that_compare_as_written():
    with SessionLocal() as db:
        novel = Novel(title="저장 시험")
        db.add(novel)
        db.flush()
        episode = Episode(novel_id=novel.id, episode_index=1, content="첫 저장")
        db.add(episode)
        db.commit()
        db.refresh(episode)
        first = episode.updated_at
        time.sleep(0.01)
        episode.content = "두 번째 저장"
        db.commit()
        db.refresh(episode)
        assert episode.updated_at > first
        # The time read back matches the stored text in SQL (as the validation
        # job checks the content it validated is still the episode's).
        assert db.scalar(select(Episode.id).where(Episode.updated_at == episode.updated_at)) == episode.id
        assert db.scalar(select(Episode.id).where(Episode.id == episode.id, Episode.updated_at == first)) is None
        db.delete(novel)
        db.commit()


def test_a_row_must_point_at_a_row_that_exists():
    with SessionLocal() as db:
        db.add(Episode(novel_id=uuid.uuid4(), episode_index=1, content="주인 없는 화"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_a_second_writer_waits_for_the_first_instead_of_failing():
    with SessionLocal() as db:
        novel = Novel(title="잠금 시험")
        db.add(novel)
        db.commit()
        novel_id = novel.id
    renamed = []

    def rename(title: str) -> None:
        with SessionLocal() as db:
            current = db.scalar(select(Novel.title).where(Novel.id == novel_id))
            db.execute(update(Novel).where(Novel.id == novel_id).values(title=f"{current}+{title}"))
            db.commit()
            renamed.append(title)

    with SessionLocal() as first:
        # Reads, and so holds the write lock from then on (BEGIN IMMEDIATE).
        current = first.scalar(select(Novel.title).where(Novel.id == novel_id))
        second = threading.Thread(target=rename, args=("둘째",))
        second.start()
        time.sleep(0.3)
        assert renamed == [], "the second waits while the first's transaction is open"
        first.execute(update(Novel).where(Novel.id == novel_id).values(title=f"{current}+첫째"))
        first.commit()
    second.join(10)
    assert renamed == ["둘째"]
    with SessionLocal() as db:
        # Neither lost the other's write.
        assert db.scalar(select(Novel.title).where(Novel.id == novel_id)) == "잠금 시험+첫째+둘째"
        db.delete(db.get(Novel, novel_id))
        db.commit()
