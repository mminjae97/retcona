"""Common Base and the multi-tenancy (per-novel isolation) mixin.

Design doc 10.1: every read/write must be filtered by novel_id.
Models that inherit NovelScopedMixin below get a novel_id column.
Repository functions should likewise take novel_id as a required argument (6.2).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NovelScopedMixin:
    """Every table inheriting this mixin has a required novel_id FK (4.1, 10.1)."""

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False, index=True
    )
