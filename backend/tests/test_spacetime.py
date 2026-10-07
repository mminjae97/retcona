import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from models.character import Character
from pipeline import extraction_rules as rules
from pipeline.context_bundle import Card, ContextBundle, deaths_before
from pipeline.extract_claims import ExtractedClaim, extract_claims
from pipeline.judges import RULE_CONFIDENCE, judge_timeline
from pipeline.merge import apply_new_information
from pipeline.sentences import split_sentences

CHARACTERS = [{"ref": "c1", "name": "레온", "aliases": []}, {"ref": "c2", "name": "세린", "aliases": []}]


def _said(text):
    """(condition, presence) of each character the sentence names, by name."""
    registry = rules.Registry(CHARACTERS, [])
    [sentence] = split_sentences(text)
    mentions = registry.mentions(sentence.narration)
    return {
        m.subject.name: (
            rules.condition_of(sentence, m, mentions),
            rules.presence_of(sentence, m, mentions),
        )
        for m in mentions
    }


# --- death and presence in a sentence -----------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "레온은 결국 상처를 이기지 못하고 숨을 거두었다.",
        "레온은 칼에 찔려 죽고 말았다.",
        "레온이 전사했다.",
        "레온은 그 자리에서 사망했다.",
        "레온은 세린의 품에서 숨졌다.",
    ],
)
def test_a_death_the_sentence_says_of_its_subject_is_found(text):
    condition, presence = _said(text)["레온"]
    assert rules.is_death(condition) and presence == ""


@pytest.mark.parametrize(
    "text",
    [
        "세린은 레온이 죽었다고 말했다.",  # said by someone, not told
        "레온은 죽지 않았다.",
        "레온은 죽은 척했다.",
        "레온은 죽을 뻔했다.",
        "레온은 마치 죽었다.",
        "레온은 죽고 싶었다.",
    ],
)
def test_a_sentence_that_only_speaks_of_death_is_not_one(text):
    assert _said(text)["레온"][0] == ""


@pytest.mark.parametrize(
    "text",
    [
        "레온은 눈앞에서 동료가 죽었다.",
        "레온은 쓰러진 친구를 보고 그가 죽었다.",
        "레온은 눈앞에서 동료가 숨을 거두었다.",
    ],
)
def test_a_death_with_a_subject_of_its_own_is_not_the_sentences_subjects(text):
    assert _said(text)["레온"][0] == ""


@pytest.mark.parametrize(
    "text",
    [
        "레온은 피가 많이 나서 죽었다.",
        "레온은 어이없이 죽었다.",  # an adverb in -이, not a subject
        "레온은 일찍이 죽었다.",
        "레온은 꿈을 이루지 못한 채 죽었다.",  # 꿈 is not what the death is likened to
        "레온은 따듯한 품에서 숨을 거두었다.",
    ],
)
def test_a_death_is_still_the_subjects_with_a_verb_an_adverb_or_an_unrelated_word_before_it(text):
    condition, _ = _said(text)["레온"]
    assert rules.is_death(condition)


def test_a_dream_or_a_likeness_right_before_the_death_is_not_one():
    assert _said("레온은 꿈에서 죽었다.")["레온"][0] == ""


def test_another_subject_taking_over_leaves_the_death_to_it():
    said = _said("레온이 보는 앞에서 세린이 죽었다.")
    assert said["레온"] == ("", "")
    assert rules.is_death(said["세린"][0])


def test_coming_back_is_found():
    condition, _ = _said("레온은 다시 되살아났다.")["레온"]
    assert rules.is_revival(condition)


@pytest.mark.parametrize(
    "text",
    [
        "레온은 언데드가 되어 일어났다.",
        "레온은 언데드가 되었다.",
        "레온은 언데드로 다시 일어났다.",
        "네크로맨서가 레온을 되살렸다.",
        "마법사는 레온의 시체를 언데드로 만들었다.",
        "레온의 시체가 언데드가 되어 일어났다.",
        "언데드가 된 레온이 나타났다.",
    ],
)
def test_a_character_brought_back_as_the_undead_or_by_another_is_a_coming_back(text):
    condition, presence = _said(text)["레온"]
    assert rules.is_revival(condition) and not rules.is_death(condition) and presence == ""


@pytest.mark.parametrize(
    "text",
    [
        "레온은 다시 일어났다.",  # a fall and a getting up
        "의사는 레온을 살려냈다.",  # saved from dying
        "마법사는 레온을 되살리지 못했다.",
        "마법사는 레온을 되살리는 꿈을 꾸었다.",
        "레온이 보는 앞에서 좀비가 일어섰다.",  # the zombie's, not 레온's
        "레온은 병사를 언데드로 만들었다.",
    ],
)
def test_getting_up_again_or_a_failed_or_dreamed_revival_is_not_one(text):
    assert not rules.is_revival(_said(text)["레온"][0])


def test_the_one_who_brings_another_back_is_not_brought_back():
    said = _said("세린은 레온을 되살렸다.")
    assert said["세린"][0] == "" and rules.is_revival(said["레온"][0])


@pytest.mark.parametrize(
    "text",
    [
        "레온은 예전에 이곳에서 자랐다.",
        "레온은 세린의 무덤 앞에 섰다.",
        "세린은 죽은 레온을 기억했다.",
        "레온의 유령이 나타났다.",
        "레온은 전설로 남았다.",
        "레온은 유언장에 이렇게 적었다.",
        "레온은 그날 밤 성을 지켰다고 한다.",
    ],
)
def test_the_dead_remembered_mourned_or_seen_as_a_ghost_do_not_appear(text):
    assert all(presence == "" for _, presence in _said(text).values())


def test_what_is_recorded_of_a_coming_back_is_read_as_one_by_the_judgment():
    dead, back = uuid.uuid4(), uuid.uuid4()
    db = MagicMock()
    db.execute.return_value = [
        _history(dead, 3, {"condition": "숨을 거두었다"}),
        _history(dead, 5, {"condition": "되살렸다"}),
        _history(back, 3, {"condition": "전사했다"}),
        _history(back, 4, {"condition": "언데드가 된"}),
    ]
    assert deaths_before(db, uuid.uuid4(), 6, [dead, back]) == {}


def test_a_character_doing_something_is_there():
    assert _said("레온은 문을 열고 들어섰다.")["레온"] == ("", "문을 열고 들어섰다")


# --- extraction ----------------------------------------------------------------


def _extract(text, died=()):
    characters = [{**c, "died": "3화: 숨을 거두었다" if c["ref"] in died else None} for c in CHARACTERS]
    return extract_claims(
        uuid.uuid4(), text, characters, [], recognize=lambda texts: [[] for _ in texts], answer=lambda qs: [""] * len(qs)
    )


def test_a_death_is_a_condition_claim_whoever_it_is_of():
    [claim] = _extract("레온은 숨을 거두었다.").claims
    assert (claim.claim_type, claim.subject, claim.subject_ref) == ("appearance", "레온", "c1")
    assert claim.attributes == {"condition": "숨을 거두었다"}
    assert claim.evidence == "레온은 숨을 거두었다."


def test_presence_is_only_claimed_of_a_character_who_died_before():
    text = "레온은 문을 열고 들어섰다. 세린은 창밖을 바라보았다."
    assert _extract(text).claims == []
    [claim] = _extract(text, died={"c1"}).claims
    assert (claim.claim_type, claim.subject_ref, claim.attributes) == ("spacetime", "c1", {"presence": "문을 열고 들어섰다"})


# --- who died before this episode -----------------------------------------------


def _history(character_id, episode_index, state):
    return SimpleNamespace(character_id=character_id, episode_index=episode_index, state=state)


def test_the_death_is_the_latest_one_not_followed_by_a_coming_back():
    dead, back, alive = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db = MagicMock()
    db.execute.return_value = [
        _history(dead, 2, {"condition": "부상을 입었다"}),
        _history(dead, 3, {"condition": "숨을 거두었다"}),
        _history(dead, 4, {"hairstyle": "짧은 머리"}),
        _history(back, 2, {"condition": "전사했다"}),
        _history(back, 5, {"condition": "되살아났다"}),
        _history(alive, 1, {"condition": "부상을 입었다"}),
    ]
    assert deaths_before(db, uuid.uuid4(), 6, [dead, back, alive]) == {dead: "3화: 숨을 거두었다"}
    assert deaths_before(db, uuid.uuid4(), 6, []) == {}


# --- the judgment ---------------------------------------------------------------


def _card(died="3화: 숨을 거두었다"):
    return Card(kind="character", id=uuid.uuid4(), name="레온", attrs={}, sources={}, died=died)


def _claim(sentence, **attributes):
    return ExtractedClaim(
        claim_type="spacetime",
        subject_kind="character",
        subject="레온",
        text=sentence,
        evidence=sentence,
        attributes=attributes,
    )


def _bundle(*cards):
    return ContextBundle(episode_id=uuid.uuid4(), claim_cards=list(cards))


def test_a_character_shown_after_dying_is_flagged():
    card = _card()
    [flag] = judge_timeline([_claim("레온은 문을 열고 들어섰다.", presence="문을 열고 들어섰다")], _bundle(card))
    assert (flag.error_type, flag.attribute, flag.subject_id, flag.claim_index) == ("spacetime", "presence", card.id, 0)
    assert (flag.reference_text, flag.evidence_text, flag.confidence) == (
        "3화: 숨을 거두었다",
        "레온은 문을 열고 들어섰다.",
        RULE_CONFIDENCE,
    )


def test_one_flag_per_character_for_the_first_sentence_that_shows_it():
    card = _card()
    claims = [_claim("레온은 일어섰다.", presence="일어섰다"), _claim("레온은 웃었다.", presence="웃었다")]
    [flag] = judge_timeline(claims, _bundle(card, card))
    assert flag.claim_index == 0


def test_nothing_is_flagged_for_a_character_who_did_not_die_or_came_back_in_this_episode():
    shown = _claim("레온은 일어섰다.", presence="일어섰다")
    assert judge_timeline([shown], _bundle(_card(died=None))) == []
    card = _card()
    back = _claim("레온은 되살아났다.", condition="되살아났다")
    assert judge_timeline([shown, back], _bundle(card, card)) == []


def test_a_claim_with_nothing_shown_is_not_a_reappearance():
    card = _card()
    assert judge_timeline([_claim("레온의 눈은 푸르다.", eye_color="푸른색")], _bundle(card)) == []


# --- what the settings record ---------------------------------------------------


def test_a_death_outweighs_a_wound_before_it_in_the_episodes_state():
    character = Character(id=uuid.uuid4(), name="레온", fixed_attrs={}, attr_sources={})
    db = MagicMock()
    db.scalars.return_value = []
    claims = [
        ExtractedClaim(
            claim_type="appearance", subject_kind="character", subject="레온", text=t, attributes={"condition": v}
        )
        for t, v in (("레온은 부상을 입었다.", "부상을 입었다"), ("레온은 숨을 거두었다.", "숨을 거두었다"))
    ]
    apply_new_information(db, uuid.uuid4(), uuid.uuid4(), 3, "본문", claims, [character.id] * 2, [])
    [row] = [r for call in db.add_all.call_args_list for r in call.args[0] if hasattr(r, "character_id")]
    assert row.state == {"condition": "숨을 거두었다"}


def test_a_presence_or_state_flag_has_no_value_the_card_could_take():
    from api.episodes import _flag_value

    claim = SimpleNamespace(attributes={"presence": "일어섰다", "eye_color": "푸른색"})
    assert _flag_value(SimpleNamespace(attribute="presence"), claim) is None
    assert _flag_value(SimpleNamespace(attribute="eye_color"), claim) == "푸른색"
