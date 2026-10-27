"""The trash against a real database (api/novels.py, pipeline/empty_trash.py).

Opt-in, like tests/test_queue_db.py: set RETCONA_DB_TESTS=1 and DATABASE_URL
to a migrated database no backend is running against.

    RETCONA_DB_TESTS=1 DATABASE_URL=postgresql+psycopg://... pytest tests/test_trash_db.py
"""

import os
import uuid
from datetime import datetime, timedelta

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("RETCONA_DB_TESTS") != "1", reason="needs RETCONA_DB_TESTS=1 and a database")

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from api.main import CLIENT_HEADER, app
from models.base import Base
from models.db import SessionLocal
from models.novel import TRASH_KEPT, Novel
from pipeline.empty_trash import empty_trash

# Not as a context manager: no lifespan, so no runner of its own.
client = TestClient(app, base_url="http://localhost:8000", headers={CLIENT_HEADER: "1"})


@pytest.fixture
def novel():
    novel_id = client.post("/novels", json={"title": "휴지통 시험"}).json()["id"]
    episode_id = client.post(f"/novels/{novel_id}/episodes", json={"content": "레온은 푸른 눈이었다."}).json()["id"]
    client.post(f"/novels/{novel_id}/characters", json={"name": "레온"})
    client.post(f"/novels/{novel_id}/episodes/{episode_id}/validations")
    yield uuid.UUID(novel_id)
    # Whatever the test left it as, deleted for good.
    _deleted_days_ago(uuid.UUID(novel_id), 31)
    empty_trash()


def _trash() -> dict[str, dict]:
    response = client.get("/novels/trash")
    assert response.status_code == 200, response.text
    return {each["id"]: each for each in response.json()}


def _deleted_days_ago(novel_id: uuid.UUID, days: int) -> None:
    with SessionLocal() as db:
        db.execute(
            update(Novel).where(Novel.id == novel_id).values(deleted_at=func.now() - timedelta(days=days))
        )
        db.commit()


def _rows(novel_id: uuid.UUID) -> int:
    """The novel's rows, in its own table and every one under it."""
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
    _deleted_days_ago(other, 31)
    empty_trash()


def test_a_novel_past_its_days_not_yet_deleted_can_still_be_restored(novel):
    client.delete(f"/novels/{novel}")
    _deleted_days_ago(novel, 40)
    assert client.post(f"/novels/{novel}/restore").status_code == 200
    rows = _rows(novel)
    empty_trash()
    assert _rows(novel) == rows


def test_a_novel_not_deleted_is_not_in_the_trash_and_cant_be_restored(novel):
    assert str(novel) not in _trash()
    assert client.post(f"/novels/{novel}/restore").status_code == 404
