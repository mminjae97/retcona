"""공통 Base 및 멀티테넌시(작품 단위 격리) 믹스인.

설계서 10.1: 모든 조회·쓰기는 novel_id 필터를 강제한다.
아래 NovelScopedMixin을 상속하는 모델은 novel_id 컬럼을 갖는다.
리포지토리 함수를 작성할 때도 novel_id를 필수 인자로 받도록 한다 (6.2).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class NovelScopedMixin:
    """이 믹스인을 상속하는 모든 테이블은 novel_id FK를 필수로 갖는다 (4.1, 10.1)."""

    novel_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("novels.id"), nullable=False, index=True
    )
