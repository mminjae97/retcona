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

import re
import uuid
from dataclasses import dataclass

from ai.nli_rerank import check_contradictions
from models.character import FIXED_ATTR_KEYS
from models.location import GEO_ATTR_KEYS
from pipeline.context_bundle import Card, ContextBundle
from pipeline.entities import normalize_name
from pipeline.extract_claims import ExtractedClaim
from pipeline.statements import character_statement, location_statement

# A pair the model finds this likely to contradict is flagged. Past one half,
# contradiction is also the most likely of the three labels.
CONTRADICTION_THRESHOLD = 0.5

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


def _premise(card: Card, attribute: str, value: str) -> str:
    if card.kind == "character":
        return character_statement(card.name, attribute, value)
    return location_statement(card.name, value)


def repeats(value: str, setting: str) -> bool:
    """Whether the claim's value just repeats the setting ("푸른색 눈동자" /
    "푸른색") — not as part of a longer number ("17살" doesn't repeat "7살")."""
    pattern = rf"(?<!\d){re.escape(normalize_name(setting))}(?!\d)"
    return re.search(pattern, normalize_name(value)) is not None


def _pairs(
    claims: list[ExtractedClaim],
    bundle: ContextBundle,
    kind: str,
    keys: tuple[str, ...],
    other_subjects: set[str] = frozenset(),
) -> list[_Pair]:
    this_episode = str(bundle.episode_id)
    subjects = {normalize_name(claim.subject) for claim in claims if claim.subject_kind == kind and claim.subject}
    subjects |= other_subjects
    pairs = []
    for index, claim in enumerate(claims):
        if claim.subject_kind != kind:
            continue
        card = bundle.card_for(index)
        if card is None:
            continue  # a new entity: nothing to contradict yet
        evidence = claim.evidence or claim.text
        hypothesis = _hypothesis(normalize_name(claim.subject), evidence, claim.text, subjects)
        for attribute, value in claim.attributes.items():
            if attribute not in keys or not _to_judge(card, attribute, value, this_episode):
                continue
            premise = _premise(card, attribute, card.attrs[attribute])
            pairs.append(_Pair(index, card, attribute, premise, hypothesis, evidence))
    return pairs


def _hypothesis(subject: str, evidence: str, text: str, subjects: set[str]) -> str:
    # The sentence, or the claim's restatement where the sentence doesn't name
    # the subject or names another of the episode's subjects (see above).
    # subject and subjects normalized.
    named = {name for name in subjects if name in normalize_name(evidence)}
    # One name inside the other ("레온" / "레온하트") isn't a second subject.
    others = {name for name in named if subject not in name and name not in subject}
    return evidence if subject in named and not others else text


def _to_judge(card: Card, attribute: str, value: str | None, this_episode: str) -> bool:
    # Only against a value from somewhere other than this episode, and one the
    # claim's value doesn't simply repeat.
    setting = card.attrs.get(attribute)
    if not setting or card.sources.get(attribute) == this_episode:
        return False
    return not (value and repeats(value, setting))


def rejudge(
    card: Card,
    attribute: str,
    value: str | None,
    subject: str,
    evidence: str | None,
    text: str,
    subjects: set[str],
    episode_id: uuid.UUID,
) -> float | None:
    """One flag judged again against its card as it is now (7.5,
    pipeline/revalidate_flag.py), by the same rules as a run: the NLI
    contradiction probability, or None where a run wouldn't ask the model —
    the card has no value for the attribute, the value came from this same
    episode, or the manuscript's value repeats it — which contradicts nothing.
    subjects: the episode's subjects of this kind, normalized."""
    if not _to_judge(card, attribute, value, str(episode_id)):
        return None
    hypothesis = _hypothesis(normalize_name(subject), evidence or text, text, subjects)
    [score] = check_contradictions([(_premise(card, attribute, card.attrs[attribute]), hypothesis)])
    return round(score.contradiction, 4)


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


def judge_appearance(
    claims: list[ExtractedClaim], context_bundle: ContextBundle, other_subjects: set[str] = frozenset()
) -> list[Flag]:
    """A character's fixed attributes (eye color, scars, origin, ...) against its card, by NLI.
    other_subjects: the normalized names of the episode's other subjects, when
    only some of its claims are judged (the sentence read depends on them)."""
    return _judge(_pairs(claims, context_bundle, "character", FIXED_ATTR_KEYS, other_subjects), "appearance")


def judge_behavior(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    # TODO (stage 5): LLM + personality/speech profile-based inference (OOC)
    raise NotImplementedError


def judge_location(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    """A location's geographic features against its card, by NLI."""
    # TODO (stage 4): rule-based distance calculation, once relations carry distances
    # TODO (stage 4): a later episode's features against the place's latest state
    # (location_state_history, written by pipeline/merge.py): a city described again
    # after it fell. Only features are compared with the card here; a "state" claim
    # (a change the story makes) never is.
    return _judge(_pairs(claims, context_bundle, "location", GEO_ATTR_KEYS), "location")


def judge_timeline(claims: list[ExtractedClaim], context_bundle: ContextBundle) -> list[Flag]:
    # TODO (stage 4): rule-based time/distance verification + LLM assist
    raise NotImplementedError
