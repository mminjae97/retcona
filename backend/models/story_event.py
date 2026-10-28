"""story_events, event_participants, event_locations, event_links (design doc 4.3, 8.3).

Nodes/edges of the story timeline graph.
event_links.link_type: sequential | branch | merge
event_links.branch_reason: the character/location that caused the branch
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class StoryEvent(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "story_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    story_timestamp: Mapped[datetime | None] = mapped_column()
    summary: Mapped[str] = mapped_column(Text, nullable=False)


class EventParticipant(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "event_participants"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("story_events.id", ondelete="CASCADE"), nullable=False, index=True)
    character_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True)


class EventLocation(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "event_locations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("story_events.id", ondelete="CASCADE"), nullable=False, index=True)
    location_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False, index=True)


class EventLink(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "event_links"
    __table_args__ = (
        Index("ix_event_links_novel_from_event", "novel_id", "from_event_id"),
        Index("ix_event_links_novel_to_event", "novel_id", "to_event_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    from_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("story_events.id", ondelete="CASCADE"), nullable=False, index=True)
    to_event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("story_events.id", ondelete="CASCADE"), nullable=False, index=True)
    link_type: Mapped[str] = mapped_column(String, nullable=False)  # sequential | branch | merge
    branch_reason: Mapped[str | None] = mapped_column(Text)
