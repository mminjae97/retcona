"""characters, character_state_history 테이블 (설계서 4.3).

- source: manual(작가 직접 입력) | auto_detected(원고에서 자동 생성) (7.4)
- 고정 속성: 이름·나이·눈 색깔·머리색·신장·흉터·출신
- 가변 속성: 헤어스타일·복장·부상/건강 상태·소지품
- personality: 성격·말투 (OOC 판단용, 7.2)
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
    fixed_attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # 나이, 눈 색깔, 머리색, 신장, 흉터, 출신 등
    mutable_attrs: Mapped[dict] = mapped_column(JSON, default=dict)  # 헤어스타일, 복장, 부상/건강 상태, 소지품
    personality: Mapped[dict] = mapped_column(JSON, default=dict)  # 성격 키워드, 말투 특징, 목표/가치관


class CharacterStateHistory(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "character_state_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    character_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("characters.id"), nullable=False)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 연재 순서 (4.2)
    story_timestamp: Mapped[datetime | None] = mapped_column()  # 극중 시간 (4.2)
    state: Mapped[dict] = mapped_column(JSON, default=dict)
