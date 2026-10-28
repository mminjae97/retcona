"""episodes table (design doc 4.3, 2.2).

status: draft | submitted
  - Editing and saving a submitted episode flips status back to draft (2.2)
"""

import uuid
from datetime import datetime

from sqlalchemy import Integer, String, Text, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin, UtcDateTime, utcnow


class Episode(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (
        # Backstops the app-level lock in api/episodes.py:create_episode — a
        # future insert path that skips that lock still can't create two
        # episodes with the same index for one novel (4.3).
        UniqueConstraint("novel_id", "episode_index", name="uq_episodes_novel_id_episode_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | submitted
    # Tracks autosave time (2.2) — bumped on every content save, not just on
    # creation. To the microsecond (utcnow): a validation run's result is out
    # of date once this differs from what it read (pipeline/validate_episode.py).
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, default=utcnow, server_default=func.now(), onupdate=utcnow, nullable=False
    )
