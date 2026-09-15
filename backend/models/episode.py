"""episodes table (design doc 4.3, 2.2).

status: draft | submitted
  - Editing and saving a submitted episode flips status back to draft (2.2)
embedding: pgvector column (chapter 5, for searching similar past setting sentences)
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin

EMBEDDING_DIM = 1024  # TODO: adjust to match the actual embedding model's (KURE-v1) dimension

class Episode(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "episodes"
    __table_args__ = (
        # Backstops the app-level lock in api/episodes.py:create_episode — a
        # future insert path that skips that lock still can't create two
        # episodes with the same index for one novel (4.3).
        UniqueConstraint("novel_id", "episode_index", name="uq_episodes_novel_id_episode_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | submitted
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
    # Tracks autosave time (2.2) — bumped on every content save, not just on creation.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
