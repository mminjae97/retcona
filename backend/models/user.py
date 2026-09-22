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
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin
from models.nickname_rules import NICKNAME_RULES


# Grace period between a deletion request and permanent deletion (3.5).
DELETION_GRACE_PERIOD = timedelta(days=30)


def deletion_grace_cutoff(now: datetime | None = None) -> datetime:
    """A `deletion_requested_at` at or before this instant is past its grace
    period.

    The one place this cutoff is computed: auth/router.py's login compares a
    single user's `deletion_requested_at` against it to decide whether a
    pending deletion can still be cancelled (410 once past), and
    workers/purge.py compares every row's against it in one query to pick
    purge candidates. Kept as one function so the two can't drift apart — a
    purge run and a login disagreeing on this would either purge an account a
    login just un-scheduled, or accept a login for an account purge is about
    to remove.
    """
    return (now or datetime.now(timezone.utc)) - DELETION_GRACE_PERIOD


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    # Length follows shared/nickname-rules.json (models/nickname_rules.py), but
    # only at the Python/ORM level: the actual column was created at
    # VARCHAR(20) by db/migrations/versions/961f54d79f2a_initial_schema.py,
    # a historical migration that isn't edited retroactively. Raising
    # maxLength above 20 needs a new migration (ALTER COLUMN) alongside it, or
    # validation will accept a nickname the database then rejects.
    nickname: Mapped[str] = mapped_column(String(NICKNAME_RULES["maxLength"]), nullable=False)
    provider: Mapped[str | None] = mapped_column(String)  # google | kakao | naver | None (direct login)
    provider_id: Mapped[str | None] = mapped_column(String)
    password_hash: Mapped[str | None] = mapped_column(String)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    @property
    def has_password(self) -> bool:
        # False for social-login accounts, which re-authenticate with their provider instead (3.5).
        return self.password_hash is not None
