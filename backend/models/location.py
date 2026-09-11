"""locations, location_state_history 테이블 (설계서 4.3).

지리적 특징, 다른 장소와의 거리·연결 관계를 저장한다.
source: manual | auto_detected (7.4)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class Location(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, default="manual")
    geo_attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # 지리적 특징, 타 장소와의 거리/연결


class LocationStateHistory(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "location_state_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    story_timestamp: Mapped[datetime | None] = mapped_column()
    state: Mapped[dict] = mapped_column(JSON, default=dict)
