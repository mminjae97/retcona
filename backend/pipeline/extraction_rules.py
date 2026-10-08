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
character the three sentences before it name, if there's exactly one — missing a
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
    # what an answer must not be
    reject: re.Pattern | None = None
    # Rules a clause out where the noun is the weak kind (not the named group
    # "strong"): 눈 is an eye, or snow.
    unless: re.Pattern | None = None


# A body part, as a whole word: the words whose usual meaning is the body. They tell, in
# front of a cue, that the cue is where it is ("오른손의 흉터"), not whose it is.
_BODY_PART_WORD = (
    r"(?:(?:오른|왼|양)?(?:손|팔|다리|얼굴|어깨|가슴|뺨|이마|턱|허리|무릎|옆구리|허벅지|종아리)(?:등|목|바닥|가락|덜미|뚝)?"
    r"|눈가|눈썹|머리|코|입술|귀|발목|목덜미)"
)
# Words that mean something else as often (a ship, "and so on", snow): not a sign of a
# possessor, but in an answer, the place of a mark all the same.
_BODY_PART_AMBIGUOUS = r"(?:눈|입|발|목|배|등|볼)"

# An answer that is nothing but body parts, listed or placed: "왼팔", "왼팔은", "왼팔과
# 오른팔", "왼쪽 뺨과 이마", "뺨 위에". Not a value. Every body word counts, the ambiguous
# ones too.
_BODY_ITEM = (
    rf"(?:(?:오른|왼|양)쪽\s)?(?:{_BODY_PART_WORD}|{_BODY_PART_AMBIGUOUS})(?:에서|에는|에도|으로|[에의이가을를은는도로와과만])?"
)
_ONLY_BODY_PARTS = re.compile(
    rf"^{_BODY_ITEM}(?:,?\s{_BODY_ITEM})*(?:\s(?:위|아래|근처|부근)(?:에서|에|의)?)?[.!?…]?$"
)

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
    # An answer that is only a body part is the place of the mark, not the mark
    # ("왼팔의 상흔" answered "왼팔"); every body word counts here, the ambiguous ones too.
    Attribute(
        "scars",
        "흉터는",
        re.compile(r"흉터|상흔|(?<![발손물퀴])자국"),
        reject=_ONLY_BODY_PARTS,
    ),
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
    # A character in what's said ("레온이 지켰다") or another topic ("성은 크고 마을은
    # 작았다"), not a place it's told by ("벨로스 성 북쪽에") or one before it
    # ("레온이 보기에 검은 숲은 ...").
    if any(
        mention.end <= other.start < end and (other.subject.kind == "character" or other.topic)
        for other in others
        if other is not mention
    ):
        return ""
    return predicate


# A predicate that says the place changed or is in a changed state, not what it is
# like: "폐허가 되었다", "불탔다", "무너졌다", "재건되었다". The word has to end the
# predicate (its last two words, or its last word where that is "...였다": a noun
# the place is) and not be denied, so "오래전 몰락한 왕가의 거처였다", "잿더미 위에
# 세워진 도시였다", "교역의 중심이 되었다" and "무너지지 않았다" are features.
_STATE_CHANGE = re.compile(
    r"폐허|잿더미|무너|붕괴|불타(?!는)|불탔|타\s?버렸|파괴|멸망|함락|몰락|사라졌|없어졌|황폐해졌|황폐화|황량해졌|시들었"
    r"|전소|소실|허물어|부서졌|쓰러졌|스러졌|가라앉|침몰|버려졌|재건|복구|복원|되살아|(?:황무지|불모지)가\s?되"
)
# Not a change that happened: denied, or only about to / tried to ("무너질 듯했다"),
# or only likened ("폐허 같았다"), or wished ("재건을 꿈꿨다"). Looked for from the word
# before the state word on, so an earlier clause ("막으려 했으나 결국 함락되었다")
# doesn't veto it.
_DENIED = re.compile(
    r"않|적\s?(?:이\s?)?없|리\s?없|아니|듯|뻔|(?<![가-힣])시도|려고|려\s?했|나섰|꿈|바랐|길\s?바|기다렸|소망|원했|기대|바라|못했|못한|같았|다름없|처럼|마치"
)
# A verb that only carries the one before it ("폐허가 되어 버렸다", "되고 말았다"), not
# after a place ("폐허 근처에 있었다").
_CONNECTING = ("어", "아", "여", "고")
_AUXILIARY = re.compile(r"^(?:버렸|버린|있었|있다|있는|두었|놓았|놓였|말았)")
# 안 / 못 before the verb ("안 무너졌다"), not the noun "안" ("성 안 전체가").
_DENIED_BEFORE_VERB = re.compile(r"(?<![가-힣])[안못]\s")
# "...이었다", "...였다": a noun the place is; not "변하였다".
_COPULA = re.compile(r"이었|이다|(?<!하)였")


# "폐허가 된 지 오래였다": a state that came about, said as how long ago.
_BECAME = re.compile(r"(?:폐허|잿더미|황무지|불모지)[가이]\s?된\s?(?:지|뒤)")


def is_state_change(predicate: str) -> bool:
    words = predicate.split()
    if not words:
        return False
    if _BECAME.search(predicate):
        return True
    # The last two words, three where the last only carries the one before ("폐허가 되어 버렸다").
    carried = len(words) > 2 and _AUXILIARY.match(words[-1]) and words[-2].endswith(_CONNECTING)
    first = len(words) - 1 if _COPULA.search(words[-1]) else max(len(words) - (3 if carried else 2), 0)
    scope = " ".join(words[first:])
    found = _STATE_CHANGE.search(scope)
    if found is None:
        return False
    # The word the state word is in, and the word before it, on to the end.
    offset = len(" ".join(words[:first])) + (1 if first else 0) + found.start()
    word = 0
    while len(" ".join(words[: word + 1])) <= offset:
        word += 1
    after = " ".join(words[max(word - 1, 0) :])
    return not (_DENIED.search(after) or _DENIED_BEFORE_VERB.search(after))


# What a character does or undergoes, said in a sentence it is the subject of: its
# death, its coming back, or just that it is there. The spacetime judgment holds
# what comes after a death against it (pipeline/judges.py judge_spacetime).
#
# A death, as the predicate ends: "숨을 거두었다", "죽고 말았다". The word has to end the
# predicate, so "죽었다고 생각했다", "죽었다는 소식을 들었다", "죽지 않았다", "죽을 뻔했다"
# and "죽은 척했다" are not it.
_ENDING = r"(?:다|습니다|어요|어|죠|네|군)?$"
_DEATH = re.compile(
    r"(?:죽었|죽어\s?버렸|죽고\s?말았|숨졌|숨을\s?(?:거두었|거뒀)|숨이\s?끊(?:어졌|겼)|사망(?:했|하였)|전사(?:했|하였)"
    r"|절명했|운명했|목숨을\s?잃었|세상을\s?떠났|생을\s?마(?:감했|쳤)|처형(?:당했|되었|됐))" + _ENDING
)
# Alive again, said of the character itself: "되살아났다", "부활했다". A plain "다시
# 일어났다" is a fall and a getting up, not this.
_REVIVAL = re.compile(r"(?:되살아났|되살아나|부활했|부활하였|다시\s?살아났|소생했)" + _ENDING)
# Back as one of the undead ("언데드가 되어 일어났다", "좀비가 되었다", "언데드로 다시
# 일어났다"), however it was done: becoming one, not an undead doing something
# ("좀비가 일어섰다" is of the zombie).
_UNDEAD = r"(?:언데드|좀비|강시|스켈레톤|구울)"
_RISE = r"(?:일어났|일어섰|깨어났|움직였|걸어\s?나왔)"
_UNDEAD_RISE = re.compile(
    _UNDEAD
    + rf"(?:(?:이|가|로)\s?(?:(?:되어서?|변해)\s?(?:다시\s?)?(?:되었|됐|변했|{_RISE})|되었|됐|변했)|로\s?(?:다시\s?)?{_RISE})"
    + _ENDING
)
# ...or said right before the name ("언데드가 된 레온이 나타났다").
_UNDEAD_STATE = re.compile(_UNDEAD + r"(?:이|가|로)?\s?(?:된|변한|되어\s?버린)\s?$")
# Brought back by somebody else, said of the character as its object ("마법사가 레온을
# 되살렸다", "레온을 언데드로 만들었다"). Not "살려냈다": that's saved from dying.
_REVIVE_OBJECT = re.compile(
    r"(?:되살렸|되살려\s?냈|부활시켰|소생시켰|" + _UNDEAD + r"(?:로|가)?\s?(?:만들었|만들어\s?냈|되살렸|일으켜\s?세웠))"
    + _ENDING
)
# What follows the name when the sentence is about the character as an object, or as
# whose body ("레온의 시체를 ...", "레온의 시체가 ..."): the object's particle, or the
# corpse's with what is said of it.
_BODY = r"(?:시체|시신|유해|유골|뼈|영혼|혼)"
_AFTER_NAME = re.compile(rf"^(?:(?P<object>[을를])|의\s?{_BODY}(?:(?P<body_object>[을를])|[이가은는]))\s?(?P<tail>.*)$")
# Not something that happened: likened, pretended, dreamed.
# ("마치" only as the adverb, not the start of "마치고".)
_NOT_ACTUAL = re.compile(r"(?<![가-힣])마치(?![가-힣])|처럼|듯|척|꿈|악몽|만약|차라리")
# Adverbs in -이 ("어이없이 죽었다"), not a subject of their own.
_ADVERB_I = re.compile(r"(?:없이|같이|깊이|높이|일찍이|가까이|괴로이|외로이|쓸쓸이|헛되이|고이)$")


def _not_actual(said: str) -> bool:
    """Whether what the predicate ends in is likened, pretended or dreamed: said
    in its last three words, so a "꿈을 이루지 못한 채 죽었다" isn't one."""
    return _NOT_ACTUAL.search(" ".join(said.split()[-3:])) is not None
# A sentence that is about the dead rather than showing them, or about the past or
# a memory: a character who died is spoken of, remembered, mourned, or seen as a
# ghost, and none of it is the character turning up again.
_NOT_PRESENT = re.compile(
    r"소식|소문|무덤|묘비|묘지|장례|유해(?!한)|시신|유품|추모|애도|죽음|죽은|죽었|죽기|숨진|사망|전사\s?(?:했|하였)|유령|영혼|망령|환영|제사"
    r"|예전|옛날|옛적|어릴\s?적|어린\s?시절|과거|지난|한때|당시|회상|떠올리|떠올렸|기억|추억|그리워|그리움"
    # ...and what is told or left of them afterwards.
    r"|유언|전설|전해\s?(?:들|지|진|내려)|[다라]고\s?한다|알려져|불렸|불린"
)


def _said_of(sentence: Sentence, mention: Mention, others: list[Mention]) -> str:
    """What the sentence says of a character it is the subject of (은/는/이/가):
    from the particle to the end of the sentence, "" where nothing is said of it
    or another subject takes over (the predicate may be that one's)."""
    if not mention.topic or mention.subject.kind != "character" or mention.subject.candidates:
        return ""
    if any(other.topic and other.start >= mention.end for other in others if other is not mention):
        return ""
    return " ".join(sentence.narration[mention.end + 1 :].split()).strip(_PREDICATE_EDGE)


def _death_of_another(said: str) -> bool:
    """Whether the death the predicate ends in is somebody else's: the word
    before it is a subject of its own ("눈앞에서 동료가 죽었다", "그가 숨을 거두었다"),
    where "피가 많이 나서 죽었다" has a verb between."""
    found = _DEATH.search(said.strip(_PREDICATE_EDGE))
    before = said.strip(_PREDICATE_EDGE)[: found.start()].split() if found else []
    return bool(before) and re.search(r"[가-힣][이가]$", before[-1]) is not None and not _ADVERB_I.search(before[-1])


def _revival_of_self(said: str) -> bool:
    return _REVIVAL.search(said) is not None or _UNDEAD_RISE.search(said) is not None


def _revived_by_another(sentence: Sentence, mention: Mention) -> str:
    """"마법사가 레온을 되살렸다" -> "되살렸다", "레온의 시체가 언데드가 되어 일어났다"
    -> "언데드가 되어 일어났다": a character brought back, or whose body is, said of
    it as an object or as whose body it is; "" where it isn't."""
    if mention.subject.kind != "character" or mention.subject.candidates:
        return ""
    after = _AFTER_NAME.match(sentence.narration[mention.end :])
    if after is None:
        return ""
    tail = " ".join(after.group("tail").split()).strip(_PREDICATE_EDGE)
    if not tail or _not_actual(tail):
        return ""
    if after.group("object") or after.group("body_object"):
        return tail if _REVIVE_OBJECT.search(tail) else ""
    return tail if _revival_of_self(tail) else ""


def condition_of(sentence: Sentence, mention: Mention, others: list[Mention]) -> str:
    """A death, or a coming back from one, the sentence says of the character it
    is about ("레온은 결국 숨을 거두었다" -> "결국 숨을 거두었다", "마법사가 레온을
    되살렸다" -> "되살렸다", "언데드가 된 레온이 나타났다" -> "언데드가 된"); "" where it
    says neither."""
    said = _said_of(sentence, mention, others)
    if not said:
        return _revived_by_another(sentence, mention)
    if _not_actual(said):
        return ""
    if (is_death(said) and not _death_of_another(said)) or _revival_of_self(said):
        return said
    # Said of the character before its name: "언데드가 된 레온은 ...".
    undead = _UNDEAD_STATE.search(sentence.narration[: mention.start])
    return undead.group().strip() if undead else ""


def is_death(value: str) -> bool:
    return _DEATH.search(value.strip(_PREDICATE_EDGE)) is not None


def is_revival(value: str) -> bool:
    """Whether a "condition" a claim or the state history keeps is a coming back,
    whichever way the sentence said it."""
    value = value.strip(_PREDICATE_EDGE)
    return any(
        pattern.search(value) is not None for pattern in (_REVIVAL, _UNDEAD_RISE, _REVIVE_OBJECT, _UNDEAD_STATE)
    )


def presence_of(sentence: Sentence, mention: Mention, others: list[Mention]) -> str:
    """What the sentence has the character it is about do or be, as the
    narration tells it now ("레온은 문을 열고 들어섰다" -> "문을 열고 들어섰다"); ""
    for a sentence about the dead, the past or a memory (_NOT_PRESENT), and for a
    death or revival (condition_of)."""
    said = _said_of(sentence, mention, others)
    if len(said) < 2 or _NOT_PRESENT.search(sentence.narration) or condition_of(sentence, mention, others):
        return ""
    return said


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
    for match in re.finditer(r"(?<!\d),|,(?!\d)|[，、]", narration):
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
    # The words after the noun's own (its particle, "눈이", is not one of them).
    # The rest of the noun's token is dropped whole.
    rest = re.sub(r"^\S+", "", clause[noun.end() :])
    after = " ".join(rest.split()[:_WORDS_AFTER])
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
    if value and attribute.reject is not None and attribute.reject.search(value):
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
CONTEXT_SENTENCES = 3

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
# A body part ahead of the cue ("오른손의 흉터") is where the cue is, not whose it is.
# A whole word only (fullmatch): "후손의", "선배의" end in one but are people.
# What marks a name in a sentence as somebody the topic acts on, not a co-subject
# ("레온과 세린은 ..."): an object, or "에게/한테".
_ACTED_ON = re.compile(r"^(?:을|를|에게서|에게|한테서|한테)")


def _characters(mentions: list[Mention]) -> dict[tuple[str, str], Subject]:
    return {m.subject.key: m.subject for m in mentions if m.subject.kind == "character"}


def _adnominal(word: str) -> bool:
    """Whether a word modifies the word after it: 의, or an adnominal ending (-는,
    -던, -ㄴ/-ㄹ as the final consonant of 푸른, 한, 갈)."""
    # Not the object particles, 만, or an adverb that ends in a final consonant.
    if not word or word.endswith(("을", "를", "만", "번", "순간", "잠깐", "동안")):
        return False
    last = word[-1]
    if last in "의는던":
        return True
    return "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 in (4, 8)


# The end of a phrase of its own, as the last word before a name: a particle that doesn't
# modify what follows.
_PHRASE_END = ("에서", "에", "으로", "로", "와", "과", "까지", "부터", "에게", "한테", "도", "의")


def _describes_next(span: str) -> bool:
    """Whether the cue at the start of span (its noun and what follows, up to the next
    name) is said of that name: a word that modifies what follows, "눈이 푸른 소녀 세린을",
    "붉은 눈의 마녀 세린을". 의 counts only on the cue's own word ("눈의")."""
    words = span.split()
    # A modifier stands in the same phrase as what it modifies: only the words after the last
    # one with a particle of its own are looked at ("눈이 푸른 소녀 세린을"; not the 문 of
    # "문 앞에서 세린을", which is its own phrase).
    start = 1 + max((i for i, word in enumerate(words[1:]) if word.endswith(_PHRASE_END)), default=-1) + 1
    first = words[0].endswith("의") if words else False
    return first or any(
        # "한 번" is a number of times, not a "한" of the name.
        # A later "앞의", "안의" is a place, not the cue's.
        _adnominal(word) and not word.endswith("의") and words[i + 1 : i + 2] != ["번"]
        for i, word in enumerate(words)
        if i >= start
    )


def _topic_before(narration: str, mentions: list[Mention], end: int) -> bool:
    """Whether a character is the topic of the sentence up to end, with no other subject
    between ("레온이 다가가자 노인은 오른손의 흉터를": 노인 is, and he isn't registered)."""
    for mention in mentions:
        if mention.subject.kind != "character" or not mention.topic or mention.end >= end:
            continue
        # After the topic's particle; a one-syllable word may be 이 "this".
        between = narration[mention.end + 1 : end].split()
        if not any(len(word) >= 2 and word[-1] in "은는이가" for word in between):
            return True
    return False


def _topic_of_two(narration: str, mentions: list[Mention], hit: CueHit) -> Subject | None:
    """The owner of a cue in a sentence with several characters and no possessor in
    front of it, where one is the topic and the cue comes before the others, who
    are acted on ("레온은 붉은 눈동자로 카엘을 노려보았다": 레온's). None otherwise:
    "레온과 세린은 눈이 푸르렀다" is both, "레온은 붉은 눈의 카엘을 ..." is the other's."""
    if hit.attribute.key not in _BODY_ATTRIBUTES:
        return None  # "레온은 스무 살 때 세린을 만났다": not a thing of the body
    characters = [m for m in mentions if m.subject.kind == "character"]
    topics = [m for m in characters if m.topic]
    if len(topics) != 1 or topics[0].end > hit.start:
        return None
    if len({m.subject.key for m in characters}) != len(characters):
        return None
    for other in characters:
        if other is topics[0]:
            continue
        # After the cue, and marked as acted on.
        if other.start < hit.start or not _ACTED_ON.match(narration[other.end :]):
            return None
        # "붉은 눈의 세린을", "눈이 푸른 세린을": the cue describes the other.
        if _describes_next(narration[hit.start : other.start]):
            return None
    return topics[0].subject


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
    body_part_possessor = False
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
        if re.fullmatch(_BODY_PART_WORD, genitive.group(1)):
            # "오른손의 흉터": no possessor, so the sentence's own subject; but "그 손의
            # 흉터" is the hand of somebody already mentioned, not this sentence's.
            if re.search(r"(?<![가-힣])[그이저]\s(?:(?:오른|왼|양)쪽\s)?$", before[: genitive.start(1)]):
                return None
            # The sentence's own subject, which is the topic: "노인은 레온에게 오른손의
            # 흉터를 보여주었다" is the old man's hand, shown to 레온.
            if here and not _topic_before(narration, mentions[index], genitive.start(1)):
                return None
            body_part_possessor = True
        elif genitive.group(1) in _PRONOUNS or person_after_that:
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
        return _topic_of_two(narration, mentions[index], hit)

    # No name in the sentence: a pronoun or a dropped subject.
    if _PLURAL_PRONOUN.match(narration):
        return None
    lead = len(narration) - len(narration.lstrip())
    # A dropped subject only for what the sentence's subject can be a body part
    # of ("붉은 눈동자가 번뜩였다"); "여섯 살 때의 일이었다" isn't about anyone.
    # Not where a body part has its "X의" ("노인은 오른손의 흉터를 보였다"): the subject
    # may be somebody the text doesn't register, so only a pronoun links it.
    dropped_subject = (
        hit.attribute.key in _BODY_ATTRIBUTES and hit.start - lead <= _CUE_FIRST_CHARS and not body_part_possessor
    )
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
