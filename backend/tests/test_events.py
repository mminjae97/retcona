import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from api.events import EventInput, LinkInput, _check_link, _check_members, _public_link

A, B, C = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_an_event_needs_an_episode_and_a_summary():
    with pytest.raises(ValidationError):
        EventInput(episode_index=0, summary="출발")
    with pytest.raises(ValidationError):
        EventInput(episode_index=1, summary="   ")
    event = EventInput(episode_index=3, summary=" 성으로 출발한다 ", character_ids=[A, A, B])
    assert (event.summary, event.character_ids) == ("성으로 출발한다", [A, B])


def test_an_episode_number_is_bounded_so_the_column_can_hold_it():
    with pytest.raises(ValidationError):
        EventInput(episode_index=3_000_000_000, summary="출발")
    assert EventInput(episode_index=100_000, summary="출발").episode_index == 100_000


def test_a_link_is_between_two_different_events_of_a_known_type():
    with pytest.raises(ValidationError):
        LinkInput(from_id=A, to_id=A)
    with pytest.raises(ValidationError):
        LinkInput(from_id=A, to_id=B, link_type="loop")
    assert LinkInput(from_id=A, to_id=B).link_type == "sequential"


def test_only_a_branch_keeps_its_reason():
    assert LinkInput(from_id=A, to_id=B, link_type="branch", branch_reason=" 세린이 남음 ").branch_reason == "세린이 남음"
    assert LinkInput(from_id=A, to_id=B, link_type="merge", branch_reason="세린이 남음").branch_reason is None
    assert LinkInput(from_id=A, to_id=B, link_type="branch", branch_reason="  ").branch_reason is None


def test_a_link_is_read_as_stored():
    row = SimpleNamespace(id=uuid.uuid4(), from_event_id=A, to_event_id=B, link_type="branch", branch_reason="이유")
    public = _public_link(row)
    assert (public.from_id, public.to_id, public.link_type, public.branch_reason) == (A, B, "branch", "이유")


def _db(*results):
    db = MagicMock()
    db.scalars.side_effect = [iter(result) for result in results]
    return db


def test_an_event_naming_a_character_or_a_place_that_is_not_the_novels_is_refused():
    body = EventInput(episode_index=1, summary="출발", character_ids=[A, B], location_ids=[C])
    with pytest.raises(HTTPException) as error:
        _check_members(_db([A]), uuid.uuid4(), body)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as error:
        _check_members(_db([A, B], []), uuid.uuid4(), body)
    assert error.value.status_code == 404
    _check_members(_db([A, B], [C]), uuid.uuid4(), body)


def test_a_link_to_an_event_not_in_the_novel_is_refused():
    with pytest.raises(HTTPException) as error:
        _check_link(_db([A]), uuid.uuid4(), LinkInput(from_id=A, to_id=B))
    assert error.value.status_code == 404


def test_a_link_that_already_exists_is_refused():
    db = _db([A, B])
    db.scalar.return_value = uuid.uuid4()
    with pytest.raises(HTTPException) as error:
        _check_link(db, uuid.uuid4(), LinkInput(from_id=A, to_id=B))
    assert error.value.status_code == 409
    db = _db([A, B])
    db.scalar.return_value = None
    _check_link(db, uuid.uuid4(), LinkInput(from_id=A, to_id=B, link_type="branch"))
