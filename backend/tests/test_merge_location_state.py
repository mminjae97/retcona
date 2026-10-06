import uuid
from unittest.mock import MagicMock

from models.location import Location, LocationStateHistory
from pipeline.extract_claims import ExtractedClaim
from pipeline.merge import apply_new_information


def _claim(**attributes):
    return ExtractedClaim(
        claim_type="location",
        subject_kind="location",
        subject="벨로스 성",
        text="벨로스 성은 폐허가 되었다.",
        attributes=attributes,
    )


def _histories(db):
    return [row for call in db.add_all.call_args_list for row in call.args[0] if isinstance(row, LocationStateHistory)]


def test_a_places_change_of_state_is_recorded_for_the_episode_and_not_in_its_card():
    db = MagicMock()
    db.scalars.return_value = []
    location_id = uuid.uuid4()
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 3, "본문", [_claim(state="폐허가 되었다")], [location_id], [])
    [row] = _histories(db)
    assert (row.location_id, row.episode_index, row.state) == (location_id, 3, {"state": "폐허가 되었다"})


def test_a_place_with_only_features_records_no_state():
    db = MagicMock()
    db.scalars.return_value = []
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 3, "본문", [_claim(features="높은 산 위")], [uuid.uuid4()], [])
    assert _histories(db) == []


def test_the_last_state_the_episode_says_is_the_one_recorded():
    db = MagicMock()
    db.scalars.return_value = []
    location_id = uuid.uuid4()
    claims = [_claim(state="폐허가 되었다"), _claim(state="재건되었다")]
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 3, "본문", claims, [location_id, location_id], [])
    [row] = _histories(db)
    assert row.state == {"state": "재건되었다"}


def test_a_rerun_replaces_what_the_episode_recorded_before():
    db = MagicMock()
    db.scalars.return_value = []
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 3, "본문", [_claim(features="높은 산 위")], [uuid.uuid4()], [])
    deletes = [str(call.args[0]) for call in db.execute.call_args_list]
    assert any("DELETE FROM location_state_history" in sql for sql in deletes)


def test_a_state_does_not_go_into_the_card():
    location = Location(id=uuid.uuid4(), name="벨로스 성", geo_attrs={}, attr_sources={})
    db = MagicMock()
    db.scalars.side_effect = [[], [location]]  # the characters, then the locations
    claim = _claim(features="높은 산 위", state="폐허가 되었다")
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 3, "본문", [claim], [location.id], [])
    assert location.geo_attrs == {"features": "높은 산 위"}
    assert "state" not in location.attr_sources
