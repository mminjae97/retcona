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


def test_one_claim_per_sentence_and_subject_holds_all_it_says():
    answers = {"세린의 나이는?": "스물세 살", "세린의 출신은?": "부산"}
    [claim] = _run("세린은 스물세 살이었고 부산 출신이었다.", answers).claims
    assert claim.attributes == {"age": "스물세 살", "origin": "부산"}


def test_a_name_only_the_ner_model_knows_becomes_a_subject_without_a_ref():
    text = "하윤의 눈동자가 푸른색이었다."
    entities = {text: [NamedEntity(0, 3, "PS")]}  # "하윤의": the particle comes with it
    [claim] = _run(text, {"하윤의 눈 색깔은?": "푸른색"}, entities).claims
    assert (claim.subject, claim.subject_ref) == ("하윤", None)


def test_a_place_the_sentence_is_about_gets_its_features():
    [claim] = _run("검은 숲은 늘 안개로 덮여 있었다.", {"검은 숲의 특징은?": "안개로 덮여 있었다"}).claims
    assert (claim.claim_type, claim.subject_kind, claim.subject) == ("location", "location", "검은 숲")
    assert claim.attributes == {"features": "안개로 덮여 있었다"}


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
