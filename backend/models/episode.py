"""episodes table (design doc 4.3, 2.2).

status: draft | submitted
  - Editing and saving a submitted episode flips status back to draft (2.2)
embedding: pgvector column (chapter 5, for searching similar past setting sentences)
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin

EMBEDDING_DIM = 1024  # TODO: adjust to match the actual embedding model's (KURE-v1) dimension

class Episode(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | submitted
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
