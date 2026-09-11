"""relations 테이블 (설계서 4.3, 8.2).

인물 간 관계, 장소 간 거리/연결 정보.
relation_type: 가족 | 연인 | 원수 | 사제 등 (8.1)
direction: 방향성 있는 관계 표시용 (8.1)
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
    direction: Mapped[str | None] = mapped_column(String)  # None(무방향) | "from_to" | "to_from"
