"""users 테이블 (설계서 4.1, 4.3).

- nickname: 필명 (3.6) — 2~20자, 중복 허용
- provider/provider_id: 소셜 로그인 식별 (3.1)
- password_hash: 자체 로그인 시 bcrypt 해시 (3.1)
- deletion_requested_at: 회원 탈퇴 접수 시각, 유예기간 30일 (3.5)
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String)  # google | kakao | naver | None(자체 로그인)
    provider_id: Mapped[str | None] = mapped_column(String)
    password_hash: Mapped[str | None] = mapped_column(String)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
