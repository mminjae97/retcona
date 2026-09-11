"""characters, character_state_history tables (design doc 4.3).

- source: manual (entered directly by the author) | auto_detected (auto-generated from the manuscript) (7.4)
- Fixed attributes: name, age, eye color, hair color, height, scars, origin
- Mutable attributes: hairstyle, outfit, injury/health status, belongings
- personality: personality/speech patterns (for OOC judgment, 7.2)
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class Character(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | auto_detected
    fixed_attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # age, eye color, hair color, height, scars, origin, etc.
    mutable_attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # hairstyle, outfit, injury/health status, belongings
    personality: Mapped[dict] = mapped_column(JSON, default=dict)  # personality keywords, speech traits, goals/values


class CharacterStateHistory(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "character_state_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)  # serialization order (4.2)
    story_timestamp: Mapped[datetime | None] = mapped_column()  # in-story time (4.2)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
