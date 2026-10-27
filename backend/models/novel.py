"""novels table (design doc 4.1, 4.3).

The top level: there are no accounts, so a novel belongs to no one but the app's
one author.
deleted_at: soft-delete timestamp (2.6), the trash. Permanently deleting it after 30
days is the local job queue's to come (roadmap stage 6); until then it stays.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class Novel(Base, TimestampMixin):
    __tablename__ = "novels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
