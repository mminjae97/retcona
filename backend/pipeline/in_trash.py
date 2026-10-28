"""A job whose novel went to the trash (design doc 2.6) while it waited or ran.

Each job locks its novel's row before it writes, and checks the novel is still
there (lock_novel). One in the trash — or deleted for good — ends the job
without touching its row: failed as gone, the row would stay failed after a
restore. Left as it is, with no job left for it, the row reads as abandoned
once the novel is back (api/episodes.py): a run or revalidation to start
again, a pick back to pending.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.novel import Novel


class NovelInTrash(Exception):
    pass


def lock_novel(db: Session, novel_id: uuid.UUID) -> None:
    """Locks the novel's row for the rest of db's transaction; NovelInTrash if
    it's in the trash or gone."""
    if db.scalar(select(Novel.id).where(Novel.id == novel_id, Novel.deleted_at.is_(None)).with_for_update()) is None:
        raise NovelInTrash(novel_id)
