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
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Engine, Integer, String, inspect
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.exc import NoSuchTableError
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
    return (now or datetime.now(UTC)) - DELETION_GRACE_PERIOD


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


def check_nickname_column_length(engine: Engine) -> None:
    """Fails loudly at startup if the *actual* users.nickname column (reflected
    from the live database) is narrower than NICKNAME_RULES["maxLength"].

    Comparing against User.nickname's declared SQLAlchemy type wouldn't catch
    anything — that type is derived from the same NICKNAME_RULES value above,
    so it always trivially matches. Only a migration changes the real column;
    if shared/nickname-rules.json's maxLength is raised without a paired
    migration (ALTER COLUMN), this is what stands between that and a 500 on
    the first nickname past the old, still-actual length.
    """
    try:
        columns = {c["name"]: c for c in inspect(engine).get_columns("users")}
        nickname_column = columns["nickname"]
    except (NoSuchTableError, KeyError) as exc:
        # Usually a fresh database that migrations haven't been run against
        # (the app never creates tables itself), but possibly DATABASE_URL
        # pointing at the wrong database — say so plainly rather than surface
        # a raw KeyError/NoSuchTableError that looks like a bug in this check.
        raise RuntimeError(
            "Could not find users.nickname to check its length — has `alembic upgrade head` "
            "been run, and does DATABASE_URL point at the right database?"
        ) from exc
    # getattr, not a direct .length: reflection returns a generic TypeEngine,
    # and while this column is a VARCHAR today (so it does carry .length),
    # nothing statically guarantees that stays true.
    # None means unbounded (TEXT, or VARCHAR with no length). Only a column
    # narrower than maxLength breaks anything; a wider one just holds names
    # that can no longer be that long, so it isn't worth refusing to start.
    actual_length = getattr(nickname_column["type"], "length", None)
    expected_length = NICKNAME_RULES["maxLength"]
    if actual_length is not None and actual_length < expected_length:
        raise RuntimeError(
            f"users.nickname is VARCHAR({actual_length}) in the database, narrower than "
            f"shared/nickname-rules.json's maxLength of {expected_length}. "
            "Write a migration to ALTER the column (or fix the JSON) before starting."
        )
