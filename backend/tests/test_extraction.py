"""Claim extraction without a model (design doc 7.1.1): the sentence splitting,
name finding, cues and ownership rules, and the extractor run with stand-ins
for the NER and QA models."""

import uuid

from infra.span_inference import NamedEntity
from pipeline import extraction_rules as rules
from pipeline.extract_claims import extract_claims
from pipeline.sentences import MAX_SENTENCE_CHARS, split_sentences

CHARACTERS = [
    {"ref": "c1", "name": "레온", "aliases": ["레온하트", "붉은 늑대"]},
    {"ref": "c2", "name": "세린", "aliases": []},
    {"ref": "c3", "name": "김철수", "aliases": ["철수형"]},
    {"ref": "c4", "name": "김철수", "aliases": ["철수오빠"]},
]
LOCATIONS = ["검은 숲"]


def _run(text, answers=None, entities=None, characters=None):
    """extract_claims with the models stood in for: answers maps a question to
    its answer, entities a sentence's narration (stripped) to its NamedEntitys."""
    answers = answers or {}
    entities = entities or {}

    def recognize(texts):
        return [entities.get(text.strip(), []) for text in texts]

    def answer(questions):
        return [answers.get(question, "") for question, _ in questions]

    return extract_claims(uuid.uuid4(), text, characters or CHARACTERS, LOCATIONS, recognize=recognize, answer=answer)


# --- sentences ---------------------------------------------------------------


def test_a_quote_stays_in_its_sentence_and_is_blanked_in_the_narration():
    [sentence] = split_sentences('"세린, 여기서 기다려." 레온이 낮게 말했다.')
    assert sentence.text == '"세린, 여기서 기다려." 레온이 낮게 말했다.'
    assert sentence.narration.strip() == "레온이 낮게 말했다."
    assert len(sentence.narration) == len(sentence.text)


def test_sentences_end_at_punctuation_outside_quotes_and_at_line_breaks():
    sentences = split_sentences('그는 웃었다. "안녕. 반가워." 그녀가 말했다.\n\n다음 줄')
    assert [s.text for s in sentences] == ["그는 웃었다.", '"안녕. 반가워." 그녀가 말했다.', "다음 줄"]


def test_a_decimal_point_is_not_a_sentence_end():
    assert len(split_sentences("키는 1.8미터였다.")) == 1


def test_a_very_long_sentence_is_cut_at_a_comma():
    text = ("가" * 100 + ", ") * 4 + "끝."
    parts = split_sentences(text)
    assert len(parts) > 1
    assert all(len(part.text) <= MAX_SENTENCE_CHARS for part in parts)


def test_a_long_quote_cut_at_a_comma_stays_dialogue_and_its_narration_stays_narration():
    text = '"' + "가나다, " * 80 + '" 세린이 말했다.'
    sentences = split_sentences(text)
    assert len(sentences) > 1
    assert all(len(s.text) == len(s.narration) for s in sentences)
    assert "".join(s.narration for s in sentences).split() == ["세린이", "말했다."]


# --- names -------------------------------------------------------------------


def test_registered_names_and_aliases_are_found_with_the_refs_of_their_cards():
    registry = rules.Registry(CHARACTERS, LOCATIONS)
    found = registry.mentions("붉은 늑대는 검은 숲에서 세린을 만났다.")
    assert [(m.subject.name, m.subject.ref, m.topic) for m in found] == [
        ("레온", "c1", True),
        ("검은 숲", None, False),
        ("세린", "c2", False),
    ]


def test_a_name_that_fits_several_characters_is_unlinked_and_an_alias_picks_one():
    registry = rules.Registry(CHARACTERS, LOCATIONS)
    [by_name] = registry.mentions("김철수가 왔다.")
    assert by_name.subject.ref is None and by_name.subject.name == "김철수"
    [by_alias] = registry.mentions("철수형이 왔다.")
    assert by_alias.subject.ref == "c3"


def test_a_name_at_the_very_end_of_a_line_is_not_a_topic():
    registry = rules.Registry(CHARACTERS, LOCATIONS)
    assert [m.topic for m in registry.mentions("검은 숲")] == [False]
    assert [m.topic for m in registry.mentions("검은 숲은")] == [True]


def test_a_name_followed_by_the_copula_is_not_a_topic():
    registry = rules.Registry(CHARACTERS, LOCATIONS)
    assert [m.topic for m in registry.mentions("그곳은 검은 숲이었다.")] == [False]
    assert [m.topic for m in registry.mentions("검은 숲이 어두웠다.")] == [True]


def test_a_name_is_not_found_at_the_start_of_a_longer_word():
    registry = rules.Registry([{"ref": "c1", "name": "하늘", "aliases": []}, *CHARACTERS], [])
    assert registry.mentions("하늘빛 눈동자와 보라색 머리") == []
    assert registry.mentions("레온하르트는 웃었다") == []
    for text in ("하늘은 웃었다.", "하늘이었다.", "하늘에게 말했다.", "하늘아, 와."):
        assert [m.subject.ref for m in registry.mentions(text)] == ["c1"], text


def test_a_name_inside_another_word_is_not_a_mention():
    assert rules.Registry(CHARACTERS, LOCATIONS).mentions("아레온 마을") == []


def test_particles_that_cant_end_a_name_come_off_and_the_others_only_when_the_name_is_known():
    assert rules.split_particle("라일라는", set()) == ("라일라", "는")
    assert rules.split_particle("벨로스 성의", set()) == ("벨로스 성", "의")
    assert rules.split_particle("하윤아", set()) == ("하윤아", "")
    assert rules.split_particle("하윤아", {"하윤"}) == ("하윤", "아")
    assert rules.split_particle("서하은", set()) == ("서하은", "")


# --- cues --------------------------------------------------------------------


def _attributes(text):
    return {hit.attribute.key for hit in rules.cue_hits(text)}


def test_an_eye_or_hair_cue_needs_a_color_in_the_clause():
    assert _attributes("레온의 눈동자는 푸른색이었다.") == {"eye_color"}
    assert _attributes("레온의 눈동자가 흔들렸다.") == set()
    assert _attributes("눈이 내렸다.") == set()
    assert _attributes("세린의 은빛 머리카락이 흩날렸다.") == {"hair_color"}
    assert _attributes("세린의 긴 머리가 흩날렸다.") == set()


def test_the_other_cues():
    assert _attributes("그는 스물세 살이었다.") == {"age"}
    assert _attributes("그는 살았다.") == set()
    assert _attributes("그녀는 부산 출신이었다.") == {"origin"}
    assert _attributes("그의 키가 컸다.") == {"height"}
    assert _attributes("그의 신장은 180센티였다.") == {"height"}


def test_a_distance_or_a_shop_is_not_a_height():
    assert _attributes("그는 30cm 떨어진 곳에 섰다.") == set()
    assert _attributes("신장개업한 가게였다.") == set()
    height = next(a for a in rules.ATTRIBUTES if a.key == "height")
    assert rules.value_of(height, "180센티", "신장은 180센티였다") == "180센티"
    assert rules.value_of(height, "컸다", "키가 컸다") == "컸다"
    assert rules.value_of(height, "떨어진", "키가 떨어진") == ""
    assert _attributes("오른손에 화상 자국이 있었다.") == {"scars"}


def test_the_color_has_to_be_next_to_the_eye_or_hair():
    assert _attributes("검은 옷을 입은 그는 머리를 숙였다.") == set()
    assert _attributes("검은 숲에서 그의 눈이 흔들렸다.") == set()
    assert _attributes("그의 눈을 똑바로 보라고 말했다.") == set()
    assert _attributes("레온의 길고 푸른 눈이 번뜩였다.") == {"eye_color"}
    assert _attributes("세린의 머리카락은 은빛이었다.") == {"hair_color"}
    assert _attributes("그는 금발을 쓸어 넘겼다.") == {"hair_color"}
    assert _attributes("눈동자는 보라색이었다.") == {"eye_color"}


def test_an_idiom_with_eye_or_head_is_not_a_cue():
    assert _attributes("눈에 띄는 붉은 머리카락이 흔들렸다.") == {"hair_color"}
    assert _attributes("눈을 뜨자 검은 연기가 피어올랐다.") == set()
    assert _attributes("그는 검은 머리를 숙였다.") == {"hair_color"}
    assert _attributes("머리를 숙이자 검은 그림자가 드리웠다.") == set()
    assert _attributes("푸른 눈을 가진 소녀였다.") == {"eye_color"}
    assert _attributes("그는 눈동자를 붉게 빛냈다.") == {"eye_color"}
    assert _attributes("눈은 푸른색이었다.") == {"eye_color"}


def test_snow_is_not_an_eye():
    assert _attributes("레온은 하얀 눈이 내리는 거리를 걸었다.") == set()
    assert _attributes("하얀 눈이 쌓인 길이었다.") == set()
    assert _attributes("그의 눈이 푸르게 빛났다.") == {"eye_color"}
    assert _attributes("눈동자가 하얀 눈처럼 맑았다.") == {"eye_color"}


def test_footprints_are_not_scars():
    assert _attributes("레온의 발자국이 눈 위에 남았다.") == set()
    assert _attributes("뺨에 칼자국이 있었다.") == {"scars"}
    assert _attributes("손등에 화상 자국이 있었다.") == {"scars"}


def test_an_age_is_a_number_not_a_word_that_starts_with_one():
    assert _attributes("열심히 살았다.") == set()
    assert _attributes("그는 열일곱 살이었다.") == {"age"}
    assert _attributes("여섯 살 때의 일이었다.") == {"age"}
    assert _attributes("열 살 위의 형이었다.") == {"age"}
    age = next(a for a in rules.ATTRIBUTES if a.key == "age")
    assert rules.value_of(age, "열심히 살", "열심히 살았다") == ""


def test_the_cues_in_separate_clauses_are_kept_apart():
    [eye, age] = sorted(rules.cue_hits("눈은 푸르렀고, 나이는 17살이었다."), key=lambda hit: hit.start)
    assert eye.attribute.key == "eye_color" and age.attribute.key == "age"
    assert eye.clause != age.clause


def test_an_answer_is_cleaned_to_the_value():
    eye = next(a for a in rules.ATTRIBUTES if a.key == "eye_color")
    age = next(a for a in rules.ATTRIBUTES if a.key == "age")
    assert rules.value_of(eye, "푸른 눈", "레온의 푸른 눈이 번뜩였다") == "푸른"
    assert rules.value_of(eye, "붉", "그의 눈이 붉게 빛났다") == "붉게"
    assert rules.value_of(eye, "번뜩였다", "눈동자가 푸른색으로 번뜩였다") == ""
    assert rules.value_of(age, "스물세 살", "스물세 살의 그녀는") == "스물세 살"
    assert rules.value_of(age, "그녀", "스물세 살의 그녀는") == ""


# --- the extractor -----------------------------------------------------------


def test_a_claim_about_a_registered_character_carries_its_ref_and_the_sentence():
    extraction = _run("레온의 눈동자는 푸른색이었다.", {"레온의 눈 색깔은?": "푸른색"})
    [claim] = extraction.claims
    assert (claim.claim_type, claim.subject_kind, claim.subject, claim.subject_ref) == (
        "appearance",
        "character",
        "레온",
        "c1",
    )
    assert claim.attributes == {"eye_color": "푸른색"}
    assert claim.evidence == "레온의 눈동자는 푸른색이었다."
    assert claim.text == "레온의 눈 색깔은 푸른색이다."


def test_an_alias_makes_a_claim_about_the_card_under_its_name():
    # The question names the alias the sentence uses: the QA model can't answer about someone the sentence doesn't.
    [claim] = _run("붉은 늑대의 눈동자는 푸른색이었다.", {"붉은 늑대의 눈 색깔은?": "푸른색"}).claims
    assert (claim.subject, claim.subject_ref) == ("레온", "c1")


def test_nothing_is_asked_of_a_sentence_without_a_cue_and_a_no_answer_makes_no_claim():
    assert _run("레온은 문을 열었다.").claims == []
    assert _run("레온의 눈동자가 흔들렸다.", {}).claims == []


def test_dialogue_is_not_read_for_claims():
    text = '"레온의 눈동자는 푸른색이야." 세린이 말했다.'
    assert _run(text, {"레온의 눈 색깔은?": "푸른색", "세린의 눈 색깔은?": "푸른색"}).claims == []


def test_a_pronoun_goes_to_the_one_character_the_sentence_before_names():
    text = "레온은 검을 뽑았다. 그의 눈이 붉게 빛났다."
    [claim] = _run(text, {"레온의 눈 색깔은?": "붉게"}).claims
    assert (claim.subject, claim.subject_ref, claim.evidence) == ("레온", "c1", "그의 눈이 붉게 빛났다.")


def test_a_pronoun_early_in_the_sentence_counts_even_when_something_comes_before_it():
    text = "세린은 고개를 끄덕였다. 스물세 살의 그녀는 부산에서 올라온 상인의 딸이었다."
    answers = {"세린의 나이는?": "스물세 살", "세린의 출신은?": "부산"}
    [claim] = _run(text, answers).claims
    assert (claim.subject, claim.attributes) == ("세린", {"age": "스물세 살", "origin": "부산"})


def test_a_demonstrative_is_not_a_pronoun_but_that_fellow_is():
    before = "레온은 문을 열었다. "
    assert _run(before + "그 순간 열일곱 살이었다.", {"레온의 나이는?": "열일곱 살"}).claims == []
    [claim] = _run(before + "그 녀석의 눈이 붉게 빛났다.", {"레온의 눈 색깔은?": "붉게"}).claims
    assert claim.subject == "레온"
    [claim] = _run(before + "그 사내는 열일곱 살이었다.", {"레온의 나이는?": "열일곱 살"}).claims
    assert claim.subject == "레온"
    assert _run("세린은 그 녀석의 푸른 눈을 보았다.", {"세린의 눈 색깔은?": "푸른"}).claims == []


def test_a_pronoun_with_two_candidates_is_left_for_the_author_to_pick():
    text = "레온은 세린을 보았다. 그의 눈이 붉게 빛났다."
    [claim] = _run(text, EYES).claims
    assert (claim.subject, claim.subject_ref, claim.candidates) == ("", None, ["c1", "c2"])
    assert claim.attributes == {"eye_color": "붉게"}
    assert claim.evidence == "그의 눈이 붉게 빛났다."
    assert claim.text == "그의 눈 색깔은 붉게이다."


def test_a_pronoun_that_fits_a_card_the_author_has_not_made_is_not_offered():
    # 하윤 is only a name the NER model found: there's no card to pick.
    text = "레온은 하윤을 보았다. 그의 눈이 붉게 빛났다."
    entities = {"레온은 하윤을 보았다.": [NamedEntity(5, 7, "PS")]}
    assert _run(text, EYES, entities).claims == []


def test_a_name_two_characters_share_is_left_for_the_author_to_pick():
    [claim] = _run("김철수의 눈동자는 푸른색이었다.", {"김철수의 눈 색깔은?": "푸른색"}).claims
    assert (claim.subject, claim.subject_ref, claim.candidates) == ("김철수", None, ["c3", "c4"])


def test_a_cue_with_no_name_and_no_pronoun_goes_back_only_for_a_body_part():
    assert _run("레온은 문을 열었다. 여섯 살 때의 일이었다.", {"레온의 나이는?": "여섯 살"}).claims == []
    [claim] = _run("레온은 문을 열었다. 붉은 눈동자가 번뜩였다.", {"레온의 눈 색깔은?": "붉은"}).claims
    assert claim.subject == "레온"


def test_a_pronoun_possessor_in_a_sentence_that_names_someone_is_not_that_someone():
    answers = {"세린의 눈 색깔은?": "푸른"}
    assert _run("세린은 그의 푸른 눈을 보았다.", answers).claims == []
    [claim] = _run("세린은 자신의 푸른 눈을 보았다.", answers).claims
    assert claim.subject == "세린"


def test_somebody_elses_eyes_are_not_the_named_characters():
    text = "레온은 노인의 눈이 회색인 것을 보았다."
    assert _run(text, {"레온의 눈 색깔은?": "회색"}).claims == []


def test_the_possessor_in_front_of_the_cue_says_whose_it_is():
    text = "레온은 세린의 푸른 눈을 보았다."
    [claim] = _run(text, {"세린의 눈 색깔은?": "푸른"}).claims
    assert claim.subject == "세린"


def test_the_topic_owns_the_body_part_the_other_name_is_acted_on():
    answers = {"레온의 눈 색깔은?": "붉은", "세린의 눈 색깔은?": "붉은"}
    [claim] = _run("레온은 붉은 눈동자로 세린을 노려보았다.", answers).claims
    assert claim.subject == "레온"
    # Not where the cue comes after the other name, where the other is a co-subject, or
    # where two names are the same character.
    assert _run("레온은 세린을 붉은 눈동자로 노려보았다.", answers).claims == []
    assert _run("레온과 세린은 붉은 눈동자를 가졌다.", answers).claims == []
    # Another subject between the topic and the cue: the eyes are that one's.
    for text in (
        "레온은 웃었고 노인은 붉은 눈동자로 세린을 노려보았다.",
        "레온이 웃자 노인은 붉은 눈동자로 세린을 노려보았다.",
        "레온은 노인에게 다가갔고 사내가 붉은 눈동자로 세린을 노려보았다.",
    ):
        assert _run(text, answers).claims == []
    # A cue that describes the name after it is that name's.
    for text in (
        "레온은 붉은 눈의 세린을 노려보았다.",
        "레온은 눈이 붉은 사과 장수 세린을 바라보았다.",
        "레온은 붉은 눈동자 세린을 바라보았다.",
    ):
        [claim] = _run(text, answers).claims
        assert claim.subject == "세린"
    # ... but not a name joined by 와/과 to the noun it describes: "눈이 붉은 소녀들과 세린을".
    assert _run("레온은 눈이 붉은 소녀들과 세린을 바라보았다.", answers).claims == []
    # A bound noun or an adverb after an adnominal-looking word is not a modifier of the name.
    for text in (
        "레온은 붉은 눈동자로 온 힘을 다해 세린을 노려보았다.",
        "레온은 붉은 눈동자로 노려본 뒤 세린을 보았다.",
        "레온은 붉은 눈동자로 얼른 세린을 노려보았다.",
    ):
        [claim] = _run(text, answers).claims
        assert claim.subject == "레온"
    # A color word is no second subject.
    [claim] = _run("레온은 검은 눈동자로 세린을 노려보았다.", {"레온의 눈 색깔은?": "검은"}).claims
    assert claim.subject == "레온"
    # A bare cue noun or a compound describes the name after it.
    hair = {"레온의 머리색은?": "은발", "세린의 머리색은?": "은발", **answers}
    [claim] = _run("레온은 은발 소녀 세린을 바라보았다.", hair).claims
    assert (claim.subject, claim.attributes) == ("세린", {"hair_color": "은발"})
    [claim] = _run("레온은 흉터투성이 사내 세린을 바라보았다.", {"세린의 흉터는?": "흉터투성이"}).claims
    assert claim.subject == "세린"
    # A person not registered, described, is nobody's of the registered: not the topic's.
    scars = {"레온의 흉터는?": "흉터투성이", **hair}
    for text in (
        "레온은 붉은 눈의 노인을 노려보았다.",
        "레온은 은발 소녀를 바라보았다.",
        "레온은 흉터투성이 사내를 바라보았다.",
        "레온은 눈이 붉은 소녀에게 다가갔다.",
        "레온은 검은 눈의 여관 주인에게 말을 걸었다.",
    ):
        assert _run(text, scars).claims == []
    assert _run("레온은 스무 살의 청년을 만났다.", {"레온의 나이는?": "스무 살"}).claims == []
    # ... but a person the topic is, or what it does with, is the topic's.
    for text in ("세린은 은발 소녀였다.", "세린은 은발의 소녀로 자랐다.", "세린은 은발 머리카락을 쓸어 넘겼다."):
        [claim] = _run(text, hair).claims
        assert claim.subject == "세린"
    # The QA model's answer is no value where it is a name: "세린의 흉터는?" answered "레온".
    assert _run("레온은 흉터투성이 사내 세린을 바라보았다.", {"세린의 흉터는?": "레온"}).claims == []
    assert _run("레온은 물러섰고 적은 붉은 눈동자로 세린을 노려보았다.", answers).claims == []
    # The cue as what the topic does something to: the rules can't tell whose it is.
    for text in (
        "레온은 붉은 머리카락을 쓰다듬으며 세린에게 속삭였다.",
        "레온은 붉은 눈동자를 가만히 들여다보다 세린을 끌어안았다.",
    ):
        assert _run(text, {"레온의 머리 색깔은?": "붉은", **answers}).claims == []
    # "한 번", "순간" are adverbs, not an adnominal of the other.
    for text in ("레온은 붉은 눈동자로 한 번 세린을 노려보았다.", "레온은 붉은 눈동자로 순간 세린을 노려보았다."):
        [claim] = _run(text, answers).claims
        assert claim.subject == "레온"
    # Shown or treated, the rules can't tell whose scar it is: "세린은 오른손의 흉터를 레온에게
    # 보여주었다" (the one showing it) reads like "흉터를 치료해 주며 세린에게" (the one treated)
    # until the verb's meaning is known, so both are refused. The eval set's gold has a reader's
    # answer for them (p96, p70) and counts them as misses.
    scar = {"레온의 흉터는?": "흉터", "세린의 흉터는?": "흉터"}
    assert _run("세린은 오른손의 흉터를 레온에게 보여주었다.", scar).claims == []
    assert _run("레온은 흉터를 조심스레 치료해 주며 세린에게 말했다.", scar).claims == []
    # Only for the body: an age in such a sentence is nobody's.
    assert _run("레온은 스무 살 때 세린을 만났다.", {"레온의 나이는?": "스무 살", "세린의 나이는?": "스무 살"}).claims == []
    # Only the words right before the name can modify it: an ordinary word ending in ㄴ/ㄹ
    # earlier in the sentence does not.
    for text in ("레온은 붉은 눈동자로 문 앞에서 세린을 노려보았다.", "레온은 붉은 눈동자로 오랜 침묵 끝에 세린을 노려보았다."):
        [claim] = _run(text, answers).claims
        assert claim.subject == "레온"
    # A place or possession of the other name is not a description of it.
    [claim] = _run("레온은 붉은 눈동자로 탑 위의 세린을 노려보았다.", answers).claims
    assert claim.subject == "레온"
    # A title or role between the modifier and the name, or the cue as an adnominal of the
    # other: the other's, never the topic's.
    for text in (
        "레온은 눈이 푸른 소녀 세린을 바라보았다.",
        "레온은 붉은 눈의 마녀 세린을 바라보았다.",
        "레온은 눈이 푸른 세린을 바라보았다.",
        "레온은 붉은 눈의 젊은 세린을 바라보았다.",
    ):
        both = {"레온의 눈 색깔은?": "푸른" if "푸른" in text else "붉은", "세린의 눈 색깔은?": "푸른" if "푸른" in text else "붉은"}
        [claim] = _run(text, both).claims
        assert claim.subject == "세린"
    # The cue as a relative clause's object ("붉은 눈을 한 세린을"): the rules don't read it.
    assert _run("레온은 붉은 눈을 한 세린을 바라보았다.", answers).claims == []


def test_a_body_part_is_no_possessor():
    [claim] = _run("레온은 오른손의 흉터를 문질렀다.", {"레온의 흉터는?": "흉터"}).claims
    assert claim.subject == "레온"
    # A person who happens to end in a body part's syllable is still somebody else.
    assert _run("레온은 후손의 흉터를 보았다.", {"레온의 흉터는?": "흉터"}).claims == []
    assert _run("레온은 노인의 오른손의 흉터를 보았다.", {"레온의 흉터는?": "흉터"}).claims == []
    # A pronoun subject is not a "그 + noun".
    [claim] = _run("레온은 문을 열었다. 그는 오른손의 흉터를 문질렀다.", {"레온의 흉터는?": "흉터"}).claims
    assert claim.subject == "레온"
    # Body words that are not on the short list of hands and arms.
    for part in ("눈가", "머리", "입술", "발목"):
        [claim] = _run(f"레온은 {part}의 흉터를 문질렀다.", {"레온의 흉터는?": "흉터"}).claims
        assert claim.subject == "레온"
    # "그 순간" is not a "그 + body part".
    [claim] = _run("레온은 그 순간 오른손의 흉터를 문질렀다.", {"레온의 흉터는?": "흉터"}).claims
    assert claim.subject == "레온"
    # A subject the text doesn't register: its body part is not the last registered character's.
    shown = {"레온의 흉터는?": "흉터"}
    assert _run("레온은 노인에게 다가갔다. 노인은 오른손의 흉터를 보였다.", shown).claims == []
    assert _run("레온은 노인을 보았다. 오른손의 흉터가 선명했다.", shown).claims == []
    # The registered topic of an earlier clause is not the subject of this one.
    assert _run("레온이 다가가자 노인은 오른손의 흉터를 보였다.", shown).claims == []
    assert _run("레온은 문을 열었고 노인은 오른손의 흉터를 보였다.", shown).claims == []
    # ... unless a pronoun names the subject.
    assert _run("레온은 문을 열었다. 그는 오른손의 흉터를 문질렀다.", shown).claims != []
    # Somebody else the topic acts on ahead of the body part: that one's.
    for text in ("레온은 노인을 부축하며 어깨의 흉터를 살폈다.", "레온은 노인의 손을 잡고 오른손의 흉터를 살폈다."):
        assert _run(text, shown).claims == []
    # 적은 is often 적 "the enemy" with 은, another subject.
    assert _run("레온은 물러섰고 적은 오른손의 흉터를 드러냈다.", shown).claims == []
    # The registered name is the subject of a clause under an unregistered topic.
    for text in (
        "노인은 레온이 오자 오른손의 흉터를 보였다.",
        "노인은 레온이 묻자 오른손의 흉터를 보였다.",
        "노인은, 레온이 다가오자 오른손의 흉터를 보였다.",
    ):
        assert _run(text, shown).claims == []
    # The one named character is the one shown the hand, not its owner.
    assert _run("노인은 레온에게 오른손의 흉터를 보여주었다.", {"레온의 흉터는?": "흉터"}).claims == []
    # "그 손의", "그 오른쪽 어깨의": somebody else's, mentioned before.
    assert _run("레온은 노인을 보았다. 그 오른쪽 어깨의 흉터가 선명했다.", {"레온의 흉터는?": "흉터"}).claims == []
    # "그 손의": somebody else's hand, mentioned before.
    assert _run("레온은 노인의 손을 잡고 그 손의 흉터를 보았다.", {"레온의 흉터는?": "흉터"}).claims == []
    # A word that is a body part as often as something else is not one.
    assert _run("레온은 배의 선체에 난 상흔을 만졌다.", {"레온의 흉터는?": "상흔"}).claims == []
    # Another subject marked by 도, 만, 께서 is not 레온.
    for subject in ("노인도", "노인만", "노인께서"):
        assert _run(f"레온은 웃었고 {subject} 오른손의 흉터를 보였다.", shown).claims == []
    # ... but a conjunction that ends in one is no subject.
    for text in ("레온은 웃었지만 오른손의 흉터를 숨겼다.", "레온은 그래도 오른손의 흉터를 숨겼다."):
        [claim] = _run(text, shown).claims
        assert (claim.subject, set(claim.attributes)) == ("레온", {"scars"})
    # ... nor a modifier ("깊은", "떨리는"), an adverb or a time.
    for text in (
        "레온은 깊은 숨을 쉬며 오른손의 흉터를 문질렀다.",
        "레온은 떨리는 손으로 오른손의 흉터를 문질렀다.",
        "레온은 오늘도 오른손의 흉터를 문질렀다.",
        "레온은 이번에도 오른손의 흉터를 문질렀다.",
        "레온은 말없이 오른손의 흉터를 문질렀다.",
        "레온은 작은 한숨과 함께 오른손의 흉터를 문질렀다.",
        "레온은 가까이 다가와 오른손의 흉터를 보였다.",
        "레온은 많은 사람들 앞에서 오른손의 흉터를 보였다.",
    ):
        [claim] = _run(text, shown).claims
        assert claim.subject == "레온"
    # A verb's connective or adnominal that ends like a subject's particle, told by its
    # part-of-speech tags: the topic's eyes.
    answers = {"레온의 눈 색깔은?": "붉은", "세린의 눈 색깔은?": "붉은", "카엘의 눈 색깔은?": "붉은"}
    for text in (
        "레온은 웃다가 붉은 눈동자로 세린을 노려보았다.",
        "레온은 고개를 돌리고는 붉은 눈동자로 세린을 노려보았다.",
        "레온은 빛나는 붉은 눈동자로 카엘을 노려보았다.",
    ):
        [claim] = _run(text, answers).claims
        assert claim.subject == "레온"
    # ... but a name with 는 is a subject: "마리는 붉은 눈동자로" is not 레온's. So is a word
    # the tagger reads as a verb or an adverb ("누군가는" -> 누구 + 이다, "한결만").
    for subject in ("마리는", "누군가는", "누군가가", "누군가도", "누군가만", "한결만"):
        assert _run(f"레온은 웃었고 {subject} 붉은 눈동자로 세린을 노려보았다.", answers).claims == []
    # ... but not a verb or an adjective made of a noun.
    for word in ("경멸하는", "힘없는", "당황했지만", "긴장해도", "의미있는", "침묵하면서도"):
        [claim] = _run(f"레온은 {word} 붉은 눈동자로 세린을 노려보았다.", answers).claims
        assert claim.subject == "레온"


def test_a_scar_s_value_names_the_mark_not_the_body_part():
    scars = next(a for a in rules.ATTRIBUTES if a.key == "scars")
    assert rules.value_of(scars, "왼팔", "왼팔의 상흔을 가렸다") == ""
    assert rules.value_of(scars, "작은 흉터", "작은 흉터가 있었다") == "작은 흉터"
    assert rules.value_of(scars, "길게 그어진", "뺨에 길게 그어진 상흔") == "길게 그어진"
    assert rules.value_of(scars, "오른쪽 어깨", "오른쪽 어깨의 상흔") == ""
    for part in ("발바닥", "정강이", "관자놀이", "이마 한가운데", "왼쪽 뺨 옆", "목 뒤", "미간", "귀 밑", "콧등"):
        assert rules.value_of(scars, part, f"{part}의 상흔") == ""
    assert rules.value_of(scars, "목", "목의 상흔") == ""
    for answer in ("왼쪽 눈 아래", "머리", "발목", "눈가", "입술"):
        assert rules.value_of(scars, answer, f"{answer}의 상흔") == "", answer
    for answer in ("왼팔.", "왼팔과 오른팔", "왼쪽 뺨과 이마", "뺨 위", "뺨 위에"):
        assert rules.value_of(scars, answer, f"{answer} 상흔") == "", answer
    for answer in ("왼팔은", "왼팔로", "왼팔에도", "뺨과", "왼팔으로"):
        assert rules.value_of(scars, answer, f"{answer} 상흔") == ""
    assert rules.value_of(scars, "양쪽 뺨", "양쪽 뺨의 상흔") == ""


def test_the_color_after_the_noun_is_counted_from_the_word_after_its_particle():
    assert _attributes("그의 눈이 어둠 속에서 붉게 번뜩였다.") == {"eye_color"}
    assert _attributes("그의 눈이 어둠 속에서 한참 붉게 번뜩였다.") == set()
    # The last word of the window only as a predicate, not the modifier of another noun.
    assert _attributes("그의 눈이 마주친 순간 붉은 노을이 졌다.") == set()
    # ... but a color noun in ㄹ ("은발") is no modifier.
    assert "hair_color" in _attributes("세린의 머리카락은 길고 탐스러운 은발")


def test_a_pronoun_looks_back_three_sentences():
    text = "레온은 문을 열었다. 바람이 불었다. 방은 어두웠다. 그의 눈이 붉게 빛났다."
    [claim] = _run(text, {"레온의 눈 색깔은?": "붉게", "그의 눈 색깔은?": "붉게"}).claims
    assert claim.subject == "레온"
    assert _run("레온은 문을 열었다. 바람이 불었다. 방은 어두웠다. 비가 왔다. 그의 눈이 붉게 빛났다.").claims == []


def test_the_third_sentence_back_is_looked_at_only_where_the_nearer_two_name_nobody():
    answers = {"레온의 눈 색깔은?": "붉은", "세린의 눈 색깔은?": "붉은"}
    [claim] = _run("레온은 문을 열었다. 바람이 불었다. 세린은 웃었다. 붉은 눈동자가 번뜩였다.", answers).claims
    assert claim.subject == "세린"


def test_one_claim_per_sentence_and_subject_holds_all_it_says():
    answers = {"세린의 나이는?": "스물세 살", "세린의 출신은?": "부산"}
    [claim] = _run("세린은 스물세 살이었고 부산 출신이었다.", answers).claims
    assert claim.attributes == {"age": "스물세 살", "origin": "부산"}


def test_a_name_only_the_ner_model_knows_becomes_a_subject_without_a_ref():
    text = "하윤의 눈동자가 푸른색이었다."
    entities = {text: [NamedEntity(0, 3, "PS")]}  # "하윤의": the particle comes with it
    [claim] = _run(text, {"하윤의 눈 색깔은?": "푸른색"}, entities).claims
    assert (claim.subject, claim.subject_ref) == ("하윤", None)


def test_a_place_the_sentence_is_about_gets_what_the_sentence_says_of_it():
    [claim] = _run("검은 숲은 늘 안개로 덮여 있었다.", {}).claims
    assert (claim.claim_type, claim.subject_kind, claim.subject) == ("location", "location", "검은 숲")
    assert claim.attributes == {"features": "늘 안개로 덮여 있었다"}
    assert claim.text == "검은 숲은 늘 안개로 덮여 있었다."


def test_only_the_first_clause_of_what_is_said_of_a_place_is_taken():
    [claim] = _run("검은 숲은 안개가 짙었고, 레온은 그곳을 지났다.", {}).claims
    assert claim.attributes == {"features": "안개가 짙었고"}


def test_what_is_done_to_something_or_with_somebody_is_not_a_place_s_features():
    for text in (
        "검은 숲은 병사들을 삼켰다.",
        "검은 숲은 레온이 지켜 왔다.",
        '검은 숲은 "위험하다"고 했다.',
        "검은 숲은 ‘저주받은 땅’이라 불렸다.",
    ):
        assert _run(text, {}).claims == []


def test_a_character_before_the_place_does_not_take_its_features_away():
    [claim] = _run("레온이 보기에 검은 숲은 늘 안개로 덮여 있었다.", {}).claims
    assert (claim.subject, claim.attributes) == ("검은 숲", {"features": "늘 안개로 덮여 있었다"})


def test_a_second_mention_of_a_place_is_tried_when_the_first_gives_nothing():
    [claim] = _run("검은 숲은 병사들을 삼켰다, 검은 숲은 늘 고요했다.", {}).claims
    assert claim.attributes == {"features": "늘 고요했다"}


def test_a_number_of_answers_that_does_not_match_the_questions_is_an_error():
    import pytest

    with pytest.raises(ValueError):
        extract_claims(
            uuid.uuid4(),
            "레온의 눈동자는 푸른색이었다.",
            CHARACTERS,
            LOCATIONS,
            recognize=lambda texts: [[] for _ in texts],
            answer=lambda questions: [],
        )


def test_what_a_sentence_says_of_a_place_is_stated_as_it_says_it():
    [claim] = _run("검은 숲은 안개가 짙었고, 레온은 그곳을 지났다.", {}).claims
    assert claim.text == "검은 숲은 안개가 짙었고."
    [claim] = _run("검은 숲은 한없이 넓다.", {}).claims
    assert claim.text == "검은 숲은 한없이 넓다."


def test_a_noun_ending_in_을_is_not_an_object():
    [claim] = _run("검은 숲은 마을 북쪽에 펼쳐져 있었다.", {}).claims
    assert claim.attributes == {"features": "마을 북쪽에 펼쳐져 있었다"}
    assert _run("검은 숲은 마을을 삼켰다.", {}).claims == []


def test_an_object_at_the_end_of_a_clause_is_an_object_too():
    assert _run("검은 숲은 병사들을, 삼켰다.", {}).claims == []


def test_only_a_topic_that_the_particle_ends_is_read():
    for text in ("검은 숲이지만 안개는 걷혔다.", "멀리 검은 숲이 보였다.", "눈앞에 검은 숲이 나타났다."):
        assert _run(text, {}).claims == []


def test_a_quote_in_another_clause_does_not_take_a_place_s_features_away():
    [claim] = _run('검은 숲은 안개가 짙었다, 레온은 "가자"고 말했다.', {}).claims
    assert claim.attributes == {"features": "안개가 짙었다"}


def test_a_pronoun_in_what_is_said_is_somebody_else_s_doing():
    assert _run("검은 숲은 그가 지켜 왔다.", {}).claims == []


def test_a_comma_in_a_number_does_not_end_the_clause():
    [claim] = _run("검은 숲은 둘레가 1,000리에 달했다.", {}).claims
    assert claim.attributes == {"features": "둘레가 1,000리에 달했다"}


def test_노을_is_not_an_object():
    [claim] = _run("검은 숲은 노을 속에 잠겼다.", {}).claims
    assert claim.attributes == {"features": "노을 속에 잠겼다"}


def test_what_is_said_of_a_second_place_is_not_the_first_one_s():
    text = "검은 숲은 크고 세이라는 작았다."
    start = text.index("세이라")
    entities = {text: [NamedEntity(start, start + 4, "LC")]}  # the particle comes with it
    claims = _run(text, {}, entities).claims
    assert [(c.subject, c.attributes) for c in claims] == [("세이라", {"features": "작았다"})]


def test_a_place_that_what_is_said_tells_by_is_not_another_topic():
    text = "검은 숲은 벨로스 성 북쪽에 펼쳐져 있었다."
    start = text.index("벨로스")
    entities = {text: [NamedEntity(start, start + 5, "LC")]}
    [claim] = _run(text, {}, entities).claims
    assert claim.subject == "검은 숲"
    assert claim.attributes == {"features": "벨로스 성 북쪽에 펼쳐져 있었다"}


def test_a_comma_after_a_number_still_ends_the_clause():
    def clauses(text):
        return [text[a:b].strip() for a, b in rules._clauses(text)]

    assert clauses("나이는 18, 눈은 푸른색이었다") == ["나이는 18", "눈은 푸른색이었다"]
    assert clauses("둘레가 1,000리에 달했다") == ["둘레가 1,000리에 달했다"]


def test_a_change_of_a_place_s_state_is_a_state_not_a_feature():
    [claim] = _run("검은 숲은 폐허가 되었다.", {}).claims
    assert (claim.subject_kind, claim.subject, claim.attributes) == ("location", "검은 숲", {"state": "폐허가 되었다"})
    [claim] = _run("검은 숲은 불타 사라졌다.", {}).claims
    assert claim.attributes == {"state": "불타 사라졌다"}


def test_a_place_that_is_described_and_then_changes_has_both():
    claims = _run("검은 숲은 늘 안개로 덮여 있었다. 몇 해가 지나 검은 숲은 무너져 내렸다.", {}).claims
    assert [c.attributes for c in claims] == [{"features": "늘 안개로 덮여 있었다"}, {"state": "무너져 내렸다"}]


def test_what_is_denied_or_only_a_role_is_a_feature_not_a_change_of_state():
    for text, feature in (
        ("검은 숲은 한 번도 함락된 적 없는 요새였다.", "한 번도 함락된 적 없는 요새였다"),
        ("검은 숲은 결코 무너지지 않았다.", "결코 무너지지 않았다"),
        ("검은 숲은 교역의 중심이 되었다.", "교역의 중심이 되었다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"features": feature}


def test_a_state_word_that_does_not_end_the_predicate_is_a_feature():
    for text, feature in (
        ("검은 숲은 오래전 몰락한 왕가의 거처였다.", "오래전 몰락한 왕가의 거처였다"),
        ("검은 숲은 잿더미 위에 세워진 도시였다.", "잿더미 위에 세워진 도시였다"),
        ("검은 숲은 안 무너졌다.", "안 무너졌다"),
        ("검은 숲은 무너질 리 없었다.", "무너질 리 없었다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"features": feature}


def test_a_change_of_state_is_one_even_with_a_noun_before_it():
    for text, state in (
        ("검은 숲은 연못이 말라붙어 폐허가 되었다.", "연못이 말라붙어 폐허가 되었다"),
        ("검은 숲은 폐허였다.", "폐허였다"),
        ("검은 숲은 몇 해 뒤 재건되었다.", "몇 해 뒤 재건되었다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"state": state}


def test_the_formal_past_is_not_a_noun_the_place_is():
    [claim] = _run("검은 숲은 폐허로 변하였다.", {}).claims
    assert claim.attributes == {"state": "폐허로 변하였다"}


def test_a_noun_안_is_not_a_denial():
    for text, state in (
        ("검은 숲은 숲 안 전체가 폐허가 되었다.", "숲 안 전체가 폐허가 되었다"),
        ("검은 숲은 불에 타 버렸다.", "불에 타 버렸다"),
        ("검은 숲은 황량해졌다.", "황량해졌다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"state": state}


def test_what_has_not_happened_is_not_a_change_of_state():
    for text, feature in (
        ("검은 숲은 금방 무너질 듯했다.", "금방 무너질 듯했다"),
        ("검은 숲은 하마터면 무너질 뻔했다.", "하마터면 무너질 뻔했다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"features": feature}


def test_a_state_a_verb_after_carries_is_a_state():
    for text, state in (
        ("검은 숲은 폐허가 되어 버렸다.", "폐허가 되어 버렸다"),
        ("검은 숲은 잿더미가 되어 있었다.", "잿더미가 되어 있었다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"state": state}


def test_a_likeness_or_a_wish_is_not_a_change_of_state():
    for text, feature in (
        ("검은 숲은 마치 폐허 같았다.", "마치 폐허 같았다"),
        ("검은 숲은 폐허나 다름없었다.", "폐허나 다름없었다"),
        ("검은 숲은 곧 함락되려 했다.", "곧 함락되려 했다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"features": feature}


def test_an_earlier_clause_does_not_veto_a_change_of_state():
    for text, state in (
        ("검은 숲은 병사들이 막으려 했으나 결국 함락되었다.", "병사들이 막으려 했으나 결국 함락되었다"),
        ("검은 숲은 꿈꾸던 땅이 폐허가 되었다.", "꿈꾸던 땅이 폐허가 되었다"),
        ("검은 숲은 결국 폐허가 되고 말았다.", "결국 폐허가 되고 말았다"),
        ("검은 숲은 불에 타 없어졌다.", "불에 타 없어졌다"),
        ("검은 숲은 화재로 전소되었다.", "화재로 전소되었다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"state": state}, text


def test_a_state_word_denied_by_the_words_after_it_is_still_a_feature():
    for text in ("검은 숲은 결코 무너지지 않았다.", "검은 숲은 마치 폐허 같았다.", "검은 숲은 금방 무너질 듯했다."):
        [claim] = _run(text, {}).claims
        assert list(claim.attributes) == ["features"], text


def test_what_did_not_happen_or_was_only_waited_for_is_not_a_state():
    for text in ("검은 숲은 끝내 재건되지 못했다.", "검은 숲은 재건될 날만 기다렸다.", "검은 숲은 폐허 근처에 있었다."):
        [claim] = _run(text, {}).claims
        assert list(claim.attributes) == ["features"], text


def test_more_ways_to_say_a_place_fell():
    for text, state in (
        ("검은 숲은 허물어졌다.", "허물어졌다"),
        ("검은 숲은 쓰러졌다.", "쓰러졌다"),
        ("검은 숲은 폐허가 된 지 오래였다.", "폐허가 된 지 오래였다"),
        ("검은 숲은 이미 잿더미가 된 뒤였다.", "이미 잿더미가 된 뒤였다"),
    ):
        [claim] = _run(text, {}).claims
        assert claim.attributes == {"state": state}, text


def test_a_place_only_mentioned_in_passing_is_not_asked_about():
    assert _run("레온은 검은 숲 입구에서 말을 멈췄다.", {"검은 숲의 특징은?": "입구"}).claims == []


# --- pronouns and gender ---------------------------------------------------------


def _pair(**overrides):
    """레온 and 세린, as the settings give them (a dict per card: gender, pronoun)."""
    leon = {"ref": "c1", "name": "레온", "aliases": [], "gender": "male", "pronoun": None}
    serin = {"ref": "c2", "name": "세린", "aliases": [], "gender": "female", "pronoun": None}
    leon.update(overrides.get("leon", {}))
    serin.update(overrides.get("serin", {}))
    return [leon, serin]


BOTH_NAMED = "레온은 세린을 보았다. "
EYES = {
    "레온의 눈 색깔은?": "붉게",
    "세린의 눈 색깔은?": "붉게",
    "그의 눈 색깔은?": "붉게",
    "그녀의 눈 색깔은?": "붉게",
}


def _subjects(text, characters):
    """Who each claim is about; "?" for one left for the author to pick."""
    return [claim.subject or "?" for claim in _run(text, EYES, characters=characters).claims]


def test_what_a_card_is_narrated_with_is_its_pronoun_or_what_its_gender_says():
    assert rules.effective_pronoun("male", None) == "he"
    assert rules.effective_pronoun("female", None) == "she"
    assert rules.effective_pronoun("unspecified", None) == "any"
    assert rules.effective_pronoun("female", "he") == "he"
    assert rules.effective_pronoun("male", "any") == "any"
    assert rules.effective_pronoun(None, None) == "any"


def test_a_pronoun_that_shows_gender_picks_among_two_candidates():
    assert _subjects(BOTH_NAMED + "그의 눈이 붉게 빛났다.", _pair()) == ["레온"]
    assert _subjects(BOTH_NAMED + "그녀의 눈이 붉게 빛났다.", _pair()) == ["세린"]
    assert _subjects(BOTH_NAMED + "그녀는 눈이 붉게 빛났다.", _pair()) == ["세린"]


def test_that_man_and_that_girl_show_gender_but_that_fellow_does_not():
    assert _subjects(BOTH_NAMED + "그 사내의 눈이 붉게 빛났다.", _pair()) == ["레온"]
    assert _subjects(BOTH_NAMED + "그 소녀의 눈이 붉게 빛났다.", _pair()) == ["세린"]
    assert _subjects(BOTH_NAMED + "그 녀석의 눈이 붉게 빛났다.", _pair()) == ["?"]


def test_cards_without_a_gender_answer_to_either_pronoun():
    unknown = _pair(leon={"gender": "unspecified"}, serin={"gender": "unspecified"})
    assert _subjects(BOTH_NAMED + "그의 눈이 붉게 빛났다.", unknown) == ["?"]
    # One of them known is enough to tell them apart, the other answers to either.
    half = _pair(leon={"gender": "unspecified"})
    assert _subjects(BOTH_NAMED + "그녀의 눈이 붉게 빛났다.", half) == ["?"]
    assert _subjects(BOTH_NAMED + "그의 눈이 붉게 빛났다.", half) == ["레온"]


def test_the_pronoun_a_card_is_narrated_with_beats_its_gender():
    # A woman living as a man, whom the narration calls 그.
    disguised = _pair(serin={"pronoun": "he"})
    assert _subjects(BOTH_NAMED + "그의 눈이 붉게 빛났다.", disguised) == ["?"]
    assert _subjects(BOTH_NAMED + "그녀의 눈이 붉게 빛났다.", disguised) == []
    only_she = _pair(leon={"gender": "male"}, serin={"gender": "female", "pronoun": "she"})
    assert _subjects(BOTH_NAMED + "그녀의 눈이 붉게 빛났다.", only_she) == ["세린"]
    # Narrated with either: stays a candidate for both pronouns.
    either = _pair(serin={"pronoun": "any"})
    assert _subjects(BOTH_NAMED + "그녀의 눈이 붉게 빛났다.", either) == ["세린"]
    assert _subjects(BOTH_NAMED + "그의 눈이 붉게 빛났다.", either) == ["?"]


def test_with_one_candidate_the_pronoun_is_not_held_against_it():
    assert _subjects("레온은 문을 열었다. 그녀의 눈이 붉게 빛났다.", _pair()) == ["레온"]
    assert _subjects("세린은 문을 열었다. 그의 눈이 붉게 빛났다.", _pair()) == ["세린"]


# --- what the question is asked over ---------------------------------------------


def _asked(text, characters=None):
    """The (question, context) pairs the QA model is given for a manuscript."""
    asked = []

    def answer(questions):
        asked.extend(questions)
        return [""] * len(questions)

    extract_claims(
        uuid.uuid4(),
        text,
        characters or CHARACTERS,
        LOCATIONS,
        recognize=lambda texts: [[] for _ in texts],
        answer=answer,
    )
    return asked


def test_a_pronoun_is_replaced_by_the_name_in_what_the_model_reads():
    assert (
        rules.name_for_pronoun("그녀의 은빛 머리카락이 바람에 흩날렸다", "세린")
        == "세린의 은빛 머리카락이 바람에 흩날렸다"
    )
    assert (
        rules.name_for_pronoun("그의 눈이 어둠 속에서 붉게 번뜩였다", "레온") == "레온의 눈이 어둠 속에서 붉게 번뜩였다"
    )
    assert rules.name_for_pronoun("그 녀석의 눈이 붉게 빛났다", "레온") == "레온의 눈이 붉게 빛났다"


def test_the_particle_after_the_name_takes_the_form_of_its_last_syllable():
    assert rules.name_for_pronoun("그는 스물아홉 살이었다", "카엘") == "카엘은 스물아홉 살이었다"
    assert rules.name_for_pronoun("그녀는 스물아홉 살이었다", "엘리제") == "엘리제는 스물아홉 살이었다"
    assert rules.name_for_pronoun("그녀가 웃었다", "세린") == "세린이 웃었다"
    assert rules.name_for_pronoun("그녀가 웃었다", "엘리제") == "엘리제가 웃었다"


def test_a_그_that_is_not_a_pronoun_is_left_alone():
    for clause in ("그 순간 눈이 붉게 빛났다", "그리고 눈이 푸르렀다", "그곳의 눈이 푸르렀다", "눈이 붉게 빛났다"):
        assert rules.name_for_pronoun(clause, "레온") == clause


def test_a_question_about_a_pronoun_is_asked_over_the_sentence_that_names_the_character():
    [(question, context)] = [
        pair
        for pair in _asked("세린은 열일곱 살이었다. 그녀의 은빛 머리카락이 바람에 흩날렸다.")
        if "머리색" in pair[0]
    ]
    assert question == "세린의 머리색은?"
    assert context == "세린은 열일곱 살이었다. 세린의 은빛 머리카락이 바람에 흩날렸다."


def test_a_clause_that_names_the_character_is_asked_over_as_it_is():
    [(question, context)] = _asked("레온의 눈동자는 푸른색이었다.")
    assert (question, context) == ("레온의 눈 색깔은?", "레온의 눈동자는 푸른색이었다.")


def test_a_pronoun_of_the_other_gender_is_not_replaced_by_the_name():
    clause = "그녀의 눈이 푸르게 빛났다"
    assert rules.name_for_pronoun(clause, "레온", "he") == clause
    assert rules.name_for_pronoun(clause, "세린", "she") == "세린의 눈이 푸르게 빛났다"
    assert rules.name_for_pronoun(clause, "레온", "any") == "레온의 눈이 푸르게 빛났다"
    assert rules.name_for_pronoun("그 녀석의 눈이 붉게 빛났다", "레온", "she") == "레온의 눈이 붉게 빛났다"


def test_a_name_earlier_in_the_sentence_is_read_over_with_the_clause():
    [(question, context)] = _asked("레온이 웃자 붉은 눈이 번뜩였다.")
    assert question == "레온의 눈 색깔은?"
    assert context == "레온이 웃자 붉은 눈이 번뜩였다."


def test_a_color_is_finished_from_the_clause_not_from_the_sentence_before():
    def answer(questions):
        return ["붉" for _ in questions]

    extraction = extract_claims(
        uuid.uuid4(),
        "레온은 붉은 망토를 둘렀다. 레온의 눈이 붉게 빛났다.",
        CHARACTERS,
        LOCATIONS,
        recognize=lambda texts: [[] for _ in texts],
        answer=answer,
    )
    assert [c.attributes.get("eye_color") for c in extraction.claims if "eye_color" in c.attributes] == ["붉게"]


def test_a_value_the_model_takes_from_the_sentence_before_is_dropped():
    extraction = extract_claims(
        uuid.uuid4(),
        "레온은 푸른 망토를 둘렀다. 그의 눈이 붉게 빛났다.",
        CHARACTERS,
        LOCATIONS,
        recognize=lambda texts: [[] for _ in texts],
        answer=lambda questions: ["푸른" for _ in questions],
    )
    assert not [c for c in extraction.claims if "eye_color" in c.attributes]


def test_the_pronoun_that_fits_the_character_is_replaced_even_after_one_that_does_not():
    assert (
        rules.name_for_pronoun("그녀는 웃었고 그의 눈이 붉게 빛났다", "레온", "he")
        == "그녀는 웃었고 레온의 눈이 붉게 빛났다"
    )
    assert rules.name_for_pronoun("그는 그녀의 눈을 보았다", "세린", "she") == "그는 세린의 눈을 보았다"


def test_a_pronoun_followed_by_punctuation_is_replaced():
    assert rules.name_for_pronoun("그녀는, 열일곱 살이었다", "세린") == "세린은, 열일곱 살이었다"
    assert rules.name_for_pronoun("붉은 눈의 그, 그의 눈이 번뜩였다", "레온") == "붉은 눈의 그, 레온의 눈이 번뜩였다"


def test_a_clause_about_the_other_gender_is_asked_over_the_clause_alone():
    [(_, context)] = _asked("레온은 문을 열었다. 그녀의 눈이 푸르게 빛났다.", _pair()[:1])
    assert context == "그녀의 눈이 푸르게 빛났다."


def test_그만_is_not_a_pronoun():
    assert rules.name_for_pronoun("그만 눈이 붉게 빛났다", "레온") == "그만 눈이 붉게 빛났다"
    assert rules.name_for_pronoun("그녀만 눈이 붉게 빛났다", "세린") == "세린만 눈이 붉게 빛났다"


def test_a_plural_pronoun_cut_by_the_window_is_not_a_singular_one():
    sentence = "어둠 속에서 바람이 불던 밤에는 그녀들은 눈이 붉게 빛났다."
    assert sentence.index("그녀들") == 18  # the window (20) ends between 그녀 and 들
    assert _subjects("세린은 문을 열었다. " + sentence, _pair()) == []


def test_a_name_earlier_in_the_sentence_is_asked_as_the_sentence_writes_it():
    [(question, context)] = _asked("레온하트가 웃었다, 붉은 눈이 번뜩였다.")
    assert question == "레온하트의 눈 색깔은?"
    assert context == "레온하트가 웃었다, 붉은 눈이 번뜩였다."
