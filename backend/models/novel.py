"""novels table (design doc 4.1, 4.3).

The top level: there are no accounts, so a novel belongs to no one but the app's
one author.
deleted_at: soft-delete timestamp (2.6), the trash. Restorable for TRASH_KEPT,
then deleted for good with everything under it (pipeline/empty_trash.py).
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin

TRASH_KEPT = timedelta(days=30)


class Novel(Base, TimestampMixin):
    __tablename__ = "novels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
