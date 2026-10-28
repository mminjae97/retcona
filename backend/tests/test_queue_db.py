"""The job queue against the tests' database (infra/queue_client.py,
api/episodes.py; tests/conftest.py). The tests make their own novel and touch
only its rows and jobs."""

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, update

from api.main import CLIENT_HEADER, app
from infra.queue_client import DatabaseQueueClient
from models.db import SessionLocal, unlock_file
from models.job import Job
from pipeline import validate_episode as ve

# Not as a context manager: no lifespan, so no runner of its own.
client = TestClient(app, base_url="http://localhost:8000", headers={CLIENT_HEADER: "1"})


@pytest.fixture
def episode():
    novel_id = client.post("/novels", json={"title": "큐 시험"}).json()["id"]
    episode_id = client.post(f"/novels/{novel_id}/episodes", json={"content": "레온은 푸른 눈이었다."}).json()["id"]
    yield uuid.UUID(novel_id), uuid.UUID(episode_id)
    _drop_jobs(uuid.UUID(novel_id))
    client.delete(f"/novels/{novel_id}")


def _drop_jobs(novel_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        db.execute(delete(Job).where(Job.payload["novel_id"].as_string() == str(novel_id)))
        db.commit()


def _jobs(novel_id: uuid.UUID) -> list[Job]:
    with SessionLocal() as db:
        return list(db.scalars(select(Job).where(Job.payload["novel_id"].as_string() == str(novel_id))))


def _validate(novel_id, episode_id) -> dict:
    response = client.post(f"/novels/{novel_id}/episodes/{episode_id}/validations")
    assert response.status_code == 202, response.text
    return response.json()


def _latest(novel_id, episode_id) -> dict:
    return client.get(f"/novels/{novel_id}/episodes/{episode_id}/validations/latest").json()


def _take(queue: DatabaseQueueClient, target: uuid.UUID):
    # Only this test's job: another test's, or one left from an earlier run,
    # could be older. Those are taken too, and put back as they were.
    others = []
    try:
        while (job := queue.dequeue()) is not None:
            if job.target_id == target:
                return job
            others.append(job)
        raise AssertionError("the test's job is in the queue")
    finally:
        with SessionLocal() as db:
            for other in others:
                db.execute(
                    update(Job).where(Job.id == other.id).values(status="queued", attempts=other.attempts - 1)
                )
            db.commit()


def test_a_run_is_queued_with_its_job_and_a_second_request_returns_it(episode):
    novel_id, episode_id = episode
    run = _validate(novel_id, episode_id)
    assert _validate(novel_id, episode_id)["id"] == run["id"]
    [job] = _jobs(novel_id)
    assert (job.type, job.target_id, job.status) == ("validate_episode", uuid.UUID(run["id"]), "queued")
    assert _latest(novel_id, episode_id)["status"] == "queued"


def test_a_job_left_running_is_recovered_and_its_run_claimed_again(episode):
    novel_id, episode_id = episode
    run_id = uuid.UUID(_validate(novel_id, episode_id)["id"])
    queue = DatabaseQueueClient()
    job = _take(queue, run_id)
    assert job.attempts == 1
    assert ve._claim_run(novel_id, run_id) == episode_id
    assert queue.recover() >= 1
    again = _take(queue, run_id)
    assert (again.id, again.attempts) == (job.id, 2)
    # Running when the app closed: claimed again.
    assert ve._claim_run(novel_id, run_id) == episode_id
    assert _latest(novel_id, episode_id)["status"] == "running"
    ve._finish_failed(novel_id, run_id, "internal")
    assert ve._claim_run(novel_id, run_id) is None
    queue.ack(job.id)
    assert _jobs(novel_id) == []


def test_a_job_the_app_closed_in_the_middle_of_counts_as_an_attempt(episode):
    novel_id, episode_id = episode
    run_id = uuid.UUID(_validate(novel_id, episode_id)["id"])
    queue = DatabaseQueueClient()
    attempts = []
    for _ in range(3):
        attempts.append(_take(queue, run_id).attempts)
        queue.recover()
    assert attempts == [1, 2, 3]


def test_a_run_whose_job_is_gone_is_abandoned_but_one_still_running_is_not(episode):
    novel_id, episode_id = episode
    run_id = uuid.UUID(_validate(novel_id, episode_id)["id"])
    queue = DatabaseQueueClient()
    job = _take(queue, run_id)
    ve._claim_run(novel_id, run_id)
    # Running for however long: still pending.
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == job.id).values(started_at=datetime.now(UTC) - timedelta(hours=2)))
        db.commit()
    assert _latest(novel_id, episode_id)["status"] == "running"
    queue.ack(job.id)
    latest = _latest(novel_id, episode_id)
    assert (latest["status"], latest["error"]) == ("failed", "abandoned")


def test_one_runner_lock_per_database_free_again_when_its_holder_closes_it():
    first, second = DatabaseQueueClient(), DatabaseQueueClient()
    try:
        assert first.hold_runner_lock()
        assert first.hold_runner_lock(), "still held"
        assert not second.hold_runner_lock()
        # The holder lets it go (as the OS does when its process ends).
        unlock_file(first._lock_file)
        assert second.hold_runner_lock()
    finally:
        for each in (first, second):
            if each._lock_file is not None and not each._lock_file.closed:
                unlock_file(each._lock_file)


def test_a_committed_job_wakes_an_idle_runner(episode):
    novel_id, episode_id = episode
    queue = DatabaseQueueClient()
    queue.wait_for_job(0)  # clears an earlier wake
    woke = []
    waiter = threading.Thread(target=lambda: (queue.wait_for_job(10), woke.append(time.monotonic())))
    started = time.monotonic()
    waiter.start()
    time.sleep(0.2)
    _validate(novel_id, episode_id)
    waiter.join(5)
    assert woke and woke[0] - started < 2
