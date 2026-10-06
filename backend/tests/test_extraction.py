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


def _run(text, answers=None, entities=None):
    """extract_claims with the models stood in for: answers maps a question to
    its answer, entities a sentence's narration (stripped) to its NamedEntitys."""
    answers = answers or {}
    entities = entities or {}

    def recognize(texts):
        return [entities.get(text.strip(), []) for text in texts]

    def answer(questions):
        return [answers.get(question, "") for question, _ in questions]

    return extract_claims(uuid.uuid4(), text, CHARACTERS, LOCATIONS, recognize=recognize, answer=answer)


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
    assert _attributes("오른손에 화상 자국이 있었다.") == {"scars"}


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
    [claim] = _run("붉은 늑대의 눈동자는 푸른색이었다.", {"레온의 눈 색깔은?": "푸른색"}).claims
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


def test_a_pronoun_with_two_candidates_is_left_alone():
    text = "레온은 세린을 보았다. 그의 눈이 붉게 빛났다."
    assert _run(text, {"레온의 눈 색깔은?": "붉게", "세린의 눈 색깔은?": "붉게"}).claims == []


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
