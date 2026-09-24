"""characters, character_state_history tables (design doc 4.3).

- source: manual (entered directly by the author) | auto_detected (auto-generated from the manuscript) (7.4)
- Fixed attributes: name, age, eye color, hair color, height, scars, origin
- Mutable attributes: hairstyle, outfit, injury/health status, belongings
- personality: personality/speech patterns (for OOC judgment, 7.2)
- attr_sources: which episode each fixed attribute was filled in from, for the
  ones validation filled in (7.4) rather than the author: {key: episode id}.
  Validating that episode again after editing it compares against its own
  earlier wording, so that value is replaced, not flagged. A key leaves this
  map once the author changes its value on the settings screen.
"""

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin

# The attribute keys a card has — the fields of api/settings.py's FixedAttrs
# and MutableAttrs, which the settings screen edits. Claim extraction (7.4)
# describes what the manuscript says in these keys, so a card it creates
# shows up on that screen filled in.
FIXED_ATTR_KEYS = ("age", "eye_color", "hair_color", "height", "scars", "origin")
MUTABLE_ATTR_KEYS = ("hairstyle", "outfit", "condition", "belongings")


class Character(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "characters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str] = mapped_column(String, default="manual")  # manual | auto_detected
    fixed_attrs: Mapped[dict] = mapped_column(JSONB, default=dict)  # age, eye color, hair color, height, scars, origin, etc.
    mutable_attrs: Mapped[dict] = mapped_column(JSONB, default=dict)  # hairstyle, outfit, injury/health status, belongings
    personality: Mapped[dict] = mapped_column(JSONB, default=dict)  # personality keywords, speech traits, goals/values
    attr_sources: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)


class CharacterStateHistory(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "character_state_history"
    __table_args__ = (
        Index("ix_character_state_history_novel_char_episode", "novel_id", "character_id", "episode_index"),
        Index("ix_character_state_history_novel_char_story_ts", "novel_id", "character_id", "story_timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)  # serialization order (4.2)
    story_timestamp: Mapped[datetime | None] = mapped_column()  # in-story time (4.2)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
