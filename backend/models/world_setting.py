"""world_settings table (design doc 4.3, 2.3).

category: era/setting | magic·martial arts system | faction/organization | history | other rules
"""

import uuid

from sqlalchemy import String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class WorldSetting(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "world_settings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
