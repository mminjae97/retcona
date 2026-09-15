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


def get_owned_novel(db: Session, novel_id: uuid.UUID, user: User) -> Novel:
    novel = db.scalar(
        select(Novel).where(Novel.id == novel_id, Novel.user_id == user.id, Novel.deleted_at.is_(None))
    )
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not found")
    return novel
