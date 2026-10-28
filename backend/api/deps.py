"""Shared FastAPI route helpers.

Kept separate from any single router module so novels.py, episodes.py, and
future per-novel-scoped routers can all resolve "does this novel exist (and
isn't in the trash)" the same way instead of drifting apart with copy-pasted
checks.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.novel import Novel


def require_novel(
    db: Session, novel_id: uuid.UUID, *, for_update: bool = False, in_trash: bool = False
) -> Novel:
    # in_trash: the novel must be in the trash instead (restoring it).
    in_place = Novel.deleted_at.is_not(None) if in_trash else Novel.deleted_at.is_(None)
    query = select(Novel).where(Novel.id == novel_id, in_place)
    if for_update:
        # Locks the row for the rest of the transaction, re-checking deleted_at
        # under the lock rather than trusting a separate unlocked read — so a
        # concurrent soft-delete can't race past this check (10.1).
        query = query.with_for_update()
    novel = db.scalar(query)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not in the trash" if in_trash else "Novel not found")
    return novel
