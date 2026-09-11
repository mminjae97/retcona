"""relations table (design doc 4.3, 8.2).

Relationships between characters, and distance/connection information between locations.
relation_type: family | romantic | rival | mentor, etc. (8.1)
direction: indicates directional relationships (8.1)
"""

import uuid

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class Relation(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "relations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    from_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    to_entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_kind: Mapped[str] = mapped_column(String, nullable=False)  # character | location
    relation_type: Mapped[str] = mapped_column(String, nullable=False)
    direction: Mapped[str | None] = mapped_column(String)  # None (undirected) | "from_to" | "to_from"
