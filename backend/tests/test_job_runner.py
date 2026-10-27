"""The job runner (workers/runner.py): what it does with each job the queue hands it."""

import threading
import time
import uuid

import pytest

from infra.queue_client import QueueClient, QueuedJob
from workers import runner
from workers.runner import MAX_ATTEMPTS, JobRunner

NOVEL = uuid.uuid4()
# The novels in the trash (or deleted for good), in place of the database.
TRASHED: set[uuid.UUID] = set()


@pytest.fixture(autouse=True)
def _novels(monkeypatch):
    TRASHED.clear()
    monkeypatch.setattr(runner, "novel_in_place", lambda novel_id: novel_id not in TRASHED)


class FakeQueue(QueueClient):
    """In memory; `events` records the calls in order."""

    def __init__(self, jobs=(), lock=True, fail=()):
        self.jobs = list(jobs)
        self.events: list[str] = []
        self.acked: list[uuid.UUID] = []
        self.lock = lock
        # Method names to fail once each.
        self.fail = set(fail)
        self.woken = threading.Event()

    def _maybe_fail(self, name):
        self.events.append(name)
        if name in self.fail:
            self.fail.discard(name)
            raise RuntimeError(f"{name} failed")

    def enqueue(self, db, type, target_id, payload):
        raise NotImplementedError

    def dequeue(self):
        self._maybe_fail("dequeue")
        return self.jobs.pop(0) if self.jobs else None

    def ack(self, job_id):
        self._maybe_fail("ack")
        self.acked.append(job_id)

    def hold_runner_lock(self):
        self._maybe_fail("lock")
        return self.lock

    def recover(self):
        self._maybe_fail("recover")
        return 0

    def wait_for_job(self, timeout):
        self.woken.wait(min(timeout, 0.05))

    def wake(self):
        self.woken.set()


def _job(type="validate_episode", attempts=1):
    return QueuedJob(uuid.uuid4(), type, uuid.uuid4(), {"novel_id": str(NOVEL)}, attempts)


def _ran(monkeypatch, handler=None):
    calls = []

    def record(novel_id, target_id):
        calls.append((novel_id, target_id))
        if handler:
            handler()

    monkeypatch.setitem(runner.HANDLERS, "validate_episode", record)
    return calls


def _until(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def test_a_job_runs_with_its_novel_and_row_and_leaves_the_queue(monkeypatch):
    calls = _ran(monkeypatch)
    job = _job()
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert calls == [(NOVEL, job.target_id)]
    assert queue.acked == [job.id]


def test_an_app_job_runs_with_no_novel_or_row(monkeypatch):
    calls = []
    monkeypatch.setitem(runner.APP_HANDLERS, "empty_trash", lambda: calls.append("emptied"))
    job = QueuedJob(uuid.uuid4(), "empty_trash", None, {}, 1)
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert calls == ["emptied"]
    assert queue.acked == [job.id]


def test_a_job_of_a_novel_in_the_trash_is_skipped_without_running(monkeypatch):
    calls = _ran(monkeypatch)
    TRASHED.add(NOVEL)
    job = _job()
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert calls == []
    assert queue.acked == [job.id]


def test_a_job_that_raises_still_leaves_the_queue(monkeypatch):
    def fail():
        raise RuntimeError("the database is gone")

    _ran(monkeypatch, fail)
    job = _job()
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert queue.acked == [job.id]


def test_an_ack_that_fails_is_tried_again(monkeypatch):
    _ran(monkeypatch)
    monkeypatch.setattr(runner, "QUEUE_RETRY_SECONDS", 0.01)
    job = _job()
    queue = FakeQueue([job], fail={"ack"})
    JobRunner(queue, load=lambda: None).run_once()
    assert queue.events.count("ack") == 2
    assert queue.acked == [job.id]


def test_a_job_started_too_many_times_is_given_up_on_without_running(monkeypatch):
    calls = _ran(monkeypatch)
    job = _job(attempts=MAX_ATTEMPTS + 1)
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert calls == []
    assert queue.acked == [job.id]
    # The last allowed attempt still runs.
    queue = FakeQueue([_job(attempts=MAX_ATTEMPTS)])
    JobRunner(queue, load=lambda: None).run_once()
    assert len(calls) == 1


def test_a_job_of_an_unknown_type_is_dropped(monkeypatch):
    calls = _ran(monkeypatch)
    job = _job(type="no_such_job")
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert calls == []
    assert queue.acked == [job.id]


def test_the_runner_locks_recovers_and_loads_before_taking_jobs(monkeypatch):
    calls = _ran(monkeypatch)
    monkeypatch.setattr(runner, "QUEUE_RETRY_SECONDS", 0.01)
    jobs = [_job(), _job()]
    # A failed recovery is tried again before any job is taken.
    queue = FakeQueue(jobs, fail={"recover"})
    loaded = []
    job_runner = JobRunner(queue, load=lambda: loaded.append(queue.events[-1]))
    job_runner.start()
    _until(lambda: len(queue.acked) == 2)
    job_runner.stop(timeout=5)
    assert not job_runner._thread.is_alive()
    assert queue.events[:3] == ["lock", "recover", "recover"]
    assert loaded == ["recover"]
    assert calls == [(NOVEL, job.target_id) for job in jobs]


def test_without_the_lock_the_runner_takes_no_job(monkeypatch):
    calls = _ran(monkeypatch)
    monkeypatch.setattr(runner, "LOCK_RETRY_SECONDS", 0.01)
    queue = FakeQueue([_job()], lock=False)
    job_runner = JobRunner(queue, load=lambda: None)
    job_runner.start()
    _until(lambda: queue.events.count("lock") >= 3)
    job_runner.stop(timeout=5)
    assert set(queue.events) == {"lock"}
    assert calls == []


def test_closing_in_the_middle_of_a_job_leaves_it_for_the_next_start(monkeypatch):
    started, finish = threading.Event(), threading.Event()

    def slow():
        started.set()
        finish.wait(5)

    _ran(monkeypatch, slow)
    job = _job()
    queue = FakeQueue([job])
    job_runner = JobRunner(queue, load=lambda: None)
    job_runner.start()
    assert started.wait(5)
    job_runner.stop(timeout=0.05)
    # Not acked: still in the queue, running, for the next start's recover()
    # to queue again as one attempt.
    assert queue.acked == []
    finish.set()


def test_stopping_wakes_an_idle_runner():
    queue = FakeQueue()
    job_runner = JobRunner(queue, load=lambda: None)
    job_runner.start()
    _until(lambda: "dequeue" in queue.events)
    job_runner.stop(timeout=5)
    assert queue.woken.is_set()
    assert not job_runner._thread.is_alive()


def test_prepare_locks_and_recovers_before_the_runner_starts(monkeypatch):
    _ran(monkeypatch)
    queue = FakeQueue([_job()])
    job_runner = JobRunner(queue, load=lambda: None)
    job_runner.prepare()
    assert queue.events == ["lock", "recover"]
    job_runner.start()
    _until(lambda: len(queue.acked) == 1)
    job_runner.stop(timeout=5)
    # Not recovered a second time once started.
    assert queue.events.count("recover") == 1


def test_a_lost_lock_is_taken_again_with_a_recovery_before_the_next_job(monkeypatch):
    calls = _ran(monkeypatch)
    queue = FakeQueue([_job()])
    held = iter([True, False, True])
    queue.hold_runner_lock = lambda: queue.events.append("lock") or next(held, True)
    job_runner = JobRunner(queue, load=lambda: None)
    job_runner.start()
    _until(lambda: len(queue.acked) == 1)
    job_runner.stop(timeout=5)
    assert queue.events[:5] == ["lock", "recover", "lock", "lock", "recover"]
    assert len(calls) == 1


def test_every_job_the_api_enqueues_has_a_handler():
    assert set(runner.HANDLERS) == {"validate_episode", "revalidate_flag", "judge_linked_claim"}
