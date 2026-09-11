"""episodes 테이블 (설계서 4.3, 2.2).

status: draft | submitted
  - submitted 화를 수정해 저장하면 status가 다시 draft로 전환된다 (2.2)
embedding: pgvector 컬럼 (5장, 유사 과거 설정 문장 검색용)
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin

EMBEDDING_DIM = 1024  # TODO: 실제 사용하는 임베딩 모델(KURE-v1)의 차원에 맞춰 조정


class Episode(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft | submitted
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
