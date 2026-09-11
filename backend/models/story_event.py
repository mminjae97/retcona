"""story_events, event_participants, event_locations, event_links (설계서 4.3, 8.3).

스토리 타임라인 그래프의 노드/엣지.
event_links.link_type: 순차 | 분기 | 합류
event_links.branch_reason: 분기를 일으킨 캐릭터·장소
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class StoryEvent(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "story_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    story_timestamp: Mapped[datetime | None] = mapped_column()
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class EventParticipant(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "event_participants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("story_events.id"), nullable=False)
    character_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"), nullable=False)


class EventLocation(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "event_locations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("story_events.id"), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("locations.id"), nullable=False)


class EventLink(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "event_links"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("story_events.id"), nullable=False)
    to_event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("story_events.id"), nullable=False)
    link_type: Mapped[str] = mapped_column(String, nullable=False)  # 순차 | 분기 | 합류
    branch_reason: Mapped[str | None] = mapped_column(Text)
