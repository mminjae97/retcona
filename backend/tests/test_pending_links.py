"""What the result screen is given for claims waiting for a pick, and how the
judgment of a pick reads the episode (pipeline/judges.py other_subjects)."""

import uuid
from types import SimpleNamespace

from ai.nli_rerank import NLIScores
from api.episodes import _pending_link_public
from pipeline import judges
from pipeline.context_bundle import Card, ContextBundle
from pipeline.extract_claims import ExtractedClaim

LEON, SERIN, GONE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
ALIVE = {
    LEON: SimpleNamespace(id=LEON, name="레온", aliases=["붉은 늑대"]),
    SERIN: SimpleNamespace(id=SERIN, name="세린", aliases=None),
}


def _claim(status="pending", subject_id=None, subject_name=None):
    options = [
        {"kind": "character", "id": str(LEON), "name": "레온", "aliases": []},
        {"kind": "character", "id": str(SERIN), "name": "세린", "aliases": []},
        {"kind": "character", "id": str(GONE), "name": "사라진 인물", "aliases": []},
        {"kind": "character", "id": "not-an-id", "name": "?", "aliases": []},
    ]
    return SimpleNamespace(
        id=uuid.uuid4(),
        link_status=status,
        evidence_text="그의 눈이 붉게 빛났다.",
        attributes={"eye_color": "붉게"},
        candidates=options,
        subject_id=subject_id,
        subject_name=subject_name,
    )


def test_a_pending_claim_is_offered_the_candidates_that_still_exist_with_their_aliases():
    item = _pending_link_public(_claim(), ALIVE)
    assert item.status == "pending"
    assert [(c.id, c.name, c.aliases) for c in item.candidates] == [(LEON, "레온", ["붉은 늑대"]), (SERIN, "세린", [])]
    assert (item.evidence_text, item.attributes, item.subject_name, item.picked_id) == (
        "그의 눈이 붉게 빛났다.",
        {"eye_color": "붉게"},
        None,
        None,
    )


def test_a_name_two_characters_share_is_shown_as_the_name_the_sentence_gave():
    item = _pending_link_public(_claim(subject_name="김철수"), ALIVE)
    assert item.subject_name == "김철수"


def test_a_pick_being_judged_shows_which_card_was_picked():
    for status in ("queued", "judging"):
        item = _pending_link_public(_claim(status, subject_id=SERIN, subject_name="세린"), ALIVE)
        assert (item.status, item.picked_id, item.subject_name) == ("judging", SERIN, None)


def _hypothesis_read(monkeypatch, evidence, other_subjects):
    """The sentence the model is given to compare with the card's setting."""
    seen = []

    def fake(pairs):
        seen.extend(pairs)
        return [NLIScores(entailment=0.0, neutral=0.0, contradiction=1.0) for _ in pairs]

    monkeypatch.setattr(judges, "check_contradictions", fake)
    card = Card(kind="character", id=SERIN, name="세린", attrs={"eye_color": "푸른색"}, sources={})
    bundle = ContextBundle(episode_id=uuid.uuid4(), claim_cards=[card])
    claim = ExtractedClaim(
        claim_type="appearance",
        subject_kind="character",
        subject="세린",
        text="세린의 눈 색깔은 붉은이다.",
        evidence=evidence,
        attributes={"eye_color": "붉은"},
    )
    judges.judge_appearance([claim], bundle, other_subjects)
    return seen[0][1]


def test_judging_one_claim_reads_the_sentence_as_the_whole_episode_would(monkeypatch):
    evidence = "세린은 레온의 붉은 눈을 보았다."
    # Judged alone, 세린 is the only subject and the sentence is taken as it is.
    assert _hypothesis_read(monkeypatch, evidence, set()) == evidence
    # With the episode's other subjects, a sentence naming another is read by the claim's restatement.
    assert _hypothesis_read(monkeypatch, evidence, {"레온"}) == "세린의 눈 색깔은 붉은이다."
