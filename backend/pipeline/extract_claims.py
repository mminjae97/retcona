"""Extract verification-target claims from the manuscript (design doc 7.1.1, first step).

Input: novel_id, manuscript text, the novel's known characters (a ref, the
  name and aliases of each) and location names
Output: ExtractedClaims (claim_type: appearance | location)

No LLM (7.1.1): the manuscript is split into sentences (pipeline/sentences.py);
the characters and places each names are found by their registered names and
aliases and by the NER model, for names not registered yet; the sentences with
a cue for a card attribute ("눈동자", "머리카락", "살", ...) are asked, by the
extractive QA model, for its value ("레온의 눈 색깔은?" -> "푸른색");
pronouns and dropped subjects are linked by rules, only where there's one
candidate (pipeline/extraction_rules.py). A claim about a known character
carries its ref (subject_ref) — characters can share a name — and the
registered name as its subject; entity matching (pipeline/entities.py, 7.4)
goes by the ref, and by name or alias where there's none.

Behavior (OOC) and spacetime claims aren't extracted yet: nothing judges them
until their stages (7.2) are built, and what they need from the extraction
follows from the judgment.

What the models see is narration only: a line of dialogue is what a character
says, not the narrator stating a fact about a card.
"""

import logging
import re
import unicodedata
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from ai import nli_rerank
from infra.span_inference import NamedEntity
from models.character import FIXED_ATTR_KEYS, MUTABLE_ATTR_KEYS
from models.location import GEO_ATTR_KEYS
from pipeline import extraction_rules as rules
from pipeline.sentences import Sentence, split_sentences
from pipeline.statements import character_statement, location_statement

logger = logging.getLogger(__name__)

# The same limits the settings screen puts on a card (api/settings.py), so a
# card created from a claim fits what that screen can save back.
NAME_MAX_LENGTH = 100
ATTR_MAX_LENGTH = 500
_TEXT_MAX_LENGTH = 2000

_ATTR_KEYS = {
    "character": set(FIXED_ATTR_KEYS + MUTABLE_ATTR_KEYS),
    "location": set(GEO_ATTR_KEYS),
}


class ExtractedClaim(BaseModel):
    claim_type: Literal["appearance", "behavior", "location", "spacetime"]
    subject_kind: Literal["character", "location"]
    # Empty only for a claim about "그" that fits several characters (candidates).
    subject: str = Field(default="", max_length=NAME_MAX_LENGTH)
    # The known character's ref from the prompt; checked by entity matching.
    subject_ref: str | None = None
    # Refs of the characters it could be, where it couldn't be tied to one: the
    # author picks (pipeline/claim_links.py). A name several share has them
    # too, as the subject.
    candidates: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)
    evidence: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("subject", "text", "evidence", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("subject_ref", mode="before")
    @classmethod
    def _ref_as_text(cls, value: object) -> object:
        # Anything that isn't a ref is no ref: the claim is matched by name.
        return value.strip() or None if isinstance(value, str) else None

    @field_validator("text", "evidence")
    @classmethod
    def _truncate(cls, value: str | None) -> str | None:
        # A blank evidence reads as none (text can't be blank: min_length).
        return value[:_TEXT_MAX_LENGTH] if value else None

    @field_validator("attributes", mode="before")
    @classmethod
    def _attributes_as_text(cls, value: object) -> object:
        # Values as text (a model may give an age as 17). Something that isn't
        # an object at all loses the attributes, not the claim.
        if not isinstance(value, dict):
            return {}
        return {str(key): str(item).strip()[:ATTR_MAX_LENGTH] for key, item in value.items() if item is not None}

    @model_validator(mode="after")
    def _has_a_subject_or_candidates(self) -> "ExtractedClaim":
        if not self.subject and not self.candidates:
            raise ValueError("A claim needs a subject or the characters it could be")
        return self

    @model_validator(mode="after")
    def _card_keys_only(self) -> "ExtractedClaim":
        # Only the keys a card of this kind has (a location has no eye color), non-empty.
        allowed = _ATTR_KEYS[self.subject_kind]
        self.attributes = {key: value for key, value in self.attributes.items() if key in allowed and value}
        return self


@dataclass
class Extraction:
    claims: list[ExtractedClaim] = field(default_factory=list)
    dropped: int = 0


Recognize = Callable[[list[str]], list[list[NamedEntity]]]
Answer = Callable[[list[tuple[str, str]]], list[str]]

# Around an answer: quotes and sentence punctuation the span can run into.
_VALUE_EDGE = " \t\"'“”‘’「」『』.,!?…~"
_PERSON, _PLACE = "PS", "LC"


@dataclass(frozen=True)
class _Question:
    sentence: int
    # None: a pronoun that fits several characters (candidates)
    subject: rules.Subject | None
    candidates: tuple[rules.Subject, ...]
    # Who the claim is said to be about: the name, or the pronoun
    who: str
    attribute: rules.Attribute | None  # None: a location's features
    question: str
    context: str
    # The clause the cue is in, for reading the value off (context may hold more)
    clause: str
    # Where the answer is read off the sentence, not asked of the QA model
    given: str | None = None

    @property
    def about(self) -> tuple:
        return self.subject.key if self.subject else ("?", *sorted(s.ref or "" for s in self.candidates))


def _clean_value(value: str) -> str:
    return " ".join(value.strip(_VALUE_EDGE).split())


def _mentions(sentences: list[Sentence], registry: rules.Registry, recognize: Recognize) -> list[list[rules.Mention]]:
    """Each sentence's mentions: the registered names and aliases, and the
    names the NER model finds that aren't registered."""
    registered = [registry.mentions(sentence.narration) for sentence in sentences]
    indexes = [i for i, sentence in enumerate(sentences) if sentence.has_narration]
    entities = recognize([sentences[i].narration for i in indexes]) if indexes else []
    named = {i: [e for e in found if e.kind in (_PERSON, _PLACE)] for i, found in zip(indexes, entities, strict=True)}
    # Names seen as they are, for taking particles off the ones that aren't.
    known = registry.strings | {
        rules.normalize(sentences[i].narration[e.start : e.end]) for i, found in named.items() for e in found
    }
    mentions = []
    for i, sentence in enumerate(sentences):
        found = list(registered[i])
        for entity in named.get(i, []):
            if any(entity.start < m.end and m.start < entity.end for m in registered[i]):
                continue
            surface = sentence.narration[entity.start : entity.end]
            stem, particle = rules.split_particle(surface, known)
            name = " ".join(unicodedata.normalize("NFC", stem).split())
            if not 2 <= len(name) <= NAME_MAX_LENGTH or re.search(r"\d", name):
                continue
            subject = registry.resolve(name) or rules.Subject(
                "character" if entity.kind == _PERSON else "location", name
            )
            found.append(
                rules.Mention(
                    entity.start, entity.start + len(stem), subject, particle in "은는이가" and bool(particle)
                )
            )
        mentions.append(sorted(found, key=lambda mention: mention.start))
    return mentions


def _question_parts(
    sentences: list[Sentence],
    mentions: list[list[rules.Mention]],
    index: int,
    owner: rules.Subject,
    clause: tuple[int, int],
    clause_text: str,
) -> tuple[str, str]:
    """(who the question names, the context it's asked over).

    The QA model answers "no answer" to a question about a person its context
    doesn't mention (ml/extraction/RESULTS.md round 2). So the question names the
    owner as the clause writes it ("철수형", "공주") where the clause does; and
    where the clause only refers to it ("그녀의 은빛 머리카락이"), puts its
    name in for the pronoun and reads it after the nearest of the
    sentences before that names it."""
    narration = sentences[index].narration
    before = None
    for mention in mentions[index]:
        if mention.subject.key != owner.key:
            continue
        if clause[0] <= mention.start and mention.end <= clause[1]:
            return narration[mention.start : mention.end], clause_text
        if mention.end <= clause[0]:
            before = mention
    if rules.points_elsewhere(clause_text, owner.pronoun):
        # "그녀의 눈" of a male character: the sentences before would only make the
        # model read it as his.
        return owner.name, clause_text
    if before is not None:
        # Named earlier in the sentence ("레온이 웃자 붉은 눈이 번뜩였다"): read from there.
        return narration[before.start : before.end], " ".join(narration[: clause[1]].split())
    context = rules.name_for_pronoun(clause_text, owner.name, owner.pronoun)
    for back in range(1, rules.CONTEXT_SENTENCES + 1):
        earlier = index - back
        if earlier >= 0 and any(mention.subject.key == owner.key for mention in mentions[earlier]):
            return owner.name, " ".join(sentences[earlier].narration.split()) + " " + context
    return owner.name, context


def _questions(sentences: list[Sentence], mentions: list[list[rules.Mention]]) -> list[_Question]:
    questions: list[_Question] = []
    seen: set[tuple] = set()
    for i, sentence in enumerate(sentences):
        if not sentence.has_narration:
            continue
        narration = sentence.narration
        for hit in rules.cue_hits(narration):
            owner = rules.owner(sentences, mentions, i, hit)
            if owner is None:
                continue
            if isinstance(owner, rules.Ambiguous):
                subject, candidates, who = None, owner.subjects, "그녀" if owner.kind == "she" else "그"
            else:
                subject, candidates, who = owner, (), owner.name
            clause_text = " ".join(narration[hit.clause[0] : hit.clause[1]].split())
            asked, context = who, clause_text
            if subject is not None:
                asked, context = _question_parts(sentences, mentions, i, subject, hit.clause, clause_text)
            question = _Question(
                i, subject, candidates, who, hit.attribute, f"{asked}의 {hit.attribute.label}?", context, clause_text
            )  # fmt: skip
            key = (i, question.about, hit.attribute.key)
            if key in seen:
                continue
            seen.add(key)
            questions.append(question)
        for mention in mentions[i]:
            key = (i, mention.subject.key, "features")
            # A place the sentence is about, not one a character is said to be at.
            if mention.subject.kind != "location" or not mention.topic or key in seen:
                continue
            features = rules.features_of(sentence, mention, mentions[i])
            if features:
                seen.add(key)
                name = mention.subject.name
                questions.append(_Question(i, mention.subject, (), name, None, "", "", "", given=features))
    return questions


def extract_claims(
    novel_id: uuid.UUID,
    manuscript: str,
    known_characters: list[dict],
    known_locations: list[str],
    *,
    recognize: Recognize | None = None,
    answer: Answer | None = None,
) -> Extraction:
    """recognize / answer: the NER and QA models (ai/nli_rerank.py, which
    raises InferenceError where they can't run); tests give their own."""
    recognize = recognize or nli_rerank.recognize_entities
    answer = answer or nli_rerank.answer_questions
    sentences = split_sentences(unicodedata.normalize("NFC", manuscript))
    registry = rules.Registry(known_characters, known_locations)
    mentions = _mentions(sentences, registry, recognize)
    questions = _questions(sentences, mentions)
    asked = [q for q in questions if q.given is None]
    raw_answers = answer([(q.question, q.context) for q in asked]) if asked else []
    if len(raw_answers) != len(asked):
        raise ValueError(f"{len(raw_answers)} answers for {len(asked)} questions")
    answers = iter(raw_answers)

    # One claim per sentence and subject, with all it says about the subject.
    grouped: dict[tuple, tuple[_Question, dict[str, str], list[str]]] = {}
    for question in questions:
        value = _clean_value(next(answers) if question.given is None else question.given)
        if question.attribute is None:
            key, valid = "features", len(value) >= 2
            statement = location_statement(question.who, value)
        else:
            value = rules.value_of(question.attribute, value, question.clause)
            # The context can hold the sentences before the clause: an answer from
            # them (a cloak's color, an earlier age) isn't the clause's.
            key, valid = question.attribute.key, bool(value) and value in question.clause
            statement = character_statement(question.who, key, value)
        if not valid:
            continue
        _, attributes, statements = grouped.setdefault((question.sentence, question.about), (question, {}, []))
        attributes[key] = value
        statements.append(statement)

    extraction = Extraction()
    for question, attributes, statements in grouped.values():
        subject = question.subject
        if subject is None:  # a pronoun that fits several characters
            kind, name, ref, candidates = "character", "", None, [s.ref for s in question.candidates if s.ref]
        else:
            kind, name, ref, candidates = subject.kind, subject.name, subject.ref, list(subject.candidates)
        try:
            extraction.claims.append(
                ExtractedClaim(
                    claim_type="appearance" if kind == "character" else "location",
                    subject_kind=kind,
                    subject=name,
                    subject_ref=ref,
                    candidates=candidates,
                    text=" ".join(statements),
                    evidence=sentences[question.sentence].text,
                    attributes=attributes,
                )
            )
        except ValidationError:
            extraction.dropped += 1
    logger.info(
        "Novel %s: %d sentence(s), %d question(s), %d claim(s)",
        novel_id, len(sentences), len(asked), len(extraction.claims),
    )  # fmt: skip
    if extraction.dropped:
        logger.warning(
            "Novel %s: dropped %d malformed claim(s), kept %d", novel_id, extraction.dropped, len(extraction.claims)
        )
    return extraction
