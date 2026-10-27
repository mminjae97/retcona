"""The "empty the trash" job (design doc 2.6, 10.2), as the job runner runs it.

A deleted novel stays in the trash (novels.deleted_at) for TRASH_KEPT, and can
be restored meanwhile (api/novels.py). After that this job deletes it for good,
with everything under its novel_id — every other table carries one
(NovelScopedMixin, 4.1), so that's the whole scope. It's enqueued while the app
runs: right after it starts, then once a day (api/main.py, request_empty_trash).

Each novel goes in its own transaction, under its row lock with the trash
re-checked: a restore that got there first wins, and one novel that fails
doesn't hold up the others (the next pass tries it again). Jobs still queued
for a novel deleted here find their rows gone and do nothing.
"""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select

from infra.queue_client import get_queue_client
from models.base import Base
from models.db import SessionLocal
from models.novel import TRASH_KEPT, Novel

logger = logging.getLogger(__name__)

JOB_TYPE = "empty_trash"


def request_empty_trash() -> None:
    """Queue a pass. Not checked against one already queued: a second pass
    finds nothing left to do."""
    with SessionLocal() as db:
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
        # Re-checked under the lock: restored since it was listed, it stays.
        novel = db.scalar(
            select(Novel.id).where(Novel.id == novel_id, Novel.deleted_at <= cutoff).with_for_update()
        )
        if novel is None:
            return False
        # sorted_tables lists parents before children, so walking it backwards
        # deletes children first and never trips a foreign key.
        for table in reversed(Base.metadata.sorted_tables):
            if "novel_id" in table.c:
                db.execute(delete(table).where(table.c.novel_id == novel_id))
        db.execute(delete(Novel).where(Novel.id == novel_id))
        db.commit()
        return True
