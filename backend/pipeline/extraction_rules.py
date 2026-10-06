"""The rules of claim extraction that need no model (design doc 7.1.1, steps 2,
3 and 5): which names a sentence mentions, which attribute a sentence has a cue
for, and whose attribute it is.

Cues are deliberately narrow. The QA model (ml/qa) answers "no answer" only
when it is sure, and on novel prose it has to be told to answer more often
(ml/qa/RESULTS.md); a sentence it's asked about should be one that states the
attribute, not one that merely has the word ("눈동자가 흔들렸다"). So an eye
or hair cue needs a color word in the clause, an age a number.

Whose it is: a possessor in front of the cue ("레온의 푸른 눈") says; a possessor
that isn't a known name ("노인의 눈") means someone else's, and the cue is
skipped; otherwise the one character the sentence names. A sentence naming no
character ("그의 눈이 붉게 빛났다", "붉은 눈동자가 번뜩였다") goes to the one
character the two sentences before it name, if there's exactly one — missing a
claim does less harm than holding it against the wrong card.
"""

import re
import unicodedata
from dataclasses import dataclass, field

from pipeline.sentences import Sentence


@dataclass(frozen=True)
class Subject:
    kind: str  # character | location
    name: str  # a registered card's name, or the name as the manuscript has it
    ref: str | None = None  # a known character's ref (pipeline/entities.py)
    # The pronoun the manuscript narrates a character with: he (그), she (그녀)
    # or any (not known, or either). Not part of who it is.
    pronoun: str = field(default="any", compare=False)
    # A name several characters share: their refs, for the author to pick from.
    candidates: tuple[str, ...] = field(default=(), compare=False)

    @property
    def key(self) -> tuple[str, str]:
        return self.kind, self.ref or normalize(self.name)


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    subject: Subject
    # Marked as the sentence's topic or subject (은/는/이/가): "검은 숲은 ..."
    topic: bool


def effective_pronoun(gender: str | None, pronoun: str | None) -> str:
    """The pronoun a card is narrated with: the one the author set, or what its
    gender says (a card with neither answers to either)."""
    if pronoun in ("he", "she", "any"):
        return pronoun
    return {"male": "he", "female": "she"}.get(gender or "", "any")


def normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


# --- Names -----------------------------------------------------------------

_NAME_BEFORE = r"(?<![0-9A-Za-z가-힣])"
# What can follow a name: not more of a word ("하늘빛 눈동자" isn't 하늘, nor
# "레온하르트" 레온), but a particle, an honorific or the copula after it.
_AFTER_NAME_PARTICLES = (
    "에게서|에게|에서|한테서|한테|께서|부터|까지|처럼|보다|조차|마저|밖에|으로|이랑|이었|이다|이라|이고|이며|이란|이야|이여|"
    "은|는|이|가|을|를|의|에|와|과|도|만|뿐|로|랑|께|아|야|여|님|씨|군|양|였"
)
_NAME_AFTER = rf"(?![A-Za-z0-9])(?=$|[^가-힣]|(?:{_AFTER_NAME_PARTICLES}))"
_TOPIC_PARTICLES = "은는이가"
_COPULAS = ("이다", "이었", "이라", "이고", "이며", "이란", "이야")


class Registry:
    """The novel's registered characters and locations, found in a sentence by
    their names and aliases."""

    def __init__(self, characters: list[dict], locations: list[str]) -> None:
        self._by_string: dict[str, dict[tuple[str, str], Subject]] = {}
        for character in characters:
            pronoun = effective_pronoun(character.get("gender"), character.get("pronoun"))
            subject = Subject("character", character["name"], character.get("ref"), pronoun)
            for string in [character["name"], *character.get("aliases", [])]:
                self._add(string, subject)
        for location in locations:
            self._add(location, Subject("location", location))
        strings = sorted(self._by_string, key=len, reverse=True)
        # Spaces inside a name match any run of whitespace.
        parts = [r"\s+".join(re.escape(word) for word in string.split()) for string in strings]
        self._pattern = (
            re.compile(f"{_NAME_BEFORE}(?:{'|'.join(parts)}){_NAME_AFTER}", re.IGNORECASE) if parts else None
        )

    def _add(self, string: str, subject: Subject) -> None:
        string = normalize(string)
        # One character is too common to read as a name.
        if len(string) >= 2:
            self._by_string.setdefault(string, {})[subject.key] = subject

    @property
    def strings(self) -> set[str]:
        return set(self._by_string)

    def resolve(self, text: str) -> Subject | None:
        """The subject a name or alias stands for. A string that fits several
        characters (namesakes) isn't told apart by context (7.1.1): it comes
        back unlinked, as the name alone; one that fits a character and a
        location is dropped."""
        candidates = list(self._by_string.get(normalize(text), {}).values())
        if len(candidates) == 1:
            return candidates[0]
        if candidates and all(subject.kind == "character" for subject in candidates):
            name = " ".join(unicodedata.normalize("NFC", text).split())
            return Subject("character", name, candidates=tuple(s.ref for s in candidates if s.ref))
        return None

    def mentions(self, narration: str) -> list[Mention]:
        if self._pattern is None:
            return []
        found = []
        for match in self._pattern.finditer(narration):
            subject = self.resolve(match.group())
            if subject is not None:
                after = narration[match.end() : match.end() + 1]
                # 이 of "이다"/"이었" is the copula ("그곳은 검은 숲이었다"), not a subject.
                copula = narration[match.end() : match.end() + 2] in _COPULAS
                topic = bool(after) and after in _TOPIC_PARTICLES and not copula
                found.append(Mention(match.start(), match.end(), subject, topic))
        return found


# KLUE-NER marks a name with the particle after it ("라일라는", "벨로스 성의")
# when the tokenizer joins them (ml/ner/README.md). Particles that don't end a
# name are taken off; those that can ("하윤아", "미나가") only when the name
# without it is known from somewhere else in the episode.
_SURE_PARTICLES = (
    "에게서", "한테서", "이라고", "에게", "한테", "께서", "에서", "으로", "부터", "까지", "처럼", "보다", "라고",
    "를", "는", "의", "을",
)  # fmt: skip
_UNSURE_PARTICLES = (
    "이여",
    "이랑",
    "랑",
    "이",
    "가",
    "은",
    "도",
    "만",
    "와",
    "과",
    "아",
    "야",
    "로",
)


def split_particle(surface: str, known: set[str]) -> tuple[str, str]:
    """(name, particle) of a name the recognizer returned; known: the names
    seen without a particle."""
    for particle in _SURE_PARTICLES:
        if surface.endswith(particle) and len(surface) - len(particle) >= 2:
            return surface[: -len(particle)], particle
    for particle in _UNSURE_PARTICLES:
        stem = surface[: -len(particle)]
        if surface.endswith(particle) and len(stem) >= 2 and normalize(stem) in known:
            return stem, particle
    return surface, ""


# --- Attribute cues ----------------------------------------------------------

_COLOR = (
    "푸른|푸르|파란|파랗|붉|빨간|빨갛|검은|검다|검게|검정|까만|까맣|칠흑|갈색|밤색|녹색|초록|연두|회색|잿빛|"
    "금빛|금색|금발|황금|은빛|은색|은발|백발|백색|하얀|하얗|새하얀|흰|하늘색|하늘빛|보랏빛|보라색|자색|"
    "에메랄드|사파이어|호박색|청색|청록|흑발|흑색|주황|노란|노랗|분홍|핑크"
)
COLOR_RE = re.compile(_COLOR)
# Native Korean numerals, tens and ones ("열일곱", "스물세", "여섯"), not just any
# word that starts with one ("열심히 살았다").
_NATIVE_NUMERAL = (
    r"(?:열|스물|스무|서른|마흔|쉰|예순|일흔|여든|아흔)(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)?"
    r"|(?<![가-힣])(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉)"
)
_AGE_UNIT = rf"(?:{_NATIVE_NUMERAL})\s?살(?!림)|\d+\s?살|\d+\s?세(?![기계상월금력우])"


@dataclass(frozen=True)
class Attribute:
    key: str  # a card attribute key (models/character.py)
    label: str  # in the question: "{name}의 {label}?", as ml/qa/eval/novel.jsonl asks
    noun: re.Pattern
    # a color word in the clause, and in the answer
    needs_color: bool = False
    # what an answer has to look like
    value: re.Pattern | None = None
    # Rules a clause out where the noun is the weak kind (not the named group
    # "strong"): 눈 is an eye, or snow.
    unless: re.Pattern | None = None


ATTRIBUTES = (
    Attribute(
        "eye_color",
        "눈 색깔은",
        re.compile(r"(?P<strong>눈동자|홍채)|(?<![가-힣])눈(?=[이은을의도에])"),
        needs_color=True,
        unless=re.compile(r"내리|내려|내렸|쌓|녹아|녹는|녹았|날리|날렸|덮인|덮여|덮었|펑펑|눈보라|눈송이|눈발"),
    ),
    Attribute(
        "hair_color",
        "머리색은",
        re.compile(r"머리카락|머리색|머릿결|(?<![가-힣])머리(?=[가는를도의])|[금은백흑]발"),
        needs_color=True,
    ),
    Attribute(
        "age",
        "나이는",
        re.compile(_AGE_UNIT),
        value=re.compile(rf"\d|{_AGE_UNIT}"),
    ),
    Attribute(
        "height",
        "키는",
        # A bare "30cm" is any distance; it's a height only as the answer to 키 / 신장.
        re.compile(r"(?<![가-힣])키(?=[가는도를])|신장(?=[이가은는을를의도])"),
        value=re.compile(r"\d|센티|미터|크|컸|큰|작|장신|단신|훤칠|건장|왜소|높|낮"),
    ),
    Attribute("scars", "흉터는", re.compile(r"흉터|상흔|(?<![발손물퀴])자국")),
    Attribute(
        "origin",
        "출신은",
        re.compile(r"출신|고향|태생|[가-힣]에서\s*(?:올라온|내려온|올라왔|내려왔|태어났|태어난)"),
    ),
)


def features_of(sentence: Sentence, mention: Mention, others: list[Mention]) -> str:
    """What the sentence says of a place it is about ("검은 숲은 늘 안개로 덮여 있었다"
    -> "늘 안개로 덮여 있었다"): what follows its topic particle, up to a comma, "" where
    that isn't a description of the place. "특징은?" is a poor question for the QA model
    (ml/extraction/RESULTS.md round 3), and a place's features are said of it in the
    one sentence.

    Not a description: nothing after it, a line of dialogue, something done to an
    object ("병사들을 맞이했다") or with a person ("레온이 지켰다")."""
    narration = sentence.narration
    # The topic of the sentence (은/는), with the particle ending there: not the
    # subject of "벨로스 성이 보였다" (nothing said of the place) or the start of an
    # ending ("검은 숲이지만").
    after = narration[mention.end + 1 : mention.end + 2]
    if narration[mention.end : mention.end + 1] not in ("은", "는") or not after.isspace():
        return ""
    # What's said up to the end of the clause the topic particle is in.
    end = next(stop for _, stop in _clauses(narration) if stop > mention.end)
    # The narration has its quoted parts blanked out: a quote there is a line the place figures in.
    if _QUOTE.search(sentence.text[mention.end : end]):
        return ""
    predicate = " ".join(narration[mention.end + 1 : end].split()).strip(_PREDICATE_EDGE)
    if (
        not 2 <= len(predicate) <= _FEATURES_MAX_LENGTH
        or _NOT_A_DESCRIPTION.search(_VILLAGE_NOUNS.sub("", predicate))
        or _PRONOUN_PHRASE.search(predicate)
    ):
        return ""
    # A character in what's said (not one before the place: "레온이 보기에 검은 숲은 ...").
    if any(other.subject.kind == "character" and mention.end <= other.start < end for other in others):
        return ""
    return predicate


_FEATURES_MAX_LENGTH = 40
_PREDICATE_EDGE = " 	\"'“”‘’「」『』.!?…~"
_QUOTE = re.compile(r"[\"“”‘’「」『』]")
# An object particle on a word ("병사들을 ..."), at the end of the clause too.
_NOT_A_DESCRIPTION = re.compile(r"(?<=[가-힣])[을를](?=\s|$)")
# Nouns that end in 을 themselves ("마을 북쪽에"), unless 을/를 follows ("마을을").
_VILLAGE_NOUNS = re.compile(r"(?:마을|가을|고을|노을)(?![을를])")


@dataclass(frozen=True)
class CueHit:
    attribute: Attribute
    start: int  # of the cue, in the sentence's narration
    clause: tuple[int, int]  # the clause it is in, which the QA model reads


def _clauses(narration: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    # Not the comma inside a number ("1,000리").
    for match in re.finditer(r"(?<!\d),(?!\d)|[，、]", narration):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(narration)))
    return spans


# How many words around the noun a color can be in: "레온의 길고 푸른 눈", "눈은
# 푸른색이었다". Further off it's another thing's color ("검은 옷을 입은 그는
# 머리를 숙였다").
_WORDS_BEFORE = 2
# Nouns that are an eye or a head as often as part of a phrase (눈을 뜨다, 머리를 숙이다).
_WEAK_NOUNS = ("눈", "머리")
_WORDS_AFTER = 3


def _color_near(clause: str, noun: re.Match) -> bool:
    if COLOR_RE.search(noun.group()):  # "금발"
        return True
    before = " ".join(clause[: noun.start()].split()[-_WORDS_BEFORE:])
    if COLOR_RE.search(before):
        return True
    # After a bare 눈 or 머리 only as its subject or topic ("눈이 붉게", "눈은
    # 푸른색"): "눈을 뜨자 검은 연기가", "눈에 띄는 붉은 ..." are other things.
    following = clause[noun.end() : noun.end() + 1]
    if noun.group() in _WEAK_NOUNS and following and following in "을를에도":
        return False
    after = " ".join(clause[noun.end() :].split()[:_WORDS_AFTER])
    return COLOR_RE.search(after) is not None


def cue_hits(narration: str) -> list[CueHit]:
    hits = []
    for clause in _clauses(narration):
        text = narration[clause[0] : clause[1]]
        for attribute in ATTRIBUTES:
            match = attribute.noun.search(text)
            if not match or (attribute.needs_color and not _color_near(text, match)):
                continue
            if attribute.unless and not match.groupdict().get("strong") and attribute.unless.search(text):
                continue
            hits.append(CueHit(attribute, clause[0] + match.start(), clause))
    return hits


_TRAILING_PARTICLE = re.compile(r"[이가를을의도만에]+$")


def value_of(attribute: Attribute, answer: str, context: str) -> str:
    """The value an answer gives, as a card would hold it, "" where it doesn't
    look like one of the attribute: a color for eyes and hair, a number for an
    age.

    The model's span can end inside a word ("붉" of "붉게") or run on into the
    noun it describes ("푸른 눈"); for a color, the first color word of the
    answer is taken, and finished from the clause where its last syllable is missing."""
    value = " ".join(answer.split())
    if attribute.needs_color:
        word = next((token for token in value.split() if COLOR_RE.search(token)), None)
        if word is None:
            return ""
        # Taken whole only where one syllable is missing ("붉" / "붉게"), not where
        # the answer is a word already and the clause goes on ("푸른색" / "푸른색이었다.").
        whole = next(
            (
                t.rstrip(".!?…")
                for t in context.split()
                if t.startswith(word) and len(t.rstrip(".!?…")) - len(word) <= 1
            ),
            word,
        )
        trimmed = _TRAILING_PARTICLE.sub("", whole)
        value = trimmed if COLOR_RE.search(trimmed) else whole
    if value and attribute.value is not None and not attribute.value.search(value):
        return ""
    return value


# A word for a person, after a 그 ("그 녀석"): a pronoun like 그 and 그녀.
_PERSON_NOUNS = "녀석|놈|사내|남자|여자|소년|소녀|아이|사람|청년|노인|아가씨|여인|남성|여성"

# --- Asking about a pronoun -----------------------------------------------------

# What can follow a pronoun: a space, the end, or punctuation ("그녀는, ...").
_PRONOUN_END = r"(?=[\s,.!?…\"'”’」』)]|$)"
_PRONOUN_PHRASE = re.compile(
    r"(?<![가-힣])(?:그녀(?!석)(?P<she>)|그(?=(?:의|는|은|가|이|를|을|도)" + _PRONOUN_END + r")(?P<he>)|그\s?(?:"
    + _PERSON_NOUNS
    + r")(?P<noun>))"
    r"(?P<particle>의|는|은|가|이|를|을|도|만)?" + _PRONOUN_END
)
_ALTERNATING_PARTICLES = {
    "은": ("은", "는"),
    "는": ("은", "는"),
    "이": ("이", "가"),
    "가": ("이", "가"),
    "을": ("을", "를"),
    "를": ("을", "를"),
}


def with_particle(name: str, particle: str) -> str:
    """The name and the particle, in the form its last syllable takes (레온은,
    세린은, 엘리제는). A name that doesn't end in Hangul takes the consonant form."""
    forms = _ALTERNATING_PARTICLES.get(particle)
    if forms is None:
        return name + particle
    last = name[-1:]
    vowel_final = "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 == 0
    return name + forms[1 if vowel_final else 0]


def _fitting_pronoun(clause: str, pronoun: str) -> tuple[re.Match | None, bool]:
    """(the first pronoun in the clause that fits a character narrated with
    `pronoun`, whether the clause has any pronoun)."""
    matches = list(_PRONOUN_PHRASE.finditer(clause))
    for match in matches:
        kind = _pronoun_kind(match.group())
        if kind == "any" or pronoun in (kind, "any"):
            return match, True
    return None, bool(matches)


def points_elsewhere(clause: str, pronoun: str) -> bool:
    """Whether every pronoun in the clause is the other gender than the character's
    (pronoun: he | she | any): it's about somebody else."""
    found, has_pronoun = _fitting_pronoun(clause, pronoun)
    return has_pronoun and found is None


def name_for_pronoun(clause: str, name: str, pronoun: str = "any") -> str:
    """The clause with the name where its first pronoun is ("그녀의 은빛 머리카락이"
    -> "세린의 은빛 머리카락이"; 그, 그녀, 그 녀석 and the like): the QA model
    answers a question about a person that its context names, and not about one
    it only refers to. Not where the pronoun is the other gender than the
    character's (pronoun: he | she | any), as it points to somebody else; the first
    pronoun that fits is the one replaced."""
    found, _ = _fitting_pronoun(clause, pronoun)
    if found is None:
        return clause
    return clause[: found.start()] + with_particle(name, found.group("particle") or "") + clause[found.end() :]


# --- Whose it is -------------------------------------------------------------

_PRONOUNS = ("그", "그녀", "자신")
# 그 alone is the demonstrative of "그 순간", "그 해"; it's a pronoun with a
# particle ("그는", "그의"; not 만: "그만" is "enough"), or in front of a word for a person ("그 녀석").
_PLURAL_PRONOUN = re.compile(r"\s*(?:그들|그녀들)")
_PARTICLES_AFTER_PRONOUN = "의|는|은|가|이|를|을|도|만"
_EARLY_PRONOUN = re.compile(
    r"(?<![가-힣])(?:"
    rf"그녀(?![가-힣]*들)(?:{_PARTICLES_AFTER_PRONOUN})?{_PRONOUN_END}"
    rf"|그(?:{_PARTICLES_AFTER_PRONOUN.removesuffix('|만')}){_PRONOUN_END}"
    rf"|그\s?(?:{_PERSON_NOUNS})(?!들)"
    r")"
)
# How far into a sentence a cue can start and still read as its subject
# ("붉은 눈동자가 어둠 속에서 번뜩였다"), when the sentence has no name.
_CUE_FIRST_CHARS = 12
# How far into a sentence a pronoun can be and still be its subject ("스물세 살의 그녀는 ...").
_PRONOUN_WINDOW = 20
_BODY_ATTRIBUTES = ("eye_color", "hair_color", "scars", "height")
# How many sentences back a pronoun's name is looked for.
CONTEXT_SENTENCES = 2

_MALE_NOUNS = ("사내", "남자", "소년", "청년", "남성")
_FEMALE_NOUNS = ("소녀", "여자", "아가씨", "여인", "여성")


def _pronoun_kind(text: str) -> str:
    """Whom a pronoun or a 그 + person points to: he (그, 그 사내), she (그녀,
    그 소녀) or any (그 녀석, 자신: nothing to tell by)."""
    if text.startswith("그녀석") or not text.startswith("그"):
        return "any"
    if text.startswith("그녀"):
        return "she"
    word = text[1:].strip()
    if word.startswith(_FEMALE_NOUNS):
        return "she"
    if word.startswith(_MALE_NOUNS) or not word.startswith(tuple(_PERSON_NOUNS.split("|"))):
        return "he"
    return "any"


_GENITIVE = re.compile(r"([가-힣A-Za-z0-9]+)의\s+(?:\S+\s+){0,2}$")


def _characters(mentions: list[Mention]) -> dict[tuple[str, str], Subject]:
    return {m.subject.key: m.subject for m in mentions if m.subject.kind == "character"}


@dataclass(frozen=True)
class Ambiguous:
    """A cue whose owner is one of several characters the pronoun fits, which
    the author can pick from."""

    subjects: tuple[Subject, ...]  # registered characters, two or more
    kind: str  # the pronoun's: he | she | any


def owner(
    sentences: list[Sentence], mentions: list[list[Mention]], index: int, hit: CueHit
) -> Subject | Ambiguous | None:
    """The character a cue in sentences[index] is about; Ambiguous where a
    pronoun fits several registered characters; None where that isn't clear.
    mentions[i]: sentences[i]'s mentions."""
    narration = sentences[index].narration
    here = _characters(mentions[index])

    # A possessor right in front of the cue.
    before = narration[: hit.start]
    genitive = _GENITIVE.search(before)
    pronoun_possessor = False
    possessor_kind = "any"
    if genitive:
        possessor_end = genitive.start(1) + len(genitive.group(1))
        named = [m for m in mentions[index] if m.subject.kind == "character" and m.end == possessor_end]
        if named:
            return named[0].subject
        # "그 녀석의 눈": the possessor is the word for a person after a 그.
        person_after_that = genitive.group(1) in _PERSON_NOUNS.split("|") and re.search(
            r"(?<![가-힣])그\s?$", before[: genitive.start(1)]
        )
        if genitive.group(1) in _PRONOUNS or person_after_that:
            # "세린은 그의 푸른 눈을 보았다": 그의 is somebody the sentence doesn't
            # name, not its subject (자신의 would be).
            if here and genitive.group(1) != "자신":
                return None
            pronoun_possessor = True
            possessor_kind = _pronoun_kind(("그" if person_after_that else "") + genitive.group(1))
        else:
            return None  # somebody else's ("노인의 눈")

    if len(here) == 1:
        return next(iter(here.values()))
    if len(here) > 1:
        return None

    # No name in the sentence: a pronoun or a dropped subject.
    if _PLURAL_PRONOUN.match(narration):
        return None
    lead = len(narration) - len(narration.lstrip())
    # A dropped subject only for what the sentence's subject can be a body part
    # of ("붉은 눈동자가 번뜩였다"); "여섯 살 때의 일이었다" isn't about anyone.
    dropped_subject = hit.attribute.key in _BODY_ATTRIBUTES and hit.start - lead <= _CUE_FIRST_CHARS
    # Found in the whole sentence, then kept to the window: cut at its end, "그녀들은"
    # would read as "그녀".
    early = _EARLY_PRONOUN.search(narration)
    if early and early.start() >= lead + _PRONOUN_WINDOW:
        early = None
    if not (pronoun_possessor or early or dropped_subject):
        return None
    candidates: dict[tuple[str, str], Subject] = {}
    for back in range(1, CONTEXT_SENTENCES + 1):
        if index - back >= 0:
            candidates.update(_characters(mentions[index - back]))
    if len(candidates) > 1:
        # What the pronoun shows narrows them: 그 isn't a character narrated
        # with 그녀, and a card that answers to either stays a candidate. With
        # one candidate there's nothing to choose between, so the pronoun isn't held
        # against it.
        kind = possessor_kind if pronoun_possessor else _pronoun_kind(early.group()) if early else "any"
        if kind != "any":
            candidates = {key: subject for key, subject in candidates.items() if subject.pronoun in (kind, "any")}
        if len(candidates) > 1:
            registered = tuple(subject for subject in candidates.values() if subject.ref)
            # Only between cards the author has: one of an unregistered name
            # can't be picked.
            if len(registered) == len(candidates):
                return Ambiguous(registered, kind)
    return next(iter(candidates.values())) if len(candidates) == 1 else None
