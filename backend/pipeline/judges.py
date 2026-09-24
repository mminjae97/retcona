"""The judgment modules (design doc 7.2).

They share the same interface (claims + context_bundle in -> flags out) so
they can run in parallel and be swapped out easily (6.2).

| Module | Main input fields | Judgment method |
|---|---|---|
| Appearance/behavior violation | fixed_attrs, latest_mutable_state, personality, world_settings | Appearance: NLI / Behavior (OOC): LLM |
| Location error | fixed_attrs (terrain), relations (distance) | NLI + rule-based distance calculation |
| Spacetime contradiction | last_known_position, state_history, relations | Rule-based time/distance verification + LLM assist |

Appearance and location (stage 2) compare what a claim says about a card
attribute with the card's value for it. NLI takes the card's value as a
sentence (premise) and the manuscript sentence the claim came from
(hypothesis): the sentence as written, rather than the claim's value in the
same template, because the model reads two same-shaped sentences with
different values ("17살" / "열일곱 살") as contradicting, however alike they
mean. The claim's own restatement, which names the subject (ai/llm.py), is
the hypothesis instead when the sentence doesn't name the subject ("그의 눈이
붉게 빛났다" reads to the model as about someone else), or names another
character/location the episode makes claims about too ("레온의 눈은 파랬고,
카엘의 눈은 붉게 빛났다" would hold Kael's eyes against Leon's card) — only
then, since a restatement shaped like the premise gets synonyms ("하늘빛" /
"푸른색") read as contradicting. A pair is only sent to
the model when the card has a value from somewhere other than this episode
and the claim's value doesn't simply repeat it.

Only fixed attributes are judged: mutable ones (hairstyle, outfit, ...)
change over the story, and a change is state history, not an error. Distance
between locations needs distances in relations first — with spacetime
(stage 4). Behavior (OOC) is stage 5.
"""

import uuid
from dataclasses import dataclass

from ai.nli_rerank import check_contradictions
from models.character import FIXED_ATTR_KEYS
from models.location import GEO_ATTR_KEYS
from pipeline.context_bundle import Card, ContextBundle
from pipeline.entities import normalize_name
from pipeline.extract_claims import ExtractedClaim

# A pair the model finds this likely to contradict is flagged. Past one half,
# contradiction is also the most likely of the three labels.
CONTRADICTION_THRESHOLD = 0.5

# What each character key is called in the premise sentence, with its topic
# particle. A location's features read as what the place is ("검은 숲은 ...이다").
_CHARACTER_ATTR_TOPICS = {
    "age": "나이는",
    "eye_color": "눈 색깔은",
    "hair_color": "머리색은",
    "height": "신장은",
    "scars": "흉터는",
    "origin": "출신은",
}


@dataclass(frozen=True)
class Flag:
    claim_index: int  # position in the claims the module was given
    subject_id: uuid.UUID
    error_type: str  # appearance | behavior | location | spacetime
    attribute: str
    confidence: float
    evidence_text: str
    reference_text: str


@dataclass(frozen=True)
class _Pair:
    claim_index: int
    card: Card
    attribute: str
    premise: str
    hypothesis: str
    evidence: str


def _as_statement(value: str) -> str:
    # "푸른색" -> "푸른색이다."; a value that's already a sentence (ends in 다
    # or punctuation) is kept, with a period.
    value = value.rstrip()
    if value.endswith((".", "!", "?", "…")):
        return value
    return f"{value}." if value.endswith("다") else f"{value}이다."


def _topic_particle(word: str) -> str:
    # 은 after a final consonant, 는 after a vowel; 은 when the word doesn't
    # end in a Hangul syllable (digits, Latin).
    last = word.rstrip()[-1:]
    if "가" <= last <= "힣" and (ord(last) - ord("가")) % 28 == 0:
        return "는"
    return "은"


def _premise(card: Card, attribute: str, value: str) -> str:
    if card.kind == "character":
        return f"{card.name}의 {_CHARACTER_ATTR_TOPICS[attribute]} {_as_statement(value)}"
    return f"{card.name}{_topic_particle(card.name)} {_as_statement(value)}"


def _pairs(claims: list[ExtractedClaim], bundle: ContextBundle, kind: str, keys: tuple[str, ...]) -> list[_Pair]:
    this_episode = str(bundle.episode_id)
    subjects = {normalize_name(claim.subject) for claim in claims if claim.subject_kind == kind}
    pairs = []
    for index, claim in enumerate(claims):
        if claim.subject_kind != kind:
            continue
        card = bundle.card_for(claim)
        if card is None:
            continue  # a new entity: nothing to contradict yet
        evidence = claim.evidence or claim.text
        subject = normalize_name(claim.subject)
        named = {name for name in subjects if name in normalize_name(evidence)}
        # One name inside the other ("레온" / "레온하트") isn't a second subject.
        others = {name for name in named if subject not in name and name not in subject}
        hypothesis = evidence if subject in named and not others else claim.text
        for attribute, value in claim.attributes.items():
            setting = card.attrs.get(attribute)
            if attribute not in keys or not setting or card.sources.get(attribute) == this_episode:
                continue
            # The value itself repeats the setting ("푸른색" / "푸른색 눈동자").
            if normalize_name(setting) in normalize_name(value):
                continue
            pairs.append(_Pair(index, card, attribute, _premise(card, attribute, setting), hypothesis, evidence))
    return pairs


def _judge(pairs: list[_Pair], error_type: str) -> list[Flag]:
    scores = check_contradictions([(pair.premise, pair.hypothesis) for pair in pairs])
    return [
        Flag(
            claim_index=pair.claim_index,
            subject_id=pair.card.id,
            error_type=error_type,
            attribute=pair.attribute,
            confidence=round(score.contradiction, 4),
            evidence_text=pair.evidence,
            reference_text=pair.card.attrs[pair.attribute],
        )
        for pair, score in zip(pairs, scores, strict=True)
        if score.contradiction >= CONTRADICTION_THRESHOLD
    ]


def judge_appearance(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    """A character's fixed attributes (eye color, scars, origin, ...) against its card, by NLI."""
    return _judge(_pairs(claims, context_bundle, "character", FIXED_ATTR_KEYS), "appearance")


def judge_behavior(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    # TODO (stage 5): LLM + personality/speech profile-based inference (OOC)
    raise NotImplementedError


def judge_location(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    """A location's geographic features against its card, by NLI."""
    # TODO (stage 4): rule-based distance calculation, once relations carry distances
    return _judge(_pairs(claims, context_bundle, "location", GEO_ATTR_KEYS), "location")


def judge_timeline(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    # TODO (stage 4): rule-based time/distance verification + LLM assist
    raise NotImplementedError
