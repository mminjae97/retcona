"""validation_runs table (design doc 2.2, 10.2, 10.4.4).

One row per "run validation" request on an episode. The API creates it
(queued) and enqueues a job carrying its id; the worker moves it to running,
then succeeded or failed. It is also the worker's idempotency record (10.4.4):
a job whose run isn't queued any more was already taken, and is skipped.

- content_updated_at: the episode's updated_at as of the content the worker
  validated — a later save makes this result out of date (2.2)
- summary: what the run found, for the editor to show (claim count, the
  characters/locations it registered as new)
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class ValidationRun(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "validation_runs"
    __table_args__ = (Index("ix_validation_runs_novel_episode_created", "novel_id", "episode_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued | running | succeeded | failed
    error: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)
    content_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
