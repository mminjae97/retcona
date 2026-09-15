"""Episode (화) endpoints — manuscript editor autosave/save (design doc 2.2).

Saving (PATCH) never triggers the AI pipeline — that's a separate "run
validation" step (8.2, not yet wired up here since QueueClient isn't
implemented). Editing a `submitted` episode's content flips it back to
`draft` (2.2), leaving existing validation results in place.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from api.deps import get_owned_novel as _get_owned_novel
from auth.dependencies import get_current_user
from models.db import get_db
from models.episode import Episode
from models.user import User

router = APIRouter()


class EpisodeCreate(BaseModel):
    content: str = ""


class EpisodeUpdate(BaseModel):
    content: str


class EpisodeSummary(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    episode_index: int
    status: str
    updated_at: datetime


class EpisodePublic(EpisodeSummary):
    content: str


def _get_episode(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, user: User) -> Episode:
    _get_owned_novel(db, novel_id, user)
    episode = db.scalar(select(Episode).where(Episode.id == episode_id, Episode.novel_id == novel_id))
    if episode is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Episode not found")
    return episode


@router.get("/{novel_id}/episodes", response_model=list[EpisodeSummary])
def list_episodes(
    novel_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Episode]:
    _get_owned_novel(db, novel_id, user)
    return list(
        db.scalars(
            select(Episode).where(Episode.novel_id == novel_id).order_by(Episode.episode_index.desc())
        )
    )


@router.post(
    "/{novel_id}/episodes", response_model=EpisodePublic, status_code=status.HTTP_201_CREATED
)
def create_episode(
    novel_id: uuid.UUID,
    body: EpisodeCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Episode:
    # Locks the novel row for the rest of this transaction so two concurrent
    # creates (double-click, two tabs) can't both read the same MAX(episode_index)
    # and insert duplicate indexes — the second request blocks here until the
    # first commits, by which point the MAX below reflects its new episode.
    # Relies on the default READ COMMITTED isolation level (models/db.py) to see
    # that committed episode once unblocked; a higher isolation level would need
    # a fresh transaction/snapshot here instead.
    _get_owned_novel(db, novel_id, user, for_update=True)
    next_index = db.scalar(
        select(func.coalesce(func.max(Episode.episode_index), 0)).where(Episode.novel_id == novel_id)
    ) + 1
    episode = Episode(novel_id=novel_id, episode_index=next_index, content=body.content)
    db.add(episode)
    db.commit()
    db.refresh(episode)
    return episode


@router.get("/{novel_id}/episodes/{episode_id}", response_model=EpisodePublic)
def get_episode(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Episode:
    return _get_episode(db, novel_id, episode_id, user)


@router.patch("/{novel_id}/episodes/{episode_id}", response_model=EpisodePublic)
def save_episode(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    body: EpisodeUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Episode:
    episode = _get_episode(db, novel_id, episode_id, user)
    # Only touch the row (and flip a submitted episode back to draft) when the
    # content actually changed — otherwise re-saving unmodified content would
    # needlessly invalidate validation results and bump updated_at.
    if body.content != episode.content:
        episode.content = body.content
        if episode.status == "submitted":
            episode.status = "draft"
    db.commit()
    db.refresh(episode)
    return episode
