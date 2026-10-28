"""QueueClient interface (design doc 10.4.3, 10.2): the local job queue.

enqueue(db, ...) / dequeue() / ack(job_id), and around them what the job
runner (workers/runner.py) needs: hold_runner_lock() and recover() at startup
(and the lock checked again before each job), wait_for_job() / wake()
while idle. The API and the runner use only this
interface; DatabaseQueueClient keeps the queue in a table of the app's own
database (models/job.py), so jobs waiting survive closing the app and no other
server is needed.

Delivery is at least once (10.4.4): a job the app closed in the middle of is
run again, so every job checks its row is still waiting for it before doing
anything (its idempotency record). Only one runner takes jobs from a database
(hold_runner_lock): the process that holds a lock on a file beside it.
"""

import functools
import os
import threading
import uuid
from abc import ABC, abstractmethod
from typing import IO, Any, NamedTuple

from sqlalchemy import ColumnElement, delete, event, exists, func, select, update
from sqlalchemy.orm import Session

from models.db import SessionLocal, database_path
from models.job import Job

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class QueuedJob(NamedTuple):
    id: uuid.UUID
    type: str
    target_id: uuid.UUID | None
    payload: dict[str, Any]
    # How many times it has been started, this one included.
    attempts: int


class QueueClient(ABC):
    @abstractmethod
    def enqueue(self, db: Session, type: str, target_id: uuid.UUID | None, payload: dict[str, Any]) -> uuid.UUID:
        """Add a job in the caller's transaction and return its id: it is queued
        when the caller commits, together with the row it works on, so neither
        is ever there without the other."""

    @abstractmethod
    def dequeue(self) -> QueuedJob | None:
        """Take the oldest queued job (it is running from then on). None if there isn't one."""

    @abstractmethod
    def ack(self, job_id: uuid.UUID) -> None:
        """The job is done (whatever its outcome): it leaves the queue."""

    @abstractmethod
    def hold_runner_lock(self) -> bool:
        """Become (or still be) the one runner of this database, for as long as
        this process lives; False if another process is. Only the holder may
        recover and take jobs."""

    @abstractmethod
    def recover(self) -> int:
        """Queue again the jobs left running by an earlier start of the app, and
        return how many. Only while holding the runner lock, before taking any."""

    @abstractmethod
    def wait_for_job(self, timeout: float) -> None:
        """Wait until a job may have been queued (one was committed here, or
        wake() was called), or the timeout passes."""

    @abstractmethod
    def wake(self) -> None:
        """End a wait_for_job now."""


def job_pending(target_id: Any) -> ColumnElement[bool]:
    """SQL: a job for this row (an id, or a column of the row's table) is still
    queued or running. A row waiting for a job with none of its jobs left was
    lost. The row is finished before its job is acked, so whatever sees the job
    gone also sees the row finished, if it was.

    How long a job has been running doesn't count: a slow one (on a CPU, or
    while the PC slept) can't be told from one that will never return. A job
    that never returns holds up the queue until the app restarts, which runs it
    again, and gives up on it after a few starts (workers/runner.py)."""
    return exists().where(Job.target_id == target_id)


def job_type_pending(type: str) -> ColumnElement[bool]:
    """SQL: a job of this type is still queued or running — for a job with no
    row of its own (empty_trash), which needs only one at a time. Checked and
    enqueued in one transaction, which no other can write in between
    (models/db.py), it's queued at most once."""
    return exists().where(Job.type == type)


# Set when a session that enqueued a job commits, so an idle runner in this
# process starts it at once instead of at its next look.
_job_committed = threading.Event()
_ENQUEUED = "retcona_job_enqueued"


@event.listens_for(Session, "after_commit")
def _wake_runner(session: Session) -> None:
    if session.info.pop(_ENQUEUED, False):
        _job_committed.set()


@event.listens_for(Session, "after_rollback")
def _forget_enqueued(session: Session) -> None:
    session.info.pop(_ENQUEUED, None)


def _try_lock(file: IO[bytes]) -> bool:
    """An exclusive lock on the file, held until it's closed — which the OS
    does when the process ends, however it ends. False if another holds it."""
    try:
        if os.name == "nt":
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


class DatabaseQueueClient(QueueClient):
    def __init__(self) -> None:
        # The lock file beside the database, kept open and locked for the
        # process's lifetime once taken.
        self._lock_file: IO[bytes] | None = None

    def enqueue(self, db: Session, type: str, target_id: uuid.UUID | None, payload: dict[str, Any]) -> uuid.UUID:
        job = Job(id=uuid.uuid4(), type=type, target_id=target_id, payload=payload, status="queued")
        db.add(job)
        db.info[_ENQUEUED] = True
        return job.id

    def dequeue(self) -> QueuedJob | None:
        oldest = (
            select(Job.id)
            .where(Job.status == "queued")
            .order_by(Job.created_at, Job.id)
            .limit(1)
            .scalar_subquery()
        )
        with SessionLocal() as db:
            # Conditional, so a job is only ever taken once.
            row = db.execute(
                update(Job)
                .where(Job.id == oldest, Job.status == "queued")
                .values(status="running", started_at=func.now(), attempts=Job.attempts + 1)
                .returning(Job.id, Job.type, Job.target_id, Job.payload, Job.attempts)
            ).one_or_none()
            db.commit()
        return None if row is None else QueuedJob(*row)

    def ack(self, job_id: uuid.UUID) -> None:
        with SessionLocal() as db:
            db.execute(delete(Job).where(Job.id == job_id))
            db.commit()

    def hold_runner_lock(self) -> bool:
        # A file lock isn't lost while its file is open: once taken, it's held.
        if self._lock_file is not None:
            return True
        path = database_path()
        file = open(path.with_name(f"{path.name}.runner-lock"), "a+b")  # noqa: SIM115 (held open for the process)
        if not _try_lock(file):
            file.close()
            return False
        self._lock_file = file
        return True

    def recover(self) -> int:
        with SessionLocal() as db:
            requeued = db.scalars(
                update(Job).where(Job.status == "running").values(status="queued").returning(Job.id)
            ).all()
            db.commit()
        return len(requeued)

    def wait_for_job(self, timeout: float) -> None:
        _job_committed.wait(timeout)
        # Cleared after waking, not before waiting: a job committed meanwhile is
        # found by the dequeue that follows.
        _job_committed.clear()

    def wake(self) -> None:
        _job_committed.set()


@functools.cache
def get_queue_client() -> QueueClient:
    return DatabaseQueueClient()
