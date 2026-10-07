"""Relationships between a novel's characters (design doc 4.3, 9.2).

What the relationship graph draws: characters are its nodes, and these are its
edges. The author enters them here; nothing reads them out of the manuscript
yet. A relation has a type in the author's words ("가족", "연인", "라이벌", ...)
and is either mutual ("친구") or points from one character to the other
("스승" -> "제자").

Stored as relations rows (models/relation.py), entity_kind "character" — the
same table holds distances between locations, which this module leaves alone.
A directed relation is stored as direction "from_to"; "to_from" is read as the
same relation the other way round.

Every write locks the novel row first, like the other per-novel endpoints
(api/settings.py), which also serializes the duplicate check below.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from api.deps import get_owned_novel as _get_owned_novel
from auth.dependencies import get_current_user
from models.character import Character
from models.db import get_db
from models.relation import Relation
from models.user import User
from pipeline.entities import normalize_name

router = APIRouter()
_DB = Depends(get_db)
_USER = Depends(get_current_user)

_TYPE_MAX_LENGTH = 50
DIRECTED = "from_to"
KIND = "character"


class RelationInput(BaseModel):
    from_id: uuid.UUID
    to_id: uuid.UUID
    relation_type: str = Field(min_length=1, max_length=_TYPE_MAX_LENGTH)
    # Points from from_id to to_id; otherwise the relation is mutual.
    directed: bool = False

    @field_validator("relation_type")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("A relation needs a type")
        return value

    @model_validator(mode="after")
    def _two_characters(self) -> "RelationInput":
        if self.from_id == self.to_id:
            raise ValueError("A relation is between two different characters")
        return self


class RelationPublic(BaseModel):
    id: uuid.UUID
    from_id: uuid.UUID
    to_id: uuid.UUID
    relation_type: str
    directed: bool


def _public(relation: Relation) -> RelationPublic:
    from_id, to_id = relation.from_entity_id, relation.to_entity_id
    if relation.direction == "to_from":
        from_id, to_id = to_id, from_id
    return RelationPublic(
        id=relation.id,
        from_id=from_id,
        to_id=to_id,
        relation_type=relation.relation_type,
        directed=relation.direction in (DIRECTED, "to_from"),
    )


def _same(a: RelationPublic | RelationInput, b: RelationPublic | RelationInput) -> bool:
    """Whether two relations say the same thing: the same type between the
    same two characters, in the same direction if they have one."""
    if normalize_name(a.relation_type) != normalize_name(b.relation_type):
        return False
    if (a.from_id, a.to_id) == (b.from_id, b.to_id):
        return a.directed == b.directed or not (a.directed or b.directed)
    return (a.from_id, a.to_id) == (b.to_id, b.from_id) and not (a.directed or b.directed)


def _get_relation(db: Session, novel_id: uuid.UUID, relation_id: uuid.UUID) -> Relation:
    relation = db.scalar(
        select(Relation).where(Relation.id == relation_id, Relation.novel_id == novel_id, Relation.entity_kind == KIND)
    )
    if relation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relation not found")
    return relation


def _check(db: Session, novel_id: uuid.UUID, body: RelationInput, *, except_id: uuid.UUID | None = None) -> None:
    found = set(
        db.scalars(select(Character.id).where(Character.novel_id == novel_id, Character.id.in_([body.from_id, body.to_id])))
    )
    if found != {body.from_id, body.to_id}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Character not found")
    existing = db.scalars(
        select(Relation).where(
            Relation.novel_id == novel_id,
            Relation.entity_kind == KIND,
            Relation.from_entity_id.in_([body.from_id, body.to_id]),
            Relation.to_entity_id.in_([body.from_id, body.to_id]),
        )
    )
    if any(_same(body, _public(other)) for other in existing if other.id != except_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "This relation already exists")


def _apply(relation: Relation, body: RelationInput) -> None:
    relation.entity_kind = KIND
    relation.from_entity_id = body.from_id
    relation.to_entity_id = body.to_id
    relation.relation_type = body.relation_type
    relation.direction = DIRECTED if body.directed else None


@router.get("/{novel_id}/relations", response_model=list[RelationPublic])
def list_relations(
    novel_id: uuid.UUID, db: Session = _DB, user: User = _USER
) -> list[RelationPublic]:
    _get_owned_novel(db, novel_id, user)
    rows = db.scalars(
        select(Relation).where(Relation.novel_id == novel_id, Relation.entity_kind == KIND).order_by(Relation.created_at, Relation.id)
    )
    return [_public(row) for row in rows]


@router.post("/{novel_id}/relations", response_model=RelationPublic, status_code=status.HTTP_201_CREATED)
def create_relation(
    novel_id: uuid.UUID,
    body: RelationInput,
    db: Session = _DB,
    user: User = _USER,
) -> RelationPublic:
    _get_owned_novel(db, novel_id, user, for_update=True)
    _check(db, novel_id, body)
    relation = Relation(novel_id=novel_id)
    _apply(relation, body)
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return _public(relation)


@router.put("/{novel_id}/relations/{relation_id}", response_model=RelationPublic)
def update_relation(
    novel_id: uuid.UUID,
    relation_id: uuid.UUID,
    body: RelationInput,
    db: Session = _DB,
    user: User = _USER,
) -> RelationPublic:
    _get_owned_novel(db, novel_id, user, for_update=True)
    relation = _get_relation(db, novel_id, relation_id)
    _check(db, novel_id, body, except_id=relation_id)
    _apply(relation, body)
    db.commit()
    db.refresh(relation)
    return _public(relation)


@router.delete("/{novel_id}/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_relation(
    novel_id: uuid.UUID,
    relation_id: uuid.UUID,
    db: Session = _DB,
    user: User = _USER,
) -> None:
    _get_owned_novel(db, novel_id, user, for_update=True)
    db.delete(_get_relation(db, novel_id, relation_id))
    db.commit()
