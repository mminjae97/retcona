"""The trash against the tests' database (api/novels.py,
pipeline/empty_trash.py; tests/conftest.py)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update

from api.main import CLIENT_HEADER, app
from infra.queue_client import QueuedJob
from models.base import Base
from models.db import SessionLocal, engine
from models.job import Job
from models.novel import TRASH_KEPT, Novel
from models.validation_run import ValidationRun
from pipeline import validate_episode
from pipeline.empty_trash import _purge, empty_trash, request_empty_trash
from pipeline.extract_claims import Extraction
from workers.runner import handle

# Not as a context manager: no lifespan, so no runner of its own.
client = TestClient(app, base_url="http://localhost:8000", headers={CLIENT_HEADER: "1"})


@pytest.fixture
def novel():
    novel_id = client.post("/novels", json={"title": "휴지통 시험"}).json()["id"]
    episode_id = client.post(f"/novels/{novel_id}/episodes", json={"content": "레온은 푸른 눈이었다."}).json()["id"]
    client.post(f"/novels/{novel_id}/characters", json={"name": "레온"})
    run = client.post(f"/novels/{novel_id}/episodes/{episode_id}/validations")
    assert run.status_code == 202, run.text
    yield uuid.UUID(novel_id)
    # Whatever the test left it as, deleted for good, with the run's job (no
    # runner here takes it).
    _delete_for_good(uuid.UUID(novel_id))
    with SessionLocal() as db:
        db.execute(delete(Job).where(Job.target_id == uuid.UUID(run.json()["id"])))
        db.commit()


def _trash() -> dict[str, dict]:
    response = client.get("/novels/trash")
    assert response.status_code == 200, response.text
    return {each["id"]: each for each in response.json()}


def _deleted_days_ago(novel_id: uuid.UUID, days: int) -> None:
    with SessionLocal() as db:
        db.execute(
            update(Novel).where(Novel.id == novel_id).values(deleted_at=datetime.now(UTC) - timedelta(days=days))
        )
        db.commit()


def _delete_for_good(novel_id: uuid.UUID) -> None:
    """This novel only, not the rest of the database's trash."""
    _deleted_days_ago(novel_id, 31)
    _purge(novel_id, datetime.now(UTC) - TRASH_KEPT)


def _rows(novel_id: uuid.UUID) -> int:
    """The novel's rows, in its own table and every one under it (every table
    but jobs has a novel_id: test_every_row_under_a_novel_goes_with_it)."""
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(Novel).where(Novel.id == novel_id))
        for table in Base.metadata.sorted_tables:
            if "novel_id" in table.c:
                count += db.scalar(select(func.count()).select_from(table).where(table.c.novel_id == novel_id))
    return count


def test_a_deleted_novel_is_in_the_trash_and_can_be_restored(novel):
    assert client.delete(f"/novels/{novel}").status_code == 204
    assert str(novel) not in {each["id"] for each in client.get("/novels").json()}
    trashed = _trash()[str(novel)]
    assert trashed["title"] == "휴지통 시험"
    kept = datetime.fromisoformat(trashed["purge_after"]) - datetime.fromisoformat(trashed["deleted_at"])
    assert kept == TRASH_KEPT

    restored = client.post(f"/novels/{novel}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["id"] == str(novel)
    assert str(novel) not in _trash()
    assert client.get(f"/novels/{novel}").status_code == 200
    # Not in the trash any more.
    assert client.post(f"/novels/{novel}/restore").status_code == 404


def test_emptying_the_trash_deletes_only_novels_past_their_days_with_everything_under_them(novel):
    other = uuid.UUID(client.post("/novels", json={"title": "아직 남는 작품"}).json()["id"])
    client.delete(f"/novels/{novel}")
    client.delete(f"/novels/{other}")
    _deleted_days_ago(novel, 31)
    _deleted_days_ago(other, 29)
    # A novel, an episode, a card, a validation run at least.
    assert _rows(novel) >= 4
    empty_trash()
    assert _rows(novel) == 0
    assert client.post(f"/novels/{novel}/restore").status_code == 404
    assert _rows(other) == 1
    assert str(other) in _trash()
    _delete_for_good(other)


def test_every_row_under_a_novel_goes_with_it():
    """What a purge relies on (pipeline/empty_trash.py): every foreign key in
    the database cascades, so deleting a novel deletes what's under it, and
    every table under a novel carries its novel_id (what _rows counts)."""
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        tables = [name for (name,) in connection.execute(text("SELECT name FROM sqlite_master WHERE type = 'table'"))]
        for table in tables:
            for key in connection.execute(text(f"PRAGMA foreign_key_list('{table}')")).mappings():
                assert key["on_delete"] == "CASCADE", f"{table}.{key['from']}"
    for table in Base.metadata.sorted_tables:
        if table.name not in ("novels", "jobs"):
            assert "novel_id" in table.c, table.name


def test_a_novel_past_its_days_not_yet_deleted_can_still_be_restored(novel):
    client.delete(f"/novels/{novel}")
    _deleted_days_ago(novel, 40)
    assert client.post(f"/novels/{novel}/restore").status_code == 200
    rows = _rows(novel)
    empty_trash()
    assert _rows(novel) == rows


def _run_its_job(novel: uuid.UUID) -> uuid.UUID:
    """The novel's validation job, as the runner runs it: handled, then acked.
    Returns the episode."""
    with SessionLocal() as db:
        run = db.scalar(select(ValidationRun).where(ValidationRun.novel_id == novel))
        job = db.scalar(select(Job).where(Job.target_id == run.id))
        episode_id = run.episode_id
        queued = QueuedJob(job.id, job.type, job.target_id, job.payload, job.attempts)
    handle(queued)
    with SessionLocal() as db:
        db.execute(delete(Job).where(Job.id == queued.id))
        db.commit()
    return episode_id


def _latest_after_restore(novel: uuid.UUID, episode_id: uuid.UUID) -> tuple[str, str | None]:
    assert client.post(f"/novels/{novel}/restore").status_code == 200
    latest = client.get(f"/novels/{novel}/episodes/{episode_id}/validations/latest").json()
    return latest["status"], latest["error"]


def test_a_job_that_comes_up_while_its_novel_is_in_the_trash_leaves_its_row_to_run_again(novel):
    client.delete(f"/novels/{novel}")
    episode_id = _run_its_job(novel)
    # Not "episode missing": stopped, for the author to run again.
    assert _latest_after_restore(novel, episode_id) == ("failed", "abandoned")


def test_a_novel_moved_to_the_trash_while_its_job_runs_leaves_its_row_to_run_again(novel, monkeypatch):
    def extract_then_delete(*args):
        # The author deletes the novel while the models work.
        assert client.delete(f"/novels/{novel}").status_code == 204
        return Extraction()

    monkeypatch.setattr(validate_episode, "extract_claims", extract_then_delete)
    episode_id = _run_its_job(novel)
    assert _latest_after_restore(novel, episode_id) == ("failed", "abandoned")


def test_a_novel_not_deleted_is_not_in_the_trash_and_cant_be_restored(novel):
    assert str(novel) not in _trash()
    assert client.post(f"/novels/{novel}/restore").status_code == 404


def test_a_pass_is_queued_only_while_none_is_queued_or_running():
    def passes() -> dict[uuid.UUID, str]:
        with SessionLocal() as db:
            rows = db.execute(select(Job.id, Job.status).where(Job.type == "empty_trash"))
            return {job_id: status for job_id, status in rows}

    before = passes()
    request_empty_trash()
    request_empty_trash()
    after = passes()
    try:
        assert after == before if before else len(after) == 1
        # All of them running (the timer fired mid-pass): none more.
        with SessionLocal() as db:
            db.execute(update(Job).where(Job.id.in_(after)).values(status="running"))
            db.commit()
        request_empty_trash()
        assert passes().keys() == after.keys()
    finally:
        with SessionLocal() as db:
            db.execute(delete(Job).where(Job.id.in_(passes().keys() - before.keys())))
            for job_id, status in before.items():
                db.execute(update(Job).where(Job.id == job_id).values(status=status))
            db.commit()
