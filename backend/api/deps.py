"""Shared FastAPI route helpers.

Kept separate from any single router module so novels.py, episodes.py, and
future per-novel-scoped routers can all resolve "does this user own this
novel" the same way instead of drifting apart with copy-pasted checks.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from models.novel import Novel
from models.user import User


def get_owned_novel(db: Session, novel_id: uuid.UUID, user: User, *, for_update: bool = False) -> Novel:
    query = select(Novel).where(Novel.id == novel_id, Novel.user_id == user.id, Novel.deleted_at.is_(None))
    if for_update:
        # Locks the row for the rest of the transaction, re-checking deleted_at
        # under the lock rather than trusting a separate unlocked read — so a
        # concurrent soft-delete can't race past this check (10.1).
        query = query.with_for_update()
    novel = db.scalar(query)
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    return novel
