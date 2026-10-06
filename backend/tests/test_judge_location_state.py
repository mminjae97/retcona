import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from models.location import Location
from pipeline import judges
from pipeline.context_bundle import Card, ContextBundle, _latest_states
from pipeline.extract_claims import ExtractedClaim
from pipeline.merge import apply_new_information

SENTENCE = "벨로스 성은 번화한 항구도시였다."


def _claim(**attributes):
    return ExtractedClaim(
        claim_type="location",
        subject_kind="location",
        subject="벨로스 성",
        text=SENTENCE,
        attributes=attributes,
        evidence=SENTENCE,
    )


def _bundle(state="폐허가 되었다", attrs=None):
    card = Card(kind="location", id=uuid.uuid4(), name="벨로스 성", attrs=attrs or {}, sources={}, state=state)
    return card, ContextBundle(episode_id=uuid.uuid4(), claim_cards=[card])


@pytest.fixture
def nli(monkeypatch):
    """The model, answering every pair with the given contradiction probability."""
    calls = []

    def answer(probability):
        def check(pairs):
            calls.append(pairs)
            return [SimpleNamespace(contradiction=probability) for _ in pairs]

        monkeypatch.setattr(judges, "check_contradictions", check)
        return calls

    return answer


def test_features_after_the_place_fell_are_held_against_its_state(nli):
    calls = nli(0.9)
    card, bundle = _bundle()
    [flag] = judges.judge_location([_claim(features="번화한 항구도시")], bundle)
    assert calls == [[("벨로스 성은 폐허가 되었다.", SENTENCE)]]
    assert (flag.attribute, flag.error_type, flag.subject_id) == ("state", "location", card.id)
    assert (flag.reference_text, flag.evidence_text, flag.claim_index) == ("폐허가 되었다", SENTENCE, 0)


def test_a_pair_the_model_finds_unlikely_to_contradict_is_not_flagged(nli):
    nli(0.1)
    _, bundle = _bundle()
    assert judges.judge_location([_claim(features="번화한 항구도시")], bundle) == []


def test_a_place_with_no_earlier_state_has_nothing_to_contradict(nli):
    calls = nli(0.9)
    _, bundle = _bundle(state=None)
    assert judges.judge_location([_claim(features="번화한 항구도시")], bundle) == []
    assert not any(calls)  # no pair went to the model


def test_a_claim_that_says_a_change_of_state_itself_is_not_held_against_the_old_one(nli):
    calls = nli(0.9)
    _, bundle = _bundle(state="재건되었다")
    assert judges.judge_location([_claim(features="높은 산 위", state="불타 사라졌다")], bundle) == []
    assert not any(calls)  # no pair went to the model


def test_a_state_only_claim_is_held_against_nothing(nli):
    calls = nli(0.9)
    _, bundle = _bundle()
    assert judges.judge_location([_claim(state="재건되었다")], bundle) == []
    assert not any(calls)  # no pair went to the model


def test_features_are_still_held_against_the_card_beside_the_state(nli):
    calls = nli(0.9)
    _, bundle = _bundle(attrs={"features": "북쪽 국경의 요새"})
    flags = judges.judge_location([_claim(features="번화한 항구도시")], bundle)
    assert [flag.attribute for flag in flags] == ["features", "state"]
    assert [flag.reference_text for flag in flags] == ["북쪽 국경의 요새", "폐허가 되었다"]
    assert len(calls) == 1


def test_a_feature_held_against_the_state_does_not_go_into_the_card(nli):
    nli(0.9)
    location = Location(id=uuid.uuid4(), name="벨로스 성", geo_attrs={}, attr_sources={})
    card = Card(kind="location", id=location.id, name="벨로스 성", attrs={}, sources={}, state="폐허가 되었다")
    claim = _claim(features="번화한 항구도시")
    flags = judges.judge_location([claim], ContextBundle(episode_id=uuid.uuid4(), claim_cards=[card]))
    db = MagicMock()
    db.scalars.side_effect = [[], [location]]
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 5, SENTENCE, [claim], [location.id], flags)
    assert location.geo_attrs == {}


def _history(location_id, *states):
    return [SimpleNamespace(location_id=location_id, state=state) for state in states]


def test_the_latest_earlier_state_of_each_place_is_the_one_found():
    place, other = uuid.uuid4(), uuid.uuid4()
    db = MagicMock()
    db.scalar.return_value = 5  # this episode's index
    # Latest episode first, as the query orders them; one with nothing to say of the place's state.
    db.execute.return_value = (
        _history(place, {"features": "x"}, {"state": "재건되었다"}, {"state": "폐허가 되었다"})
        + _history(other, {"state": "불탔다"})
    )
    assert _latest_states(db, uuid.uuid4(), uuid.uuid4(), [place, other]) == {
        place: "재건되었다",
        other: "불탔다",
    }


def test_no_state_is_looked_for_without_places_or_for_an_unknown_episode():
    db = MagicMock()
    assert _latest_states(db, uuid.uuid4(), uuid.uuid4(), []) == {}
    db.scalar.return_value = None
    assert _latest_states(db, uuid.uuid4(), uuid.uuid4(), [uuid.uuid4()]) == {}
    db.execute.assert_not_called()
