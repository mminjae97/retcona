import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.relations import RelationInput, RelationPublic, _apply, _check, _public, _same
from models.relation import Relation

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def _rel(from_id, to_id, relation_type="친구", directed=False):
    return RelationPublic(id=uuid.uuid4(), from_id=from_id, to_id=to_id, relation_type=relation_type, directed=directed)


def test_a_relation_needs_two_different_characters_and_a_type():
    with pytest.raises(ValidationError):
        RelationInput(from_id=A, to_id=A, relation_type="친구")
    with pytest.raises(ValidationError):
        RelationInput(from_id=A, to_id=B, relation_type="   ")
    assert RelationInput(from_id=A, to_id=B, relation_type=" 친구 ").relation_type == "친구"


def test_a_directed_relation_is_stored_from_to_and_a_mutual_one_without_direction():
    relation = Relation()
    _apply(relation, RelationInput(from_id=A, to_id=B, relation_type="스승", directed=True))
    assert (relation.direction, relation.entity_kind) == ("from_to", "character")
    _apply(relation, RelationInput(from_id=A, to_id=B, relation_type="친구"))
    assert relation.direction is None


def test_a_relation_stored_to_from_is_read_the_other_way_round():
    row = SimpleNamespace(id=uuid.uuid4(), from_entity_id=A, to_entity_id=B, relation_type="스승", direction="to_from")
    public = _public(row)
    assert (public.from_id, public.to_id, public.directed) == (B, A, True)


@pytest.mark.parametrize(
    "first, second, same",
    [
        (_rel(A, B), _rel(B, A), True),  # mutual, either way round
        (_rel(A, B, "친구"), _rel(A, B, " 친구 "), True),
        (_rel(A, B, directed=True), _rel(A, B, directed=True), True),
        (_rel(A, B, directed=True), _rel(B, A, directed=True), False),  # two directions, two relations
        (_rel(A, B, directed=True), _rel(A, B), False),
        (_rel(A, B, "친구"), _rel(A, B, "라이벌"), False),
        (_rel(A, B), _rel(A, C), False),
    ],
)
def test_two_relations_are_the_same_when_they_say_the_same_thing(first, second, same):
    assert _same(first, second) is same


def _db(characters, relations=()):
    db = MagicMock()
    db.scalars.side_effect = [iter(characters), iter(relations)]
    return db


def test_a_relation_to_a_character_not_in_the_novel_is_refused():
    with pytest.raises(HTTPException) as error:
        _check(_db([A]), uuid.uuid4(), RelationInput(from_id=A, to_id=B, relation_type="친구"))
    assert error.value.status_code == 404


def test_a_relation_that_already_exists_is_refused_but_not_against_itself():
    existing = SimpleNamespace(id=uuid.uuid4(), from_entity_id=B, to_entity_id=A, relation_type="친구", direction=None)
    body = RelationInput(from_id=A, to_id=B, relation_type="친구")
    with pytest.raises(HTTPException) as error:
        _check(_db([A, B], [existing]), uuid.uuid4(), body)
    assert error.value.status_code == 409
    _check(_db([A, B], [existing]), uuid.uuid4(), body, except_id=existing.id)
