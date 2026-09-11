"""world_settings 테이블 (설계서 4.3, 2.3).

category: 시대적 배경 | 마법·무공 체계 | 세력·조직 | 역사 | 기타 규칙
"""

import uuid

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class WorldSetting(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "world_settings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
