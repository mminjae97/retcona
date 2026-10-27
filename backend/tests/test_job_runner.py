"""The job runner (workers/runner.py): what it does with each job the queue hands it."""

import uuid

from infra.queue_client import QueueClient, QueuedJob
from workers import runner
from workers.runner import MAX_ATTEMPTS, JobRunner

NOVEL = uuid.uuid4()


class FakeQueue(QueueClient):
    def __init__(self, jobs=(), recovered=0):
        self.jobs = list(jobs)
        self.acked: list[uuid.UUID] = []
        self.recovered = recovered
        self.recover_calls = 0

    def enqueue(self, db, type, target_id, payload):
        raise NotImplementedError

    def dequeue(self):
        return self.jobs.pop(0) if self.jobs else None

    def ack(self, job_id):
        self.acked.append(job_id)

    def recover(self):
        self.recover_calls += 1
        return self.recovered


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


def test_a_job_runs_with_its_novel_and_row_and_leaves_the_queue(monkeypatch):
    calls = _ran(monkeypatch)
    job = _job()
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
    assert calls == [(NOVEL, job.target_id)]
    assert queue.acked == [job.id]


def test_a_job_that_raises_still_leaves_the_queue(monkeypatch):
    def fail():
        raise RuntimeError("the database is gone")

    _ran(monkeypatch, fail)
    job = _job()
    queue = FakeQueue([job])
    JobRunner(queue, load=lambda: None).run_once()
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


def test_the_runner_queues_again_what_an_earlier_start_left_then_stops_when_told(monkeypatch):
    calls = _ran(monkeypatch)
    loaded = []
    queue = FakeQueue([_job(), _job()], recovered=1)
    job_runner = JobRunner(queue, load=lambda: loaded.append(True))
    job_runner.start()
    job_runner.stop(timeout=5)
    assert queue.recover_calls == 1
    assert loaded == [True]
    assert not job_runner._thread.is_alive()
    # It ran what it took before being told to stop.
    assert len(calls) == len(queue.acked)


def test_every_job_the_api_enqueues_has_a_handler():
    assert set(runner.HANDLERS) == {"validate_episode", "revalidate_flag", "judge_linked_claim"}
