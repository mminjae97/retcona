"""locations, location_state_history tables (design doc 4.3).

Stores geographic features and distance/connection relationships to other locations.
source: manual | auto_detected (7.4)
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin

# geo_attrs keys claim extraction fills in (7.4): the geographic features the
# manuscript describes. Distances/connections live in relations (8.1).
GEO_ATTR_KEYS = ("features",)


class Location(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "locations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, default="manual")
    geo_attrs: Mapped[dict] = mapped_column(JSONB, default=dict)  # geographic features, distance/connections to other locations


class LocationStateHistory(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "location_state_history"
    __table_args__ = (
        Index("ix_location_state_history_novel_loc_episode", "novel_id", "location_id", "episode_index"),
        Index("ix_location_state_history_novel_loc_story_ts", "novel_id", "location_id", "story_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    story_timestamp: Mapped[datetime | None] = mapped_column()
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
