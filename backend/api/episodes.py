"""Episode (화) endpoints — manuscript editor autosave/save, and "run validation" (design doc 2.2).

Saving (PATCH) never triggers the AI pipeline — that's the separate "run
validation" step (POST .../validations), which records a run and hands it to
the CPU worker through the job queue (10.2); the editor then polls the run.
What the latest run found contradicting the settings is listed by GET .../flags.
Editing a `submitted` episode's content flips it back to `draft` (2.2),
leaving existing validation results in place.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, load_only

from api.deps import get_owned_novel as _get_owned_novel
from auth.dependencies import get_current_user
from infra.queue_client import get_queue_client
from models.claim import Claim, ContradictionFlag
from models.db import get_db
from models.episode import Episode
from models.user import User
from models.validation_run import ValidationRun

logger = logging.getLogger(__name__)

router = APIRouter()

# A run still queued or running this long after it was requested is taken to
# be lost (no worker running, or one that died mid-job — the local Redis queue
# doesn't redeliver) and is failed as "abandoned", so the author can run
# validation again instead of waiting on it forever. Well past how long one
# extraction takes.
RUN_ABANDON_AFTER = timedelta(minutes=15)
_ACTIVE_STATUSES = ("queued", "running")


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


def _get_episode(
    db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, user: User, *, for_update: bool = False
) -> Episode:
    _get_owned_novel(db, novel_id, user, for_update=for_update)
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
            select(Episode)
            # This list view only needs the summary fields — defers the Text
            # content and 1024-dim embedding columns so listing a novel with
            # many/long episodes doesn't pull its whole manuscript text over
            # the wire just to discard it during response serialization.
            .options(load_only(Episode.id, Episode.episode_index, Episode.status, Episode.updated_at))
            .where(Episode.novel_id == novel_id)
            .order_by(Episode.episode_index.asc())
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
    # Locked for the same reason as create_episode/rename_novel: without it, a
    # concurrent soft-delete of the novel could commit between this read and
    # this function's own commit, letting a save land on a "deleted" novel.
    episode = _get_episode(db, novel_id, episode_id, user, for_update=True)
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


# ---------------------------------------------------------------- validation runs


class ValidationRunPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    episode_id: uuid.UUID
    status: str  # queued | running | succeeded | failed
    # failed only: abandoned | queue_unavailable | episode_missing |
    # empty_manuscript | llm_failed | bad_llm_response | inference_failed | internal
    error: str | None
    # succeeded only: {claims, dropped_claims, new_characters, new_locations, flags}
    summary: dict
    # The episode's updated_at as of the content this run validated; a later
    # one means the manuscript changed since (2.2's "out of date" banner).
    content_updated_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _latest_run(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID) -> ValidationRun | None:
    return db.scalar(
        select(ValidationRun)
        .where(ValidationRun.novel_id == novel_id, ValidationRun.episode_id == episode_id)
        .order_by(ValidationRun.created_at.desc(), ValidationRun.id.desc())
        .limit(1)
    )


def _abandon_if_stale(db: Session, run: ValidationRun) -> None:
    """Fails a run that has been queued or running too long; the caller commits."""
    if run.status not in _ACTIVE_STATUSES or datetime.now(UTC) - run.created_at < RUN_ABANDON_AFTER:
        return
    # Conditional, so a worker finishing it at this moment wins: its
    # succeeded/failed stays, and a worker still going discards its results
    # (pipeline/validate_episode.py).
    db.execute(
        update(ValidationRun)
        .where(ValidationRun.id == run.id, ValidationRun.status.in_(_ACTIVE_STATUSES))
        .values(status="failed", error="abandoned", finished_at=func.now())
    )
    db.refresh(run)


@router.post(
    "/{novel_id}/episodes/{episode_id}/validations",
    response_model=ValidationRunPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
def request_validation(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ValidationRun:
    """Validates the episode's saved content (the editor saves first). While
    a run for the episode is queued or running, returns that one instead of
    starting another — a double click, or a second tab, doesn't validate twice.
    """
    # The novel's row lock serializes this check-then-create per novel.
    episode = _get_episode(db, novel_id, episode_id, user, for_update=True)
    if not episode.content.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The manuscript is empty")
    latest = _latest_run(db, novel_id, episode_id)
    if latest is not None:
        _abandon_if_stale(db, latest)
        if latest.status in _ACTIVE_STATUSES:
            return latest

    run = ValidationRun(novel_id=novel_id, episode_id=episode_id, status="queued")
    db.add(run)
    # Committed (with an abandoned run's new status) before it's enqueued, so
    # the worker can't pick the job up before the run it names exists.
    db.commit()
    db.refresh(run)
    try:
        get_queue_client().enqueue(
            {"job_id": str(run.id), "type": "validate_episode", "novel_id": str(novel_id), "episode_id": str(episode_id)}
        )
    except Exception:
        logger.exception("Could not enqueue validation run %s", run.id)
        run.status = "failed"
        run.error = "queue_unavailable"
        run.finished_at = func.now()
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Validation is unavailable right now")
    return run


@router.get(
    "/{novel_id}/episodes/{episode_id}/validations/latest",
    response_model=ValidationRunPublic,
    responses={204: {"description": "The episode has never been validated"}},
)
def get_latest_validation(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ValidationRun | Response:
    _get_episode(db, novel_id, episode_id, user)
    run = _latest_run(db, novel_id, episode_id)
    if run is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    _abandon_if_stale(db, run)
    db.commit()
    return run


# ---------------------------------------------------------------- contradiction flags


class FlagPublic(BaseModel):
    id: uuid.UUID
    error_type: str  # appearance | location (behavior, spacetime: later stages)
    attribute: str | None  # the setting-card key, e.g. eye_color / features
    confidence: float
    status: str  # open | resolved_by_revalidation | accepted | dismissed
    evidence_text: str  # the manuscript sentence
    reference_text: str | None  # the setting's value it contradicts
    subject_kind: str | None  # character | location
    subject_id: uuid.UUID | None  # None once the card is deleted
    subject_name: str | None
    claim_text: str


@router.get("/{novel_id}/episodes/{episode_id}/flags", response_model=list[FlagPublic])
def list_flags(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[FlagPublic]:
    """What the episode's latest successful run found contradicting the
    settings, most confident first (2.4, 2.5). A new run replaces them."""
    _get_episode(db, novel_id, episode_id, user)
    rows = db.execute(
        select(ContradictionFlag, Claim)
        .join(Claim, Claim.id == ContradictionFlag.claim_id)
        .where(
            ContradictionFlag.novel_id == novel_id,
            Claim.novel_id == novel_id,
            Claim.episode_id == episode_id,
        )
        .order_by(ContradictionFlag.confidence.desc(), ContradictionFlag.id)
    )
    return [
        FlagPublic(
            id=flag.id,
            error_type=flag.error_type,
            attribute=flag.attribute,
            confidence=flag.confidence,
            status=flag.status,
            evidence_text=flag.evidence_text,
            reference_text=flag.reference_text,
            subject_kind=claim.subject_kind,
            subject_id=claim.subject_id,
            subject_name=claim.subject_name,
            claim_text=claim.text,
        )
        for flag, claim in rows
    ]
