"""The author's picks for claims the extraction couldn't tie to a card
(pipeline/claim_links.py), applied to the extraction before it's judged."""

import uuid

from pipeline.claim_links import apply_choices, link_key
from pipeline.extract_claims import ExtractedClaim

LEON, SERIN = uuid.uuid4(), uuid.uuid4()
REFS = {"c1": LEON, "c2": SERIN}
CARDS = {"c1": {"name": "레온", "aliases": []}, "c2": {"name": "세린", "aliases": []}}
SENTENCE = "그의 눈이 붉게 빛났다."


def _pending(evidence=SENTENCE, subject="", candidates=("c1", "c2")):
    return ExtractedClaim(
        claim_type="appearance",
        subject_kind="character",
        subject=subject,
        candidates=list(candidates),
        text="그의 눈 색깔은 붉게이다.",
        evidence=evidence,
        attributes={"eye_color": "붉게"},
    )


def test_a_claim_needs_a_subject_or_the_characters_it_could_be():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ExtractedClaim(claim_type="appearance", subject_kind="character", text="x", evidence="x")


def test_the_key_is_the_sentence_by_its_letters_and_the_name_given():
    assert link_key("그의 눈이  붉게 빛났다!", "") == link_key(SENTENCE, "")
    assert link_key(SENTENCE, "김철수") == link_key(SENTENCE, " 김철수 ")
    assert link_key(SENTENCE, "김철수") != link_key(SENTENCE, "")
    assert link_key(SENTENCE, "") != link_key("다른 문장이다.", "")


def test_a_pick_makes_the_claim_one_about_that_card():
    claim = _pending()
    [kept] = apply_choices([claim], {link_key(SENTENCE, ""): SERIN}, REFS, CARDS)
    assert (kept.subject, kept.subject_ref, kept.candidates) == ("세린", "c2", [])
    assert kept.attributes == {"eye_color": "붉게"}
    # Said with her name now, as the judgment reads it where the sentence doesn't name her.
    assert kept.text == "세린의 눈 색깔은 붉게이다."


def test_not_any_of_them_drops_the_claim():
    assert apply_choices([_pending()], {link_key(SENTENCE, ""): None}, REFS, CARDS) == []


def test_a_claim_with_no_pick_stays_pending():
    [kept] = apply_choices([_pending()], {}, REFS, CARDS)
    assert (kept.subject, kept.subject_ref, kept.candidates) == ("", None, ["c1", "c2"])


def test_a_pick_for_a_card_that_is_not_a_candidate_leaves_it_pending():
    gone = uuid.uuid4()
    [kept] = apply_choices([_pending()], {link_key(SENTENCE, ""): gone}, REFS, CARDS)
    assert kept.candidates == ["c1", "c2"] and kept.subject == ""
    [narrowed] = apply_choices([_pending(candidates=("c1",))], {link_key(SENTENCE, ""): SERIN}, REFS, CARDS)
    assert narrowed.candidates == ["c1"]


def test_a_name_two_characters_share_is_picked_the_same_way():
    claim = _pending(evidence="김철수의 눈동자는 푸른색이었다.", subject="김철수")
    key = link_key("김철수의 눈동자는 푸른색이었다.", "김철수")
    [kept] = apply_choices([claim], {key: LEON}, REFS, CARDS)
    assert (kept.subject, kept.subject_ref) == ("레온", "c1")


def test_claims_that_are_not_pending_are_left_as_they_are():
    plain = ExtractedClaim(
        claim_type="appearance", subject_kind="character", subject="레온", subject_ref="c1", text="x", evidence="x"
    )
    assert apply_choices([plain], {link_key("x", "레온"): SERIN}, REFS, CARDS) == [plain]


def test_the_candidates_stored_with_a_pending_claim_tell_same_named_cards_apart_by_alias():
    from pipeline.validate_episode import _candidates

    cards = {
        "c3": {"name": "김철수", "aliases": ["철수형"]},
        "c4": {"name": "김철수", "aliases": ["철수오빠"]},
    }
    refs = {"c3": uuid.uuid4(), "c4": uuid.uuid4()}
    claim = _pending(evidence="김철수의 눈동자는 푸른색이었다.", subject="김철수", candidates=("c3", "c4", "c9"))
    options = _candidates(claim, None, refs, cards)
    assert [(o["id"], o["name"], o["aliases"]) for o in options] == [
        (str(refs["c3"]), "김철수", ["철수형"]),
        (str(refs["c4"]), "김철수", ["철수오빠"]),
    ]
    assert all(o["kind"] == "character" for o in options)
    # A claim that has a card isn't offered any.
    assert _candidates(claim, refs["c3"], refs, cards) == []
