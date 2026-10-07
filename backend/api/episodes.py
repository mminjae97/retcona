"""Episode (화) endpoints — manuscript editor autosave/save, and "run validation" (design doc 2.2).

Saving (PATCH) never triggers the AI pipeline — that's the separate "run
validation" step (POST .../validations), which records a run and hands it to
the CPU worker through the job queue (10.2); the editor then polls the run.
What the latest run found contradicting the settings is listed by GET .../flags,
and the author acts on each flag with PATCH .../flags/{id} (2.4), or has one
judged again after supplementing its setting, POST .../flags/{id}/revalidate
(7.5) — a job for the CPU worker too.
Claims the extraction couldn't tie to one card wait in GET .../pending-links
for the author to pick one, POST .../pending-links/{id} (7.1.1); the worker
judges the pick as well.
Editing a `submitted` episode's content flips it back to `draft` (2.2),
leaving existing validation results in place.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, load_only

from api.deps import get_owned_novel as _get_owned_novel
from auth.dependencies import get_current_user
from infra.queue_client import get_queue_client
from models.character import SPACETIME_ATTR_KEYS, Character
from models.claim import Claim, ContradictionFlag
from models.db import get_db
from models.episode import Episode
from models.flag_revalidation import FlagRevalidation
from models.location import STATE_ATTR_KEYS, Location
from models.user import User
from models.validation_run import ValidationRun
from pipeline.claim_links import link_key, record_choice
from pipeline.dismissals import dismissal_key, record_dismissal, remove_dismissal
from pipeline.entities import normalize_name
from pipeline.judges import repeats

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


class FlagCounts(BaseModel):
    open: int = 0
    total: int = 0


class ValidationRunPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    episode_id: uuid.UUID
    status: str  # queued | running | succeeded | failed
    # failed only: abandoned | queue_unavailable | episode_missing |
    # empty_manuscript | inference_failed | internal
    error: str | None
    # succeeded only: {claims, dropped_claims, new_characters, new_locations,
    # flags}. flags is how many flags the run found (absent on runs from
    # before contradiction judgment) — a record; flag_counts is the state now.
    summary: dict
    # The episode's flags as they are now (those of its latest successful
    # run, after the author's accepts and dismissals), and how many are still
    # open. Counted for a finished run only: 0/0 while one is queued or running.
    flag_counts: FlagCounts = FlagCounts()
    # The episode's updated_at as of the content this run validated; a later
    # one means the manuscript changed since (2.2's "out of date" banner).
    content_updated_at: datetime | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


def _run_public(db: Session, novel_id: uuid.UUID, run: ValidationRun) -> ValidationRunPublic:
    if run.status in _ACTIVE_STATUSES:
        # The editor polls these and shows only progress; not worth the count.
        return ValidationRunPublic.model_validate(run)
    counts = FlagCounts()
    for flag_status, count in db.execute(
        select(ContradictionFlag.status, func.count())
        .join(Claim, Claim.id == ContradictionFlag.claim_id)
        .where(
            ContradictionFlag.novel_id == novel_id,
            Claim.novel_id == novel_id,
            Claim.episode_id == run.episode_id,
        )
        .group_by(ContradictionFlag.status)
    ):
        counts.total += count
        if flag_status == "open":
            counts.open += count
    return ValidationRunPublic.model_validate(run).model_copy(update={"flag_counts": counts})


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
) -> ValidationRunPublic:
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
            return _run_public(db, novel_id, latest)

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
    return _run_public(db, novel_id, run)


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
) -> ValidationRunPublic | Response:
    _get_episode(db, novel_id, episode_id, user)
    run = _latest_run(db, novel_id, episode_id)
    if run is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    _abandon_if_stale(db, run)
    db.commit()
    return _run_public(db, novel_id, run)


# ---------------------------------------------------------------- contradiction flags


class FlagRevalidationPublic(BaseModel):
    """The flag's latest revalidation (models/flag_revalidation.py)."""

    model_config = {"from_attributes": True}

    status: str  # queued | running | succeeded | failed
    # failed: abandoned | queue_unavailable | superseded | flag_missing |
    # flag_handled | card_missing | setting_changed | inference_failed | internal
    error: str | None
    outcome: str | None  # succeeded: resolved | contradicts
    setting: str | None  # the card's value it was judged against
    created_at: datetime
    finished_at: datetime | None


class FlagPublic(BaseModel):
    id: uuid.UUID
    error_type: str  # appearance | location (behavior, spacetime: later stages)
    attribute: str | None  # the setting-card key, e.g. eye_color / features
    confidence: float | None  # None: to be judged again (the setting changed since)
    status: str  # open | accepted | dismissed | resolved | resolved_by_revalidation (models/claim.py)
    evidence_text: str  # the manuscript sentence
    reference_text: str | None  # the setting's value it contradicts
    subject_kind: str | None  # character | location
    subject_id: uuid.UUID | None  # None once the card is deleted
    subject_name: str | None
    claim_text: str
    # What the manuscript says for the attribute — what "accept" writes to the card
    value: str | None
    revalidation: FlagRevalidationPublic | None = None


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
        .order_by(ContradictionFlag.confidence.desc().nulls_last(), ContradictionFlag.id)
    ).all()
    latest = _latest_revalidations(db, novel_id, [flag.id for flag, _ in rows])
    db.commit()
    return [_flag_public(flag, claim, latest.get(flag.id)) for flag, claim in rows]


def _latest_revalidations(
    db: Session, novel_id: uuid.UUID, flag_ids: list[uuid.UUID]
) -> dict[uuid.UUID, FlagRevalidation]:
    """Each flag's latest revalidation; one still queued or running long past
    when it should have finished is failed as abandoned first (as runs are).
    The caller commits."""
    if not flag_ids:
        return {}
    db.execute(
        update(FlagRevalidation)
        .where(
            FlagRevalidation.novel_id == novel_id,
            FlagRevalidation.flag_id.in_(flag_ids),
            FlagRevalidation.status.in_(_ACTIVE_STATUSES),
            FlagRevalidation.created_at < func.now() - RUN_ABANDON_AFTER,
        )
        .values(status="failed", error="abandoned", finished_at=func.now())
    )
    latest: dict[uuid.UUID, FlagRevalidation] = {}
    for revalidation in db.scalars(
        select(FlagRevalidation)
        .where(FlagRevalidation.novel_id == novel_id, FlagRevalidation.flag_id.in_(flag_ids))
        .order_by(FlagRevalidation.created_at, FlagRevalidation.id)
    ):
        latest[revalidation.flag_id] = revalidation
    return latest


def _flag_public(
    flag: ContradictionFlag, claim: Claim, revalidation: FlagRevalidation | None = None
) -> FlagPublic:
    return FlagPublic(
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
        value=_flag_value(flag, claim),
        revalidation=FlagRevalidationPublic.model_validate(revalidation) if revalidation is not None else None,
    )


def _flag_value(flag: ContradictionFlag, claim: Claim) -> str | None:
    """What the manuscript says for the flagged attribute: shown to the author,
    and what accepting writes to the card."""
    if not flag.attribute or flag.attribute in _HISTORY_ATTR_KEYS:
        return None  # nothing the card could take
    return (claim.attributes or {}).get(flag.attribute)


class FlagAction(BaseModel):
    # accept: the manuscript is right — its value replaces the card's (7.4:
    #   changing an existing setting goes through the author, and this is that)
    # dismiss: a false positive; the flag is closed and the card left as it is
    # reopen: undoes a dismissal
    action: Literal["accept", "dismiss", "reopen"]


# 409 details, as codes the result screen turns into messages.
FLAG_HANDLED = "flag_handled"  # not open (accept/dismiss) or not dismissed (reopen)
FLAG_NO_VALUE = "flag_no_value"  # the claim has no value for the attribute
FLAG_NO_SETTING = "flag_no_setting"  # a state / presence flag: held against the story's history, not a card value
# Attributes a flag can carry that aren't a card's (pipeline/judges.py): what the story says happened before.
_HISTORY_ATTR_KEYS = STATE_ATTR_KEYS + SPACETIME_ATTR_KEYS
FLAG_CARD_MISSING = "flag_card_missing"  # the setting card was deleted
# accept while the episode is being validated: that run judged against the
# card as it was, and would bring the flag back when it finishes
FLAG_RUN_ACTIVE = "flag_run_active"
# accept after the manuscript was edited since the run: the sentence may be gone
FLAG_OUTDATED = "flag_outdated"
# accept after the card's value changed since the run (the settings screen, or
# an accept in another episode): the author hasn't seen what would be replaced
# — also a revalidation that supplements the setting over a value not shown
FLAG_SETTING_CHANGED = "flag_setting_changed"


# Which card attribute a flag's attribute lives in, by subject kind.
_CARD_FIELDS = {"character": (Character, "fixed_attrs"), "location": (Location, "geo_attrs")}


@router.patch("/{novel_id}/episodes/{episode_id}/flags/{flag_id}", response_model=FlagPublic)
def act_on_flag(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    flag_id: uuid.UUID,
    body: FlagAction,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FlagPublic:
    # The novel's row lock: accepting writes a setting card, as the settings
    # screen and validation runs do under the same lock.
    episode = _get_episode(db, novel_id, episode_id, user, for_update=True)
    flag, claim = _get_flag(db, novel_id, episode_id, flag_id)

    if body.action == "reopen":
        if flag.status != "dismissed":
            raise HTTPException(status.HTTP_409_CONFLICT, FLAG_HANDLED)
        flag.status = "open"
        _forget_dismissal(db, novel_id, episode_id, flag, claim)
    elif flag.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_HANDLED)
    elif body.action == "dismiss":
        flag.status = "dismissed"
        # Kept apart from this run's flags, so later runs honor it too.
        key = _dismissal_key_of(flag, claim)
        if key is not None:
            record_dismissal(db, novel_id, episode_id, key)
    else:
        _raise_if_run_active(db, novel_id, episode_id)
        # "submitted": the saved manuscript is what the last successful run
        # validated (a save since made it a draft, 2.2).
        if episode.status != "submitted":
            raise HTTPException(status.HTTP_409_CONFLICT, FLAG_OUTDATED)
        _accept(db, novel_id, flag, claim)
        flag.status = "accepted"
    revalidation = _latest_revalidations(db, novel_id, [flag.id]).get(flag.id)
    db.commit()
    return _flag_public(flag, claim, revalidation)


def _get_flag(
    db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, flag_id: uuid.UUID
) -> tuple[ContradictionFlag, Claim]:
    row = db.execute(
        select(ContradictionFlag, Claim)
        .join(Claim, Claim.id == ContradictionFlag.claim_id)
        .where(
            ContradictionFlag.id == flag_id,
            ContradictionFlag.novel_id == novel_id,
            Claim.novel_id == novel_id,
            Claim.episode_id == episode_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Flag not found")
    return row.tuple()


def _raise_if_run_active(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID) -> None:
    # A run in progress judged against the card as it was, and replaces this
    # run's flags when it finishes.
    latest = _latest_run(db, novel_id, episode_id)
    if latest is not None:
        _abandon_if_stale(db, latest)
        if latest.status in _ACTIVE_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, FLAG_RUN_ACTIVE)


def _card_of(db: Session, novel_id: uuid.UUID, claim: Claim):
    """The setting card the claim is about, and the field its judged attributes are in."""
    fields = _CARD_FIELDS.get(claim.subject_kind or "")
    card = None
    if fields is not None and claim.subject_id is not None:
        model, attrs_field = fields
        card = db.scalar(select(model).where(model.id == claim.subject_id, model.novel_id == novel_id))
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_CARD_MISSING)
    return card, attrs_field


def _dismissal_key_of(flag: ContradictionFlag, claim: Claim):
    return dismissal_key(claim.subject_id, flag.attribute, claim.evidence_text, _flag_value(flag, claim), flag.reference_text)


def _forget_dismissal(
    db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, flag: ContradictionFlag, claim: Claim
) -> None:
    key = _dismissal_key_of(flag, claim)
    if key is not None:
        remove_dismissal(db, novel_id, episode_id, key)


def _accept(db: Session, novel_id: uuid.UUID, flag: ContradictionFlag, claim: Claim) -> None:
    value = _flag_value(flag, claim)
    if not value or claim.subject_kind not in _CARD_FIELDS:
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_NO_VALUE)
    card, attrs_field = _card_of(db, novel_id, claim)
    current = (getattr(card, attrs_field) or {}).get(flag.attribute)
    if normalize_name(str(current or "")) != normalize_name(flag.reference_text or ""):
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_SETTING_CHANGED)
    # Reassigned, not mutated: SQLAlchemy doesn't see changes inside a JSONB value.
    setattr(card, attrs_field, {**(getattr(card, attrs_field) or {}), flag.attribute: value})
    # The author chose this value: it's theirs now, not an episode's to
    # replace or clear on a later run (models/character.py). The card's
    # source stays: its other attributes are still as detected.
    card.attr_sources = {key: record for key, record in (card.attr_sources or {}).items() if key != flag.attribute}

    # The episode's other flags on the same attribute were judged against the
    # old value. One whose value repeats the new setting (the judges' rule,
    # judges.repeats: a run wouldn't flag it now) is resolved, open or
    # dismissed — not "accepted": the author didn't accept it. The rest show the new value for the author to judge, with no
    # confidence (it was about the old value) until the episode is validated
    # again — a dismissed one reopened, since its dismissal was about the old
    # value too (accepting one of them replaces the value again, knowingly).
    siblings = db.execute(
        select(ContradictionFlag, Claim)
        .join(Claim, Claim.id == ContradictionFlag.claim_id)
        .where(
            ContradictionFlag.novel_id == novel_id,
            ContradictionFlag.id != flag.id,
            ContradictionFlag.status.in_(("open", "dismissed")),
            ContradictionFlag.attribute == flag.attribute,
            Claim.novel_id == novel_id,
            Claim.episode_id == claim.episode_id,
            Claim.subject_kind == claim.subject_kind,
            Claim.subject_id == claim.subject_id,
        )
    )
    for sibling, sibling_claim in siblings:
        if sibling.status == "dismissed":
            # About the old value; left in place it would silently dismiss
            # this sentence again if the setting ever went back to that value.
            _forget_dismissal(db, novel_id, claim.episode_id, sibling, sibling_claim)
        sibling_value = _flag_value(sibling, sibling_claim) or ""
        if sibling_value and repeats(sibling_value, value):
            sibling.status = "resolved"
        else:
            sibling.reference_text = value
            sibling.confidence = None
            sibling.status = "open"


# ---------------------------------------------------------------- revalidation (7.5)


class RevalidateRequest(BaseModel):
    # The setting's new value, when the author supplements it here (the card's
    # value for the flag's attribute); None to judge the flag against the card
    # as it is now (changed on the settings screen).
    setting: str | None = Field(None, max_length=500)

    @field_validator("setting")
    @classmethod
    def _not_blank(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Must not be blank")
        return value


@router.post(
    "/{novel_id}/episodes/{episode_id}/flags/{flag_id}/revalidate",
    response_model=FlagPublic,
    status_code=status.HTTP_202_ACCEPTED,
)
def revalidate_flag(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    flag_id: uuid.UUID,
    body: RevalidateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FlagPublic:
    """Judges an open flag again against its card (7.5): only the judgment
    that raised it, by the CPU worker (pipeline/revalidate_flag.py). With a
    setting, the card's value for the flag's attribute becomes it first — the
    author's value — and the episode's other open flags on that attribute,
    judged against the old value, are judged again too. Without one, while
    the flag's last revalidation is still queued or running, returns that one
    instead of starting another."""
    # The novel's row lock: this may write a setting card, as accepting does.
    _get_episode(db, novel_id, episode_id, user, for_update=True)
    flag, claim = _get_flag(db, novel_id, episode_id, flag_id)
    if flag.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_HANDLED)
    if not flag.attribute:
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_NO_VALUE)
    if flag.attribute in _HISTORY_ATTR_KEYS:
        raise HTTPException(status.HTTP_409_CONFLICT, FLAG_NO_SETTING)
    _raise_if_run_active(db, novel_id, episode_id)
    card, attrs_field = _card_of(db, novel_id, claim)

    to_judge = [flag]
    if body.setting is not None:
        attrs = getattr(card, attrs_field) or {}
        current = attrs.get(flag.attribute)
        if normalize_name(str(current or "")) != normalize_name(flag.reference_text or ""):
            raise HTTPException(status.HTTP_409_CONFLICT, FLAG_SETTING_CHANGED)
        if normalize_name(body.setting) != normalize_name(str(current or "")):
            # Reassigned, not mutated: SQLAlchemy doesn't see changes inside a JSONB value.
            setattr(card, attrs_field, {**attrs, flag.attribute: body.setting})
            # The author's value now, not an episode's to replace on a later run.
            card.attr_sources = {
                key: record for key, record in (card.attr_sources or {}).items() if key != flag.attribute
            }
            to_judge += list(
                db.scalars(
                    select(ContradictionFlag)
                    .join(Claim, Claim.id == ContradictionFlag.claim_id)
                    .where(
                        ContradictionFlag.novel_id == novel_id,
                        ContradictionFlag.id != flag.id,
                        ContradictionFlag.status == "open",
                        ContradictionFlag.attribute == flag.attribute,
                        Claim.novel_id == novel_id,
                        Claim.episode_id == episode_id,
                        Claim.subject_kind == claim.subject_kind,
                        Claim.subject_id == claim.subject_id,
                    )
                )
            )
            # Held against the new value from now on, not judged against it
            # yet (as accepting leaves the other flags): kept even if the
            # revalidation then fails, so another one — with the value as it
            # now is — can still be asked for.
            for each in to_judge:
                each.reference_text = body.setting
                each.confidence = None
    elif (active := _latest_revalidations(db, novel_id, [flag.id]).get(flag.id)) is not None and (
        active.status in _ACTIVE_STATUSES
    ):
        db.commit()
        return _flag_public(flag, claim, active)

    # One in progress on any of them judges a value that is no longer the one
    # to judge (or will be judged again anyway): this one replaces it.
    db.execute(
        update(FlagRevalidation)
        .where(
            FlagRevalidation.novel_id == novel_id,
            FlagRevalidation.flag_id.in_([each.id for each in to_judge]),
            FlagRevalidation.status.in_(_ACTIVE_STATUSES),
        )
        .values(status="failed", error="superseded", finished_at=func.now())
    )
    revalidations = [FlagRevalidation(novel_id=novel_id, flag_id=each.id, status="queued") for each in to_judge]
    db.add_all(revalidations)
    # Committed (with the setting) before they're enqueued, so the worker
    # can't pick a job up before the row it names exists.
    db.commit()
    try:
        queue = get_queue_client()
        for revalidation in revalidations:
            queue.enqueue({"job_id": str(revalidation.id), "type": "revalidate_flag", "novel_id": str(novel_id)})
    except Exception:
        logger.exception("Could not enqueue revalidation of flag %s", flag.id)
        db.execute(
            update(FlagRevalidation)
            .where(
                FlagRevalidation.id.in_([revalidation.id for revalidation in revalidations]),
                FlagRevalidation.status == "queued",
            )
            .values(status="failed", error="queue_unavailable", finished_at=func.now())
        )
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Revalidation is unavailable right now")
    db.refresh(revalidations[0])
    return _flag_public(flag, claim, revalidations[0])


# --- claims waiting for the author to pick a card (7.1.1) ---------------------

# 409 details, as codes the result screen turns into messages.
LINK_HANDLED = "link_handled"  # the claim isn't waiting for a pick (picked already, or a new run replaced it)
LINK_NOT_A_CANDIDATE = "link_not_a_candidate"  # the card isn't one the claim could be
LINK_CARD_MISSING = "link_card_missing"  # the card was deleted
LINK_RUN_ACTIVE = "link_run_active"  # a run is validating the episode and would replace the claim
# A pick still queued or judging this long after it was made is taken to be lost
# (no worker running), and the claim goes back to pending, as an abandoned run
# fails (RUN_ABANDON_AFTER).
LINK_ABANDON_AFTER = RUN_ABANDON_AFTER
_LINK_ACTIVE = ("queued", "judging")


class PendingCandidate(BaseModel):
    id: uuid.UUID
    kind: str  # character
    name: str
    aliases: list[str]  # tell characters with one name apart


class PendingLinkPublic(BaseModel):
    id: uuid.UUID  # the claim
    status: Literal["pending", "judging"]  # judging: picked, being judged
    evidence_text: str | None  # the manuscript sentence
    # What it says, as setting-card keys: {"eye_color": "붉게"}
    attributes: dict[str, str]
    # The name the sentence gave where it's one several characters share;
    # None for a bare pronoun
    subject_name: str | None
    candidates: list[PendingCandidate]  # the ones that still exist
    picked_id: uuid.UUID | None  # judging only


class LinkPick(BaseModel):
    # The character picked; None: the sentence isn't about any of them
    subject_id: uuid.UUID | None


class LinkPickResult(BaseModel):
    id: uuid.UUID
    outcome: Literal["judging", "skipped"]


def _put_back_stale_picks(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID) -> None:
    db.execute(
        update(Claim)
        .where(
            Claim.novel_id == novel_id,
            Claim.episode_id == episode_id,
            Claim.link_status.in_(_LINK_ACTIVE),
            Claim.link_requested_at < datetime.now(UTC) - LINK_ABANDON_AFTER,
        )
        .values(link_status="pending", subject_id=None, link_requested_at=None)
    )


def _pending_link_public(claim: Claim, alive: dict[uuid.UUID, Character]) -> PendingLinkPublic:
    candidates = []
    for option in claim.candidates or []:
        try:
            card = alive.get(uuid.UUID(str(option.get("id"))))
        except ValueError:
            continue
        if card is not None:
            candidates.append(
                PendingCandidate(
                    id=card.id,
                    kind="character",
                    name=card.name,
                    aliases=[str(alias) for alias in card.aliases or []],
                )
            )
    judging = claim.link_status in _LINK_ACTIVE
    return PendingLinkPublic(
        id=claim.id,
        status="judging" if judging else "pending",
        evidence_text=claim.evidence_text,
        attributes={str(key): str(value) for key, value in (claim.attributes or {}).items()},
        # A claim being judged already has the picked card's name.
        subject_name=None if judging else claim.subject_name,
        candidates=candidates,
        picked_id=claim.subject_id if judging else None,
    )


@router.get("/{novel_id}/episodes/{episode_id}/pending-links", response_model=list[PendingLinkPublic])
def list_pending_links(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[PendingLinkPublic]:
    """The claims the extraction couldn't tie to one card — a pronoun that fits
    several characters, a name several share — in the order of the manuscript,
    for the author to pick a card for (7.1.1), with the picks being judged. A
    new run replaces them."""
    episode = _get_episode(db, novel_id, episode_id, user)
    _put_back_stale_picks(db, novel_id, episode_id)
    claims = list(
        db.scalars(
            select(Claim).where(
                Claim.novel_id == novel_id,
                Claim.episode_id == episode_id,
                Claim.link_status.in_(("pending", *_LINK_ACTIVE)),
            )
        )
    )
    alive = {card.id: card for card in db.scalars(select(Character).where(Character.novel_id == novel_id))}
    db.commit()

    def position(claim: Claim) -> int:
        found = episode.content.find(claim.evidence_text) if claim.evidence_text else -1
        return found if found >= 0 else len(episode.content)

    claims.sort(key=lambda claim: (position(claim), str(claim.id)))
    return [_pending_link_public(claim, alive) for claim in claims]


@router.post(
    "/{novel_id}/episodes/{episode_id}/pending-links/{claim_id}",
    response_model=LinkPickResult,
    status_code=status.HTTP_202_ACCEPTED,
)
def pick_pending_link(
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    claim_id: uuid.UUID,
    body: LinkPick,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> LinkPickResult:
    """The author's pick for a claim waiting for one (7.1.1): a card among its
    candidates, which the CPU worker judges the claim against now
    (pipeline/judge_linked_claim.py), or none ("해당 없음"), which drops it.
    Either is kept, so the next run applies it and doesn't ask again."""
    _get_episode(db, novel_id, episode_id, user, for_update=True)
    claim = db.scalar(
        select(Claim).where(Claim.id == claim_id, Claim.novel_id == novel_id, Claim.episode_id == episode_id)
    )
    if claim is None:
        # A new run replaced it (or it was handled and dropped): not a claim that was never there.
        raise HTTPException(status.HTTP_409_CONFLICT, LINK_HANDLED)
    _put_back_stale_picks(db, novel_id, episode_id)
    db.refresh(claim)
    if claim.link_status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, LINK_HANDLED)
    # A run in progress replaces the claim when it finishes.
    latest = _latest_run(db, novel_id, episode_id)
    if latest is not None:
        _abandon_if_stale(db, latest)
        if latest.status in _ACTIVE_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, LINK_RUN_ACTIVE)

    key = link_key(claim.evidence_text, claim.subject_name or "")
    if body.subject_id is None:
        record_choice(db, novel_id, episode_id, key, None)
        db.delete(claim)
        db.commit()
        return LinkPickResult(id=claim_id, outcome="skipped")

    candidate_ids = {str(option.get("id")) for option in claim.candidates or []}
    if str(body.subject_id) not in candidate_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, LINK_NOT_A_CANDIDATE)
    card = db.scalar(select(Character).where(Character.id == body.subject_id, Character.novel_id == novel_id))
    if card is None:
        raise HTTPException(status.HTTP_409_CONFLICT, LINK_CARD_MISSING)
    record_choice(db, novel_id, episode_id, key, card.id)
    # The name it came with stays (it's part of the key the pick is kept under,
    # and what the claim goes back to if it isn't judged); the worker renames it
    # for the card once it's judged.
    claim.subject_id = card.id
    claim.link_status = "queued"
    claim.link_requested_at = func.now()
    # Committed before it's enqueued, so the worker can't pick the job up
    # before the state it expects exists.
    db.commit()
    try:
        get_queue_client().enqueue({"job_id": str(claim_id), "type": "judge_linked_claim", "novel_id": str(novel_id)})
    except Exception:
        logger.exception("Could not enqueue the judgment of claim %s", claim_id)
        db.execute(
            update(Claim)
            .where(Claim.id == claim_id, Claim.link_status == "queued")
            .values(link_status="pending", subject_id=None, link_requested_at=None)
        )
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Judging is unavailable right now")
    return LinkPickResult(id=claim_id, outcome="judging")
