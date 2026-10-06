"""One setting-card attribute value as a Korean sentence (design doc 7.2).

The judgment reads a card's value as a premise ("레온의 눈 색깔은 푸른색이다.",
pipeline/judges.py), and claim extraction restates what a manuscript sentence
says in the same shape (pipeline/extract_claims.py), for the sentences that
don't name their subject.
"""

import re

# What each character key is called in the sentence, with its topic particle.
CHARACTER_ATTR_TOPICS = {
    "age": "나이는",
    "eye_color": "눈 색깔은",
    "hair_color": "머리색은",
    "height": "신장은",
    "scars": "흉터는",
    "origin": "출신은",
}

# Syllables before a final 다 that make it a predicate ending ("습했다",
# "이다", "있다", "빛난다") rather than the end of a noun ("바다", "캐나다"); so does
# any syllable with a final consonant ("넓다", "깊다", "컸다"), which a noun
# in 다 doesn't have.
_PREDICATE_STEMS = set("이하한난있없는된진졌렸웠났랐갔왔섰쳤썼았었였했됐")
# A clause ending a value cut off a sentence can end in ("안개가 짙었고"); not 고 or 며
# alone, which end nouns too ("창고").
_CONNECTIVE = re.compile(r"(?:[았었였했겠]고|지만|는데|은데|면서|으며|니까)$")


def _is_predicate(value: str) -> bool:
    if _CONNECTIVE.search(value):
        return True
    before = value[-2:-1]
    return value.endswith("다") and (
        before in _PREDICATE_STEMS or ("가" <= before <= "힣" and (ord(before) - ord("가")) % 28 != 0)
    )


def as_statement(value: str) -> str:
    # "푸른색" -> "푸른색이다."; a value that's already a sentence (ends in a
    # predicate or punctuation) is kept, with a period.
    value = value.rstrip()
    if value.endswith((".", "!", "?", "…")):
        return value
    if _is_predicate(value):
        return f"{value}."
    return f"{value}이다."


def topic_particle(word: str) -> str:
    # 은 after a final consonant, 는 after a vowel; 은 when the word doesn't
    # end in a Hangul syllable (digits, Latin).
    last = word.rstrip()[-1:]
    if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 == 0:
        return "는"
    return "은"


def character_statement(name: str, attribute: str, value: str) -> str:
    return f"{name}의 {CHARACTER_ATTR_TOPICS[attribute]} {as_statement(value)}"


def location_statement(name: str, value: str) -> str:
    # A location's features read as what the place is ("검은 숲은 ...이다"), or, where the
    # value is what a sentence says of it ("한없이 넓다", "안개가 짙었고"), as that.
    return f"{name}{topic_particle(name)} {as_statement(value)}"
