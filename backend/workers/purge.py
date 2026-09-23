"""Account purge job (design doc 3.5).

Permanently deletes accounts whose deletion request is older than the grace
period, together with everything they own: every novel and, through the
novel_id on every other table (4.1), all of its characters, locations,
episodes, claims, flags, events and so on. The multi-tenant layout is what
makes the scope a single path: user -> novels -> novel_id.

It runs on a schedule by itself: the API server starts a background loop
(api/main.py) that does one pass shortly after startup and then one every
day at midnight (PURGE_TIMEZONE, Asia/Seoul unless set), retrying a failed
pass after an hour (PASS_RETRY_SECONDS), so a plain deployment needs nothing
extra. It can also be run on its own — once from cron or Cloud Scheduler, or
as a long-lived worker that does the same daily pass:

    python -m workers.purge                      # one pass now
    python -m workers.purge --loop               # one pass now, then one every midnight

Either way it first runs the API server's startup check
(models.db.check_database, without the nickname column part) and exits
non-zero on a schema mismatch. With
--loop, a database that can't be reached yet is retried every minute for up
to 10 minutes (CHECK_RETRY_SECONDS, CHECK_MAX_WAIT_SECONDS) before giving up
— so run it under a restart policy — and a failed pass is retried after an
hour, like the API server's loop.

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
from datetime import UTC, datetime, time, timedelta
from time import monotonic
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from models.base import Base
from models.db import SessionLocal, check_database
from models.novel import Novel
from models.user import User, deletion_grace_cutoff

# By name, not __name__: run as `python -m workers.purge`, __name__ is
# "__main__", which would fall outside the "workers" logger that
# infra/app_logging.py sets up.
logger = logging.getLogger("workers.purge")

# The purge runs once a day at midnight in this time zone (an IANA name).
PURGE_TIMEZONE_ENV = "PURGE_TIMEZONE"
DEFAULT_PURGE_TIMEZONE = "Asia/Seoul"

# A failed pass (one that couldn't reach the database, or lost it partway) is
# retried after this long rather than at the next midnight, by both the API
# server's loop (api/main.py) and the standalone --loop worker. Accounts that
# failed on their own wait for the next midnight (see purge_pass).
PASS_RETRY_SECONDS = 3600.0

# The standalone --loop worker's startup check. While the database can't be
# reached (still coming up: a compose start, a Cloud SQL restart), it's
# retried every CHECK_RETRY_SECONDS, but only for CHECK_MAX_WAIT_SECONDS: a
# connection error can't be told apart from a permanent one (a wrong password,
# a missing database or host — psycopg gives no SQLSTATE at connect time, and a
# starting server also answers FATAL), so past that the worker exits non-zero
# and the misconfiguration shows up as a failing process instead of a
# healthy-looking one that never purges. So run the --loop worker under a
# restart policy (compose `restart: unless-stopped`, a Kubernetes Deployment,
# systemd Restart=on-failure): a database that takes longer than this to come
# up then just costs a restart, instead of stopping the purge for good.
CHECK_RETRY_SECONDS = 60.0
CHECK_MAX_WAIT_SECONDS = 600.0


def seconds_until_next_midnight(now: datetime | None = None) -> float:
    """Seconds from `now` to the next midnight in the purge time zone.

    Always the *next* one: at exactly midnight it is a full day away, so a pass
    that finishes early can't run twice in the same minute."""
    tz = ZoneInfo(os.environ.get(PURGE_TIMEZONE_ENV) or DEFAULT_PURGE_TIMEZONE)
    local = (now or datetime.now(UTC)).astimezone(tz)
    next_midnight = datetime.combine(local.date() + timedelta(days=1), time.min, tzinfo=tz)
    # Subtract in UTC: aware datetimes sharing a tzinfo subtract as wall-clock
    # time, which is an hour off across a daylight-saving change.
    return (next_midnight.astimezone(UTC) - local.astimezone(UTC)).total_seconds()


def delay_after_pass(succeeded: bool) -> float:
    """Seconds until the next pass: the next midnight, or PASS_RETRY_SECONDS
    after a failed one. Shared by the API server's loop and the standalone
    worker, which differ only in how they wait (asyncio vs a thread)."""
    return seconds_until_next_midnight() if succeeded else PASS_RETRY_SECONDS


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
    # than users and novels carries novel_id (NovelScopedMixin). Skipped
    # outright for an account with no novels, sparing it ~16 no-op DELETEs.
    if novel_ids:
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
        except OperationalError:
            # The database itself (a restart, a dropped connection), not this
            # account: every remaining one would fail the same way, each after
            # its own connect timeout and with its own traceback. So the pass
            # stops here, and the caller treats it as one failed pass (retried
            # after PASS_RETRY_SECONDS by the loops). Also covers the rarer
            # per-statement OperationalErrors, e.g. a deadlock — fine to retry.
            raise
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


def _log_result(result: PurgeResult, *, log_nothing: bool) -> None:
    # One place for how a pass is reported, so every entry point reports the
    # same outcome at the same level: failed accounts (each already logged
    # with its traceback) as a WARNING, so alerting on WARNING catches them
    # whichever way the purge runs.
    if result.failed:
        logger.warning(
            "Purged %d account(s); %d failed and stay pending until the next pass", result.purged, result.failed
        )
    elif result.purged or log_nothing:
        logger.info("Purged %d account(s) past the deletion grace period", result.purged)


def purge_pass() -> bool:
    """One scheduled pass, logged; False if the pass itself failed — the
    database unreachable, or lost partway (purge_expired_accounts stops at a
    connection error instead of failing each remaining account on its own) —
    which the loops retry after PASS_RETRY_SECONDS. Accounts that failed on
    their own are an account-specific problem that retrying within the hour
    wouldn't fix: they're reported and left for the next midnight's pass, so
    one account that always fails doesn't put every instance on hourly passes
    for good. Nothing is logged for a pass with nothing to purge (each
    instance runs one every night)."""
    try:
        result = purge_once()
    except Exception:
        logger.exception("Purge pass failed; retrying in %d s", PASS_RETRY_SECONDS)
        return False
    _log_result(result, log_nothing=False)
    return True


def run(loop: bool = False) -> None:
    # The same startup check as the API server's (not in purge_once: the API
    # server's own passes already ran it at its startup), so a database behind
    # this code's migrations fails here plainly instead of partway through a
    # pass — minus the nickname column check, which has nothing to do with
    # purging and shouldn't stop it. Logging needs no setup here:
    # workers/__init__.py did it.
    if not loop:
        check_database(nickname_column=False)
        # A failure should surface as a non-zero exit (cron, Cloud Scheduler), and Ctrl-C keeps its default meaning.
        result = purge_once()
        _log_result(result, log_nothing=True)  # a one-off run always says what it did
        if result.failed:
            sys.exit(1)
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # finish the current pass, then exit (10.4.4)
    # A bad PURGE_TIMEZONE fails here, not after the first pass when the first
    # midnight is worked out — as the API server's startup does (api/main.py).
    seconds_until_next_midnight()
    started = monotonic()
    checked = False
    delay = 0.0
    while not stop.wait(delay):
        if not checked:
            try:
                check_database(nickname_column=False)
            except OperationalError as exc:
                # A schema mismatch (RuntimeError) isn't caught: that needs a
                # migration, not a retry.
                if monotonic() - started > CHECK_MAX_WAIT_SECONDS:
                    raise
                logger.warning(
                    "Could not reach the database for the startup check (%s); retrying in %d s",
                    exc.orig or exc,
                    CHECK_RETRY_SECONDS,
                )
                delay = CHECK_RETRY_SECONDS
                continue
            checked = True
        delay = delay_after_pass(purge_pass())


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Permanently delete accounts past their deletion grace period.")
    parser.add_argument(
        "--loop",
        action="store_true",
        help=(
            "keep running: a pass now, then one every midnight (a failed pass is retried after an hour; "
            "an unreachable database at startup is retried for up to 10 minutes)"
        ),
    )
    args = parser.parse_args()
    run(loop=args.loop)
