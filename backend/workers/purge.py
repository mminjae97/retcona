"""Account purge job (design doc 3.5).

Permanently deletes accounts whose deletion request is older than the grace
period, together with everything they own: every novel and, through the
novel_id on every other table (4.1), all of its characters, locations,
episodes, claims, flags, events and so on. The multi-tenant layout is what
makes the scope a single path: user -> novels -> novel_id.

Run it periodically (cron / Cloud Scheduler):  python -m workers.purge
It is idempotent and safe to run concurrently: each account is purged in its
own transaction, under a row lock that is skipped if someone else (a login
cancelling the deletion, another purge run) holds it.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.base import Base
from models.db import SessionLocal
from models.novel import Novel
from models.user import DELETION_GRACE_PERIOD, User

logger = logging.getLogger(__name__)


def _purge_user(db: Session, user_id, cutoff: datetime) -> bool:
    # Re-checked under the lock: a login may have cancelled the deletion since
    # the candidate list was read, and that must win.
    user = db.scalar(
        select(User)
        .where(User.id == user_id, User.deletion_requested_at.is_not(None), User.deletion_requested_at <= cutoff)
        .with_for_update(skip_locked=True)
    )
    if user is None:
        db.rollback()
        return False

    novel_ids = select(Novel.id).where(Novel.user_id == user_id)
    # sorted_tables lists parents before children, so walking it backwards
    # deletes children first and never trips a foreign key. Every table other
    # than users and novels carries novel_id (NovelScopedMixin).
    for table in reversed(Base.metadata.sorted_tables):
        if "novel_id" in table.c:
            db.execute(delete(table).where(table.c.novel_id.in_(novel_ids)))
    db.execute(delete(Novel).where(Novel.user_id == user_id))
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    return True


def purge_expired_accounts(db: Session, now: datetime | None = None) -> int:
    """Purge every account past its grace period; returns how many were removed."""
    cutoff = (now or datetime.now(timezone.utc)) - DELETION_GRACE_PERIOD
    candidates = list(
        db.scalars(
            select(User.id).where(User.deletion_requested_at.is_not(None), User.deletion_requested_at <= cutoff)
        )
    )
    db.rollback()  # end the read transaction; each purge below is its own

    purged = 0
    for user_id in candidates:
        try:
            if _purge_user(db, user_id, cutoff):
                purged += 1
        except Exception:
            # One account failing must not stop the rest; it stays pending and is retried next run.
            db.rollback()
            logger.exception("Failed to purge account %s", user_id)
    return purged


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    with SessionLocal() as db:
        purged = purge_expired_accounts(db)
    logger.info("Purged %d account(s)", purged)


if __name__ == "__main__":
    run()
