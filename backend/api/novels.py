"""Novel (작품) management endpoints (design doc 2.6).

Novels are the top level (there are no accounts); every other entity table is
scoped to a novel_id (4.1). Deletion here is a soft delete (deleted_at, the trash):
the trash lists those and restores them, for TRASH_KEPT; then the
empty_trash job deletes them for good (pipeline/empty_trash.py).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import require_novel
from models.db import get_db
from models.novel import TRASH_KEPT, Novel

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


class TrashedNovel(BaseModel):
    id: uuid.UUID
    title: str
    deleted_at: datetime
    # When it's deleted for good: the first pass of the empty_trash job after
    # this (one runs at startup and daily), so possibly a little later.
    purge_after: datetime


@router.get("", response_model=list[NovelPublic])
def list_novels(db: Session = Depends(get_db)) -> list[Novel]:
    return list(
        db.scalars(
            select(Novel).where(Novel.deleted_at.is_(None)).order_by(Novel.created_at.desc())
        )
    )


# Before /{novel_id}, which would otherwise take "trash" for an id.
@router.get("/trash", response_model=list[TrashedNovel])
def list_trash(db: Session = Depends(get_db)) -> list[TrashedNovel]:
    novels = db.scalars(select(Novel).where(Novel.deleted_at.is_not(None)).order_by(Novel.deleted_at.desc()))
    return [
        TrashedNovel(
            id=novel.id,
            title=novel.title,
            deleted_at=novel.deleted_at,
            purge_after=novel.deleted_at + TRASH_KEPT,
        )
        for novel in novels
    ]


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


@router.post("/{novel_id}/restore", response_model=NovelPublic)
def restore_novel(novel_id: uuid.UUID, db: Session = Depends(get_db)) -> Novel:
    # Locked as empty_trash locks it: whichever gets there first wins, and a
    # novel deleted for good meanwhile is a 404. One past its 30 days that
    # hasn't been deleted yet (the app was closed) can still come back.
    novel = db.scalar(
        select(Novel).where(Novel.id == novel_id, Novel.deleted_at.is_not(None)).with_for_update()
    )
    if novel is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Novel not in the trash")
    novel.deleted_at = None
    db.commit()
    db.refresh(novel)
    return novel
