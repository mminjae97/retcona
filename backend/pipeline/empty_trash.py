"""The "empty the trash" job (design doc 2.6, 10.2), as the job runner runs it.

A deleted novel stays in the trash (novels.deleted_at) for TRASH_KEPT, and can
be restored meanwhile (api/novels.py). After that this job deletes it for good:
its row, and with it everything under it — every foreign key cascades
(models/base.py), so deleting the novel deletes its episodes, and theirs
their claims, and so on. It's enqueued while the app runs: right after it
starts, then every hour (api/main.py, request_empty_trash).

Each novel goes in its own transaction, with the trash re-checked in it: a
restore that got there first wins, and one novel that fails doesn't hold up
the others (the next pass tries it again). Jobs still queued for a novel
deleted here find their rows gone and do nothing.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from infra.queue_client import get_queue_client, job_type_pending
from models.db import SessionLocal
from models.novel import TRASH_KEPT, Novel

logger = logging.getLogger(__name__)

JOB_TYPE = "empty_trash"


def request_empty_trash() -> None:
    """Queue a pass, unless one is already queued or running (the runner busy
    for a while, or a second backend process on the database): that one does
    the same."""
    with SessionLocal() as db:
        if db.scalar(select(job_type_pending(JOB_TYPE))):
            return
        get_queue_client().enqueue(db, JOB_TYPE, None, {})
        db.commit()


def empty_trash() -> None:
    cutoff = datetime.now(UTC) - TRASH_KEPT
    with SessionLocal() as db:
        novel_ids = list(db.scalars(select(Novel.id).where(Novel.deleted_at <= cutoff)))
    purged = failed = 0
    for novel_id in novel_ids:
        try:
            purged += _purge(novel_id, cutoff)
        except Exception:
            failed += 1
            logger.exception("Could not permanently delete novel %s; the next pass tries again", novel_id)
    if novel_ids:
        logger.info("Emptied the trash: %d novel(s) deleted for good, %d failed", purged, failed)


def _purge(novel_id: uuid.UUID, cutoff: datetime) -> bool:
    with SessionLocal() as db:
        # Re-checked in this transaction: restored since it was listed, it stays.
        deleted = db.execute(
            delete(Novel).where(Novel.id == novel_id, Novel.deleted_at <= cutoff).returning(Novel.id)
        ).one_or_none()
        db.commit()
        return deleted is not None
