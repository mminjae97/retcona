"""Novel (작품) management endpoints (design doc 2.6).

Novels are the top level (there are no accounts); every other entity table is
scoped to a novel_id (4.1). Deletion here is a soft delete (deleted_at, the trash); the
design doc's 30-day permanent delete (2.6) comes with the local job queue.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import require_novel
from models.db import get_db
from models.novel import Novel

router = APIRouter()


class _TitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title must not be blank")
        return value


# Creation and rename each get their own class (rather than one reused
# directly, or aliased — a plain `NovelRename = NovelCreate` rebinding would
# still be the identical class) so a future creation-only field on
# NovelCreate can't silently become required on rename too.
class NovelCreate(_TitleInput):
    pass


class NovelRename(_TitleInput):
    pass


class NovelPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    title: str
    created_at: datetime


@router.get("", response_model=list[NovelPublic])
def list_novels(db: Session = Depends(get_db)) -> list[Novel]:
    return list(
        db.scalars(
            select(Novel).where(Novel.deleted_at.is_(None)).order_by(Novel.created_at.desc())
        )
    )


@router.get("/{novel_id}", response_model=NovelPublic)
def get_novel(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> Novel:
    return require_novel(db, novel_id)


@router.post("", response_model=NovelPublic, status_code=status.HTTP_201_CREATED)
def create_novel(
    body: NovelCreate, db: Session = Depends(get_db)
) -> Novel:
    novel = Novel(title=body.title)
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


@router.patch("/{novel_id}", response_model=NovelPublic)
def rename_novel(
    novel_id: uuid.UUID,
    body: NovelRename,
    db: Session = Depends(get_db),
) -> Novel:
    # Locked for the same reason as episodes.py:create_episode — without it, a
    # concurrent delete_novel can commit its soft-delete between this read and
    # this function's own commit, leaving a "deleted" novel with an updated
    # title (10.1).
    novel = require_novel(db, novel_id, for_update=True)
    novel.title = body.title
    db.commit()
    db.refresh(novel)
    return novel


@router.delete("/{novel_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_novel(
    novel_id: uuid.UUID,
    db: Session = Depends(get_db),
) -> None:
    # Locked for the same reason as rename_novel/create_episode/save_episode
    # — without it, this read isn't actually serialized against theirs (an
    # unlocked SELECT here doesn't block on their FOR UPDATE, and doesn't
    # block them either), so a concurrent rename/save could still commit
    # its change after this soft-delete reads deleted_at as still null,
    # landing on top of it — exactly the outcome those locks are meant to
    # prevent.
    novel = require_novel(db, novel_id, for_update=True)
    novel.deleted_at = datetime.now(timezone.utc)
    db.commit()
