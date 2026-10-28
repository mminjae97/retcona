"""validation_runs table (design doc 2.2, 10.2, 10.4.4).

One row per "run validation" request on an episode. The API creates it
(queued) with a job for it (models/job.py); the job moves it to running, then
succeeded or failed. It is also the job's idempotency record (10.4.4): a job
whose run is finished already (or was given up on) is skipped.

- content_updated_at: the episode's updated_at as of the content the job
  validated — a later save makes this result out of date (2.2)
- summary: what the run found, for the editor to show (claim count, the
  characters/locations it registered as new)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin, UtcDateTime


class ValidationRun(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "validation_runs"
    __table_args__ = (Index("ix_validation_runs_novel_episode_created", "novel_id", "episode_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued | running | succeeded | failed
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}", nullable=False)
    content_updated_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
