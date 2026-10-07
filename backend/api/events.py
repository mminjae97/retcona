"""The story timeline's events and the links between them (design doc 4.3, 9.3).

What the timeline graph draws: an event is a node — what happened, in which
episode, to which characters, in which places — and a link is an edge from one
event to the one that follows from it. The author enters them here; nothing
reads them out of the manuscript yet.

A link is "sequential" (the story goes on), "branch" (one event leads on to
several that go their own ways, with the reason — the character or place that
set them apart — optionally written down) or "merge" (separate lines come
together again). The author says which: the graph's shape alone can't tell a
split from an event that merely has two consequences.

Every write locks the novel row first, like the other per-novel endpoints
(api/settings.py), which also serializes the duplicate check on links.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from api.deps import get_owned_novel as _get_owned_novel
from auth.dependencies import get_current_user
from models.character import Character
from models.db import get_db
from models.location import Location
from models.story_event import EventLink, EventLocation, EventParticipant, StoryEvent
from models.user import User

router = APIRouter()
_DB = Depends(get_db)
_USER = Depends(get_current_user)

_EPISODE_MAX = 100_000  # the column is a 32-bit integer; no serial runs this long
_SUMMARY_MAX_LENGTH = 500
_REASON_MAX_LENGTH = 200
_MEMBERS_MAX = 50

LinkType = Literal["sequential", "branch", "merge"]


def _unique(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    return list(dict.fromkeys(ids))


class EventInput(BaseModel):
    episode_index: int = Field(ge=1, le=_EPISODE_MAX)
    summary: str = Field(min_length=1, max_length=_SUMMARY_MAX_LENGTH)
    character_ids: list[uuid.UUID] = Field(default_factory=list, max_length=_MEMBERS_MAX)
    location_ids: list[uuid.UUID] = Field(default_factory=list, max_length=_MEMBERS_MAX)

    @field_validator("summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("An event needs a summary")
        return value

    @field_validator("character_ids", "location_ids")
    @classmethod
    def _once_each(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        return _unique(value)


class EventPublic(BaseModel):
    id: uuid.UUID
    episode_index: int
    summary: str
    character_ids: list[uuid.UUID]
    location_ids: list[uuid.UUID]


class LinkInput(BaseModel):
    from_id: uuid.UUID
    to_id: uuid.UUID
    link_type: LinkType = "sequential"
    # Only a branch has one: what set the lines apart.
    branch_reason: str | None = Field(None, max_length=_REASON_MAX_LENGTH)

    @model_validator(mode="after")
    def _two_events(self) -> "LinkInput":
        if self.from_id == self.to_id:
            raise ValueError("A link is between two different events")
        reason = (self.branch_reason or "").strip()
        self.branch_reason = reason if reason and self.link_type == "branch" else None
        return self


class LinkPublic(BaseModel):
    id: uuid.UUID
    from_id: uuid.UUID
    to_id: uuid.UUID
    link_type: str  # LinkType, as stored
    branch_reason: str | None


class LocationPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str


# ---------------------------------------------------------------- locations


@router.get("/{novel_id}/locations", response_model=list[LocationPublic])
def list_locations(novel_id: uuid.UUID, db: Session = _DB, user: User = _USER) -> list[Location]:
    """The places the manuscript's claims registered (7.4), for the author to
    pick the ones an event happens in."""
    _get_owned_novel(db, novel_id, user)
    return list(db.scalars(select(Location).where(Location.novel_id == novel_id).order_by(Location.name, Location.id)))


# ---------------------------------------------------------------- events


def _public_events(db: Session, novel_id: uuid.UUID, events: list[StoryEvent]) -> list[EventPublic]:
    ids = [event.id for event in events]
    characters: dict[uuid.UUID, list[uuid.UUID]] = {}
    locations: dict[uuid.UUID, list[uuid.UUID]] = {}
    if ids:
        for event_id, character_id in db.execute(
            select(EventParticipant.event_id, EventParticipant.character_id)
            .where(EventParticipant.novel_id == novel_id, EventParticipant.event_id.in_(ids))
            .order_by(EventParticipant.created_at, EventParticipant.id)
        ):
            characters.setdefault(event_id, []).append(character_id)
        for event_id, location_id in db.execute(
            select(EventLocation.event_id, EventLocation.location_id)
            .where(EventLocation.novel_id == novel_id, EventLocation.event_id.in_(ids))
            .order_by(EventLocation.created_at, EventLocation.id)
        ):
            locations.setdefault(event_id, []).append(location_id)
    return [
        EventPublic(
            id=event.id,
            episode_index=event.episode_index,
            summary=event.summary,
            character_ids=characters.get(event.id, []),
            location_ids=locations.get(event.id, []),
        )
        for event in events
    ]


def _get_event(db: Session, novel_id: uuid.UUID, event_id: uuid.UUID) -> StoryEvent:
    event = db.scalar(select(StoryEvent).where(StoryEvent.id == event_id, StoryEvent.novel_id == novel_id))
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    return event


def _check_members(db: Session, novel_id: uuid.UUID, body: EventInput) -> None:
    """The characters and places an event names are this novel's."""
    if body.character_ids:
        found = set(db.scalars(select(Character.id).where(Character.novel_id == novel_id, Character.id.in_(body.character_ids))))
        if found != set(body.character_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Character not found")
    if body.location_ids:
        found = set(db.scalars(select(Location.id).where(Location.novel_id == novel_id, Location.id.in_(body.location_ids))))
        if found != set(body.location_ids):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")


def _set_members(db: Session, novel_id: uuid.UUID, event_id: uuid.UUID, body: EventInput) -> None:
    db.execute(delete(EventParticipant).where(EventParticipant.novel_id == novel_id, EventParticipant.event_id == event_id))
    db.execute(delete(EventLocation).where(EventLocation.novel_id == novel_id, EventLocation.event_id == event_id))
    db.add_all(EventParticipant(novel_id=novel_id, event_id=event_id, character_id=i) for i in body.character_ids)
    db.add_all(EventLocation(novel_id=novel_id, event_id=event_id, location_id=i) for i in body.location_ids)


@router.get("/{novel_id}/events", response_model=list[EventPublic])
def list_events(novel_id: uuid.UUID, db: Session = _DB, user: User = _USER) -> list[EventPublic]:
    _get_owned_novel(db, novel_id, user)
    events = list(
        db.scalars(
            select(StoryEvent)
            .where(StoryEvent.novel_id == novel_id)
            .order_by(StoryEvent.episode_index, StoryEvent.created_at, StoryEvent.id)
        )
    )
    return _public_events(db, novel_id, events)


@router.post("/{novel_id}/events", response_model=EventPublic, status_code=status.HTTP_201_CREATED)
def create_event(novel_id: uuid.UUID, body: EventInput, db: Session = _DB, user: User = _USER) -> EventPublic:
    _get_owned_novel(db, novel_id, user, for_update=True)
    _check_members(db, novel_id, body)
    event = StoryEvent(novel_id=novel_id, episode_index=body.episode_index, summary=body.summary)
    db.add(event)
    db.flush()
    _set_members(db, novel_id, event.id, body)
    db.commit()
    return _public_events(db, novel_id, [event])[0]


@router.put("/{novel_id}/events/{event_id}", response_model=EventPublic)
def update_event(
    novel_id: uuid.UUID, event_id: uuid.UUID, body: EventInput, db: Session = _DB, user: User = _USER
) -> EventPublic:
    _get_owned_novel(db, novel_id, user, for_update=True)
    event = _get_event(db, novel_id, event_id)
    _check_members(db, novel_id, body)
    event.episode_index = body.episode_index
    event.summary = body.summary
    _set_members(db, novel_id, event.id, body)
    db.commit()
    return _public_events(db, novel_id, [event])[0]


@router.delete("/{novel_id}/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(novel_id: uuid.UUID, event_id: uuid.UUID, db: Session = _DB, user: User = _USER) -> None:
    _get_owned_novel(db, novel_id, user, for_update=True)
    event = _get_event(db, novel_id, event_id)
    # What hangs off it goes with it: who and where, and the links to and from it.
    db.execute(delete(EventParticipant).where(EventParticipant.novel_id == novel_id, EventParticipant.event_id == event_id))
    db.execute(delete(EventLocation).where(EventLocation.novel_id == novel_id, EventLocation.event_id == event_id))
    db.execute(
        delete(EventLink).where(
            EventLink.novel_id == novel_id, or_(EventLink.from_event_id == event_id, EventLink.to_event_id == event_id)
        )
    )
    db.delete(event)
    db.commit()


# ---------------------------------------------------------------- links


def _public_link(link: EventLink) -> LinkPublic:
    return LinkPublic(
        id=link.id,
        from_id=link.from_event_id,
        to_id=link.to_event_id,
        link_type=link.link_type,
        branch_reason=link.branch_reason,
    )


def _get_link(db: Session, novel_id: uuid.UUID, link_id: uuid.UUID) -> EventLink:
    link = db.scalar(select(EventLink).where(EventLink.id == link_id, EventLink.novel_id == novel_id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    return link


def _check_link(db: Session, novel_id: uuid.UUID, body: LinkInput, *, except_id: uuid.UUID | None = None) -> None:
    found = set(db.scalars(select(StoryEvent.id).where(StoryEvent.novel_id == novel_id, StoryEvent.id.in_([body.from_id, body.to_id]))))
    if found != {body.from_id, body.to_id}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Event not found")
    # One link from an event to another, whatever its type: the type is part of what it says.
    query = select(EventLink.id).where(
        EventLink.novel_id == novel_id, EventLink.from_event_id == body.from_id, EventLink.to_event_id == body.to_id
    )
    if except_id is not None:
        query = query.where(EventLink.id != except_id)
    if db.scalar(query) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This link already exists")


def _apply_link(link: EventLink, body: LinkInput) -> None:
    link.from_event_id = body.from_id
    link.to_event_id = body.to_id
    link.link_type = body.link_type
    link.branch_reason = body.branch_reason


@router.get("/{novel_id}/event-links", response_model=list[LinkPublic])
def list_links(novel_id: uuid.UUID, db: Session = _DB, user: User = _USER) -> list[LinkPublic]:
    _get_owned_novel(db, novel_id, user)
    rows = db.scalars(select(EventLink).where(EventLink.novel_id == novel_id).order_by(EventLink.created_at, EventLink.id))
    return [_public_link(row) for row in rows]


@router.post("/{novel_id}/event-links", response_model=LinkPublic, status_code=status.HTTP_201_CREATED)
def create_link(novel_id: uuid.UUID, body: LinkInput, db: Session = _DB, user: User = _USER) -> LinkPublic:
    _get_owned_novel(db, novel_id, user, for_update=True)
    _check_link(db, novel_id, body)
    link = EventLink(novel_id=novel_id)
    _apply_link(link, body)
    db.add(link)
    db.commit()
    db.refresh(link)
    return _public_link(link)


@router.put("/{novel_id}/event-links/{link_id}", response_model=LinkPublic)
def update_link(
    novel_id: uuid.UUID, link_id: uuid.UUID, body: LinkInput, db: Session = _DB, user: User = _USER
) -> LinkPublic:
    _get_owned_novel(db, novel_id, user, for_update=True)
    link = _get_link(db, novel_id, link_id)
    _check_link(db, novel_id, body, except_id=link_id)
    _apply_link(link, body)
    db.commit()
    db.refresh(link)
    return _public_link(link)


@router.delete("/{novel_id}/event-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_link(novel_id: uuid.UUID, link_id: uuid.UUID, db: Session = _DB, user: User = _USER) -> None:
    _get_owned_novel(db, novel_id, user, for_update=True)
    db.delete(_get_link(db, novel_id, link_id))
    db.commit()
