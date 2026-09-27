"""flag_revalidations table (design doc 7.5).

One row per "revalidate this flag" request: the author supplemented the
setting a flag was judged against (or changed it on the settings screen) and
has only that flag judged again, not the whole episode. The API creates it
(queued) and enqueues a job carrying its id; the CPU worker moves it to
running, then succeeded or failed (pipeline/revalidate_flag.py). As with
validation_runs, it is also the worker's idempotency record (10.4.4).

- outcome (succeeded only): resolved — the flag no longer contradicts the
  setting (it becomes resolved_by_revalidation) | contradicts — it still does
  (it stays open, with the new confidence)
- setting: the card's value the flag was judged against — for a resolved
  flag, the setting that resolved it (7.5: kept to learn from later); None if
  the card had no value for the attribute any more
- confidence: the NLI contradiction probability, when the model was asked
  (not for a setting that's empty or that the manuscript's value repeats)

A run that validates the episode again replaces its flags, and their
revalidations go with them (ON DELETE CASCADE).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class FlagRevalidation(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "flag_revalidations"
    __table_args__ = (Index("ix_flag_revalidations_novel_flag_created", "novel_id", "flag_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    flag_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contradiction_flags.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String, nullable=False, default="queued")  # queued | running | succeeded | failed
    error: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String)  # resolved | contradicts
    setting: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
