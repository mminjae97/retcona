"""users table (design doc 4.1, 4.3).

- nickname: pen name (3.6) — 2-20 characters, duplicates allowed
- provider/provider_id: social login identity (3.1)
- password_hash: bcrypt hash for direct login (3.1)
- deletion_requested_at: when account deletion was requested; 30-day grace period (3.5)
- token_version: embedded in every token as the `ver` claim; a token is only
  accepted while it matches. Bumped when deletion is requested and never reset
  (a re-login that cancels the deletion keeps the new value), so tokens from
  before the request stay dead for good.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


# Grace period between a deletion request and permanent deletion (3.5).
DELETION_GRACE_PERIOD = timedelta(days=30)


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    nickname: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str | None] = mapped_column(String)  # google | kakao | naver | None (direct login)
    provider_id: Mapped[str | None] = mapped_column(String)
    password_hash: Mapped[str | None] = mapped_column(String)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    @property
    def has_password(self) -> bool:
        # False for social-login accounts, which re-authenticate with their provider instead (3.5).
        return self.password_hash is not None
