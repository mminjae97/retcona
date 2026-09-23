"""Account purge job (design doc 3.5).

Permanently deletes accounts whose deletion request is older than the grace
period, together with everything they own: every novel and, through the
novel_id on every other table (4.1), all of its characters, locations,
episodes, claims, flags, events and so on. The multi-tenant layout is what
makes the scope a single path: user -> novels -> novel_id.

It runs on a schedule by itself: the API server starts a background loop
(api/main.py) that does one pass shortly after startup and then one every
day at midnight (PURGE_TIMEZONE, Asia/Seoul unless set), retrying a failed
pass after an hour (PASS_RETRY_SECONDS, up to QUICK_RETRIES times a day), so
a plain deployment needs nothing extra. It can also be run on its own — once from cron or Cloud Scheduler, or
as a long-lived worker that does the same daily pass:

    python -m workers.purge                      # one pass now
    python -m workers.purge --loop               # one pass now, then one every midnight

Either way it first runs the API server's startup check
(models.db.check_database, without the nickname column part) and exits
non-zero on a schema mismatch. With
--loop, a database that can't be reached yet is retried every minute for up
to 10 minutes (CHECK_RETRY_SECONDS, CHECK_MAX_WAIT_SECONDS) before giving up
— so run it under a restart policy — and a failed pass is retried like the
API server's loop does.

It is idempotent and safe to run concurrently (several API instances, a
separate worker): each account is purged in its own transaction, under a row
lock that is skipped if someone else (a login cancelling the deletion,
another purge run) holds it.
"""

import argparse
import logging
import os
import random
import signal
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from time import monotonic
from typing import NamedTuple
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, text
from sqlalchemy.exc import DBAPIError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from models.base import Base
from models.db import SessionLocal, check_database
from models.email_verification import EmailVerification
from models.novel import Novel
from models.user import User, deletion_grace_cutoff

# By name, not __name__: run as `python -m workers.purge`, __name__ is
# "__main__", which would fall outside the "workers" logger that
# infra/app_logging.py sets up.
logger = logging.getLogger("workers.purge")

# The purge runs once a day at midnight in this time zone (an IANA name).
PURGE_TIMEZONE_ENV = "PURGE_TIMEZONE"
DEFAULT_PURGE_TIMEZONE = "Asia/Seoul"

# A failed pass (see purge_pass) is retried after PASS_RETRY_SECONDS rather
# than at the next midnight — by both the API server's loop (api/main.py) and
# the standalone --loop worker — up to QUICK_RETRIES times after each
# midnight's pass. A failure that outlasts that (an outage of hours) settles
# back into the midnight schedule, where the next failure gets its own quick
# retries again: at most QUICK_RETRIES extra passes a day per process.
PASS_RETRY_SECONDS = 3600.0
QUICK_RETRIES = 3
# If working out the next midnight itself fails (e.g. time zone data gone at
# runtime), the API server's loop waits this long instead — a day, not
# PASS_RETRY_SECONDS, so a broken schedule doesn't turn into a pass an hour.
SCHEDULE_FAILURE_DELAY_SECONDS = 86400.0

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


class PassSchedule:
    """When the next pass runs, given how the last one went: the next
    midnight after a success; PASS_RETRY_SECONDS after a failure, up to
    QUICK_RETRIES times, then the next midnight — with the count starting
    over, so a later, unrelated failure gets its quick retries too. Shared by
    the API server's loop and the standalone worker, which differ only in how
    they wait (asyncio vs a thread). The next attempt is logged at INFO: the
    failed pass already logged its own ERROR, and one alert per failure is
    enough."""

    def __init__(self) -> None:
        self.quick_retries_used = 0

    def after(self, succeeded: bool) -> float:
        if not succeeded and self.quick_retries_used < QUICK_RETRIES:
            self.quick_retries_used += 1
            logger.info(
                "Retrying the purge pass in %d s (quick retry %d of %d)",
                PASS_RETRY_SECONDS,
                self.quick_retries_used,
                QUICK_RETRIES,
            )
            return PASS_RETRY_SECONDS
        if not succeeded:
            logger.info("Quick retries used up; next purge pass at the next midnight")
        self.quick_retries_used = 0
        return seconds_until_next_midnight()


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


# SQLSTATE classes/codes where the database itself can't take the pass right
# now, whichever account is being purged: 08 connection exception; 57P
# operator intervention (admin/crash shutdown, "cannot connect now" — not
# 57014 query_canceled, which is one statement); 53 insufficient resources
# (disk full, too many connections); 58 system error (I/O); XX internal error
# (corruption); 25006 read-only transaction (a standby after a failover); 42
# undefined table/column, insufficient privilege (a newer migration renamed a
# table this code deletes from); 3D/3F no such database/schema; 28
# authentication. Anything else the server reports is counted against the
# account.
_DATABASE_WIDE_SQLSTATES = ("08", "57P", "53", "58", "XX", "25006", "42", "3D", "3F", "28")
# Timeouts and lock waits: per-account on their own, but this many of the
# same one in a pass (not necessarily in a row: accounts with no novels skip
# the novel-scoped tables and succeed in between) means something shared — a
# migration's lock on a table every DELETE touches, an overloaded server — so
# the pass stops instead of waiting out a timeout for every remaining account.
# The candidate order is shuffled every pass, so a few accounts that always
# time out on their own can't stop it at the same place every time and keep
# the ones after them from ever being purged.
_CONTENTION_SQLSTATES = ("57014", "55P03")
CONTENTION_LIMIT = 3


def _sqlstate(exc: Exception) -> str | None:
    orig = getattr(exc, "orig", None)
    return getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)  # psycopg 3 / psycopg2


def _database_answers(db: Session) -> bool:
    # Asking, rather than guessing from the exception: psycopg raises the same
    # code-less OperationalError for a connection that's gone and for a query
    # it refused to send (more than 65535 parameters — one huge account).
    # Opening a new connection here if the old one is gone waits at most
    # DB_CONNECT_TIMEOUT_SECONDS.
    try:
        db.rollback()
        db.execute(text("SELECT 1"))
        db.rollback()
    except Exception:  # noqa: BLE001 — any failure to answer is the answer
        return False
    return True


def _is_database_wide(exc: Exception, db: Session) -> bool:
    """Whether a failure while purging one account is the database's (stop
    the pass) rather than that account's (count it, go on). Not by exception
    class: psycopg makes per-statement errors — statement_timeout, deadlocks,
    serialization failures — OperationalErrors too."""
    if not isinstance(exc, DBAPIError):
        return False
    if exc.connection_invalidated:
        return True
    sqlstate = _sqlstate(exc)
    if sqlstate is not None:
        return sqlstate.startswith(_DATABASE_WIDE_SQLSTATES)
    if isinstance(exc, (OperationalError, InterfaceError)):
        # No error code from the server: unreachable, the connection lost
        # mid-statement — or a statement the driver refused to send.
        return not _database_answers(db)
    return False


class PurgePassAborted(Exception):
    """A pass stopped partway at a database-wide failure or contention (the
    __cause__ is the error it stopped at). Carries what it had done by then —
    those deletes are committed and can't be undone — so whoever logs the
    failure reports them with it: purged and failed so far, and left_pending
    (the account it stopped at, and every one after it; accounts skipped
    along the way are in none of the three)."""

    def __init__(self, reason: str, purged: int, failed: int, left_pending: int) -> None:
        super().__init__(f"{reason}: {purged} purged, {failed} failed, {left_pending} left pending")
        self.reason = reason
        self.purged = purged
        self.failed = failed
        self.left_pending = left_pending


def purge_expired_accounts(
    db: Session, now: datetime | None = None, should_stop: Callable[[], bool] | None = None
) -> PurgeResult:
    """Purge every account past its grace period; returns how many were
    removed and how many failed. `should_stop` is checked between accounts
    (a shutdown): the pass then ends early, as a normal result — what's left
    is simply still pending for the next one."""
    cutoff = deletion_grace_cutoff(now)
    candidates = list(
        db.scalars(
            select(User.id).where(User.deletion_requested_at.is_not(None), User.deletion_requested_at <= cutoff)
        )
    )
    db.rollback()  # end the read transaction; each purge below is its own
    random.shuffle(candidates)  # see _CONTENTION_SQLSTATES

    purged = failed = 0
    contention: dict[str, int] = {}
    failure_kinds: set[str] = set()
    for index, user_id in enumerate(candidates):
        if should_stop is not None and should_stop():
            # Not a failure — what's left is picked up by the next pass — but
            # said, since the result alone looks like a finished pass.
            logger.info(
                "Purge pass interrupted by shutdown: %d account(s) purged, %d failed, %d left pending",
                purged,
                failed,
                len(candidates) - index,
            )
            break
        try:
            if _purge_user(db, user_id, cutoff):
                purged += 1
        except Exception as exc:
            sqlstate = _sqlstate(exc)
            if _is_database_wide(exc, db):
                raise PurgePassAborted("the database failed", purged, failed, len(candidates) - index) from exc
            if sqlstate in _CONTENTION_SQLSTATES:
                contention[sqlstate] = contention.get(sqlstate, 0) + 1
                if contention[sqlstate] >= CONTENTION_LIMIT:
                    raise PurgePassAborted(
                        f"{CONTENTION_LIMIT} accounts hit SQLSTATE {sqlstate} (contention, not the accounts)",
                        purged,
                        failed,
                        len(candidates) - index,
                    ) from exc
            # One account failing must not stop the rest; it stays pending and is retried next run.
            db.rollback()
            failed += 1
            failure_kinds.add(sqlstate or type(exc).__name__)
            logger.exception("Failed to purge account %s", user_id)
    if failed >= 2 and not purged and len(failure_kinds) == 1:
        # A fact, not a verdict: this is also what a few accounts that always
        # fail on their own look like on a night nothing else expired.
        logger.error("All %d account(s) the purge pass attempted failed the same way (%s)", failed, *failure_kinds)
    return PurgeResult(purged, failed)


# A signup verification row (auth/email_verification.py) that no one finished
# with is deleted this long after its last code was sent. Not sooner: the row
# also carries the address's hourly sending limit.
STALE_VERIFICATION_AGE = timedelta(days=1)


def delete_stale_email_verifications(db: Session, now: datetime | None = None) -> int:
    """Codes requested for signups that were never finished; returns how many rows went."""
    cutoff = (now or datetime.now(UTC)) - STALE_VERIFICATION_AGE
    deleted = db.execute(delete(EmailVerification).where(EmailVerification.sent_at < cutoff)).rowcount
    db.commit()
    return deleted


def purge_once(should_stop: Callable[[], bool] | None = None) -> PurgeResult:
    """One pass in a session of its own: stale signup codes, then accounts."""
    with SessionLocal() as db:
        delete_stale_email_verifications(db)
        return purge_expired_accounts(db, should_stop=should_stop)


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


def _log_aborted(exc: PurgePassAborted) -> None:
    # One record per aborted pass, with the counts and the error's traceback
    # together.
    logger.error(
        "Purge pass stopped partway: %s. %d account(s) purged, %d failed, %d left pending",
        exc.reason,
        exc.purged,
        exc.failed,
        exc.left_pending,
        exc_info=exc.__cause__,
    )


def purge_pass(should_stop: Callable[[], bool] | None = None) -> bool:
    """One scheduled pass, logged; False if the pass failed, for PassSchedule
    to retry sooner than the next midnight: it couldn't run at all, or it
    stopped at a database-wide error or at contention (see
    _is_database_wide, _CONTENTION_SQLSTATES). Accounts that failed on their
    own are an account-specific problem that retrying within the hour
    wouldn't fix: they're reported and left for the next midnight's pass.
    Nothing is logged for a pass with nothing to purge (each instance runs
    one every night)."""
    try:
        result = purge_once(should_stop)
    except PurgePassAborted as exc:
        _log_aborted(exc)
        return False
    except Exception:
        logger.exception("Purge pass failed")
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
        try:
            result = purge_once()
        except PurgePassAborted as exc:
            _log_aborted(exc)
            sys.exit(1)
        _log_result(result, log_nothing=True)  # a one-off run always says what it did
        if result.failed:
            sys.exit(1)
        return
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # finish the current account, then exit (10.4.4)
    # A bad PURGE_TIMEZONE fails here, not after the first pass when the first
    # midnight is worked out — as the API server's startup does (api/main.py).
    seconds_until_next_midnight()
    started = monotonic()
    checked = False
    schedule = PassSchedule()
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
        delay = schedule.after(purge_pass(stop.is_set))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Permanently delete accounts past their deletion grace period.")
    parser.add_argument(
        "--loop",
        action="store_true",
        help=(
            "keep running: a pass now, then one every midnight (a failed pass is retried after an hour, "
            "up to 3 times a day; an unreachable database at startup is retried for up to 10 minutes)"
        ),
    )
    args = parser.parse_args()
    run(loop=args.loop)
