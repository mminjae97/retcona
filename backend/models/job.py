"""jobs table: the local job queue (design doc 10.2, 10.4.4).

One row per job waiting to run or running; the job runner (workers/runner.py)
deletes it once the job is done (infra/queue_client.py, ack). A job's own
outcome is recorded on the row it works on (a validation run, a flag
revalidation, a claim), which is also its idempotency record: a job whose row
isn't waiting for it any more is skipped.

- target_id: that row's id. A row still waiting for a job when no job for it is
  left was lost (its job failed in a way it couldn't record), which the API
  tells the author (api/episodes.py, abandoned)
- payload: what the job needs besides target_id (novel_id, ...)
- status: queued | running. A job left running when the app closed is queued
  again when it starts (10.4.4)
- attempts: how many times it has been started, so a job the app keeps
  closing or crashing in the middle of is given up on after a few

Not novel-scoped (NovelScopedMixin): the queue is the app's, and a job's
novel_id is in its payload, which the job filters by.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Job(Base, TimestampMixin):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type: Mapped[str] = mapped_column(String, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), index=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued | running
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
