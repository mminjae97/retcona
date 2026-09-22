"""Account purge job (design doc 3.5).

Permanently deletes accounts whose deletion request is older than the grace
period, together with everything they own: every novel and, through the
novel_id on every other table (4.1), all of its characters, locations,
episodes, claims, flags, events and so on. The multi-tenant layout is what
makes the scope a single path: user -> novels -> novel_id.

It runs on a schedule by itself: the API server starts a background loop
(api/main.py) that does one pass shortly after startup and then one every
day at midnight (PURGE_TIMEZONE, Asia/Seoul unless set), so a plain deployment
needs nothing extra. It can also
be run on its own — once from cron or Cloud Scheduler, or as a long-lived
worker that does the same daily pass:

    python -m workers.purge                      # one pass now
    python -m workers.purge --loop               # one pass now, then one every midnight

It is idempotent and safe to run concurrently (several API instances, a
separate worker): each account is purged in its own transaction, under a row
lock that is skipped if someone else (a login cancelling the deletion,
another purge run) holds it.
"""

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import datetime, time, timedelta, timezone
from typing import Iterator, NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from models.base import Base
from models.db import SessionLocal
from models.novel import Novel
from models.user import User, deletion_grace_cutoff

logger = logging.getLogger(__name__)

# The purge runs once a day at midnight in this time zone (an IANA name).
PURGE_TIMEZONE_ENV = "PURGE_TIMEZONE"
DEFAULT_PURGE_TIMEZONE = "Asia/Seoul"


def seconds_until_next_midnight(now: datetime | None = None) -> float:
    """Seconds from `now` to the next midnight in the purge time zone.

    Always the *next* one: at exactly midnight it is a full day away, so a pass
    that finishes early can't run twice in the same minute."""
    tz = ZoneInfo(os.environ.get(PURGE_TIMEZONE_ENV) or DEFAULT_PURGE_TIMEZONE)
    local = (now or datetime.now(timezone.utc)).astimezone(tz)
    next_midnight = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=tz)
    # Subtract in UTC: aware datetimes sharing a tzinfo subtract as wall-clock
    # time, which is an hour off across a daylight-saving change.
    return (next_midnight.astimezone(timezone.utc) - local.astimezone(timezone.utc)).total_seconds()


def purge_schedule(startup_delay: float) -> Iterator[float]:
    """Seconds to wait before each pass: `startup_delay` before the first (a
    pass right after startup catches up on a midnight the process wasn't alive
    for — scaled to zero, restarted, redeployed), then until every following
    midnight. Shared by the API server's loop and the standalone worker."""
    yield startup_delay
    while True:
        yield seconds_until_next_midnight()


class PurgeResult(NamedTuple):
    purged: int
    failed: int  # left pending, retried on the next pass


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

    # Resolved once into a literal list: left as a Select, it would be
    # re-planned and re-executed as a correlated subquery inside every one of
    # the ~16 DELETEs below instead of being read from the row lock already held.
    novel_ids = list(db.scalars(select(Novel.id).where(Novel.user_id == user_id)))
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


def purge_expired_accounts(db: Session, now: datetime | None = None) -> PurgeResult:
    """Purge every account past its grace period; returns how many were removed and how many failed."""
    cutoff = deletion_grace_cutoff(now)
    candidates = list(
        db.scalars(
            select(User.id).where(User.deletion_requested_at.is_not(None), User.deletion_requested_at <= cutoff)
        )
    )
    db.rollback()  # end the read transaction; each purge below is its own

    purged = failed = 0
    for user_id in candidates:
        try:
            if _purge_user(db, user_id, cutoff):
                purged += 1
        except Exception:
            # One account failing must not stop the rest; it stays pending and is retried next run.
            db.rollback()
            failed += 1
            logger.exception("Failed to purge account %s", user_id)
    return PurgeResult(purged, failed)


def purge_once() -> PurgeResult:
    """One pass in a session of its own."""
    with SessionLocal() as db:
        return purge_expired_accounts(db)


def run(loop: bool = False) -> None:
    logging.basicConfig(level=logging.INFO)
    if not loop:
        # A failure should surface as a non-zero exit (cron, Cloud Scheduler), and Ctrl-C keeps its default meaning.
        result = purge_once()
        logger.info("Purged %d account(s), %d failed", *result)
        if result.failed:
            sys.exit(1)
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # finish the current pass, then exit (10.4.4)
    for delay in purge_schedule(startup_delay=0.0):
        if stop.wait(delay):
            break
        try:
            logger.info("Purged %d account(s), %d failed", *purge_once())
        except Exception:
            # e.g. the database is briefly unreachable: a long-lived worker retries at the next midnight.
            logger.exception("Purge pass failed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Permanently delete accounts past their deletion grace period.")
    parser.add_argument("--loop", action="store_true", help="keep running: a pass now, then one every midnight")
    args = parser.parse_args()
    run(loop=args.loop)
