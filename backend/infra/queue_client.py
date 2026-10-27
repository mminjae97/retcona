"""QueueClient interface (design doc 10.4.3, 10.2): the local job queue.

enqueue(db, ...) / dequeue() / ack(job_id), and recover() at startup. The API
and the job runner (workers/runner.py) use only this interface;
DatabaseQueueClient keeps the queue in a table of the app's own database
(models/job.py), so jobs waiting survive closing the app and no other server
is needed.

Delivery is at least once (10.4.4): a job the app closed in the middle of is
run again, so every job checks its row is still waiting for it before doing
anything (its idempotency record).
"""

import functools
import uuid
from abc import ABC, abstractmethod
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, delete, exists, func, select, update
from sqlalchemy.orm import Session

from models.db import SessionLocal
from models.job import Job


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
    def recover(self) -> int:
        """Queue again the jobs left running by an earlier start of the app, and
        return how many. Only when no job is running: at startup, before the
        runner takes any."""


def job_pending(target_id: Any) -> ColumnElement[bool]:
    """SQL: a job for this row (an id, or a column of the row's table) is still
    queued or running. A row waiting for a job with none of its jobs left was
    lost. The row is finished before its job is acked, so whatever sees the job
    gone also sees the row finished, if it was."""
    return exists().where(Job.target_id == target_id)


class DatabaseQueueClient(QueueClient):
    def enqueue(self, db: Session, type: str, target_id: uuid.UUID | None, payload: dict[str, Any]) -> uuid.UUID:
        job = Job(id=uuid.uuid4(), type=type, target_id=target_id, payload=payload, status="queued")
        db.add(job)
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
            # Conditional, so a job is only ever taken once. (Another process
            # taking the same one first leaves this with none; the runner looks
            # again shortly.)
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

    def recover(self) -> int:
        with SessionLocal() as db:
            requeued = db.scalars(
                update(Job).where(Job.status == "running").values(status="queued").returning(Job.id)
            ).all()
            db.commit()
        return len(requeued)


@functools.cache
def get_queue_client() -> QueueClient:
    return DatabaseQueueClient()
