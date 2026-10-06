"""One setting-card attribute value as a Korean sentence (design doc 7.2).

The judgment reads a card's value as a premise ("레온의 눈 색깔은 푸른색이다.",
pipeline/judges.py), and claim extraction restates what a manuscript sentence
says in the same shape (pipeline/extract_claims.py), for the sentences that
don't name their subject.
"""

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
# "이다", "있다", "빛난다") rather than the end of a noun ("바다", "캐나다").
_PREDICATE_STEMS = set("이하한난있없는된진졌렸웠났랐갔왔섰쳤썼았었였했됐")


def as_statement(value: str) -> str:
    # "푸른색" -> "푸른색이다."; a value that's already a sentence (ends in a
    # predicate or punctuation) is kept, with a period.
    value = value.rstrip()
    if value.endswith((".", "!", "?", "…")):
        return value
    if value.endswith("다") and value[-2:-1] in _PREDICATE_STEMS:
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
    # A location's features read as what the place is ("검은 숲은 ...이다").
    return f"{name}{topic_particle(name)} {as_statement(value)}"
