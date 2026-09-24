"""Result merging and auto-apply (design doc 7.1, 7.3, 7.4).

- merge_and_dedupe: merges the results of the judgment modules and removes
  duplicate detections of the same underlying error
- apply_new_information: what the episode says that doesn't contradict
  anything goes into the settings (7.4) — strictly adding: a card attribute
  that's still empty is filled in, and the characters' mutable attributes
  (hairstyle, outfit, ...) are recorded in character_state_history for this
  episode. An attribute the card already has is never changed here, flagged
  or not: changing an existing setting is the author's call (2.4). The one
  exception is a value filled in from this same episode by an earlier run:
  that's the episode's own earlier wording, and the new wording replaces it —
  or, once the sentence it was taken from is gone from the episode, the value
  is cleared, so text the author removed isn't held against other episodes.
  (Only then: a run whose extraction merely missed it this time keeps it.)
"""

import re
import uuid

from sqlalchemy import Text, cast, delete, or_, select
from sqlalchemy.orm import Session

from models.character import (
    FIXED_ATTR_KEYS,
    MUTABLE_ATTR_KEYS,
    Character,
    CharacterStateHistory,
)
from models.location import GEO_ATTR_KEYS, Location
from pipeline.context_bundle import source_episodes
from pipeline.entities import normalize_name
from pipeline.extract_claims import ExtractedClaim
from pipeline.judges import Flag


def merge_and_dedupe(flags_by_module: list[list[Flag]]) -> list[Flag]:
    """One flag per subject, attribute and manuscript sentence — the model may
    make two claims of one sentence — keeping the most confident, and the
    result sorted by confidence (2.5)."""
    best: dict[tuple, Flag] = {}
    for flag in (flag for flags in flags_by_module for flag in flags):
        key = (flag.subject_id, flag.attribute, flag.evidence_text)
        if key not in best or flag.confidence > best[key].confidence:
            best[key] = flag
    return sorted(best.values(), key=lambda flag: flag.confidence, reverse=True)


# What's compared of a sentence: letters and digits only, so a copy that
# differs in spacing, quotes or punctuation is still the same sentence.
_NOT_WORD = re.compile(r"[\W_]+")


def _words(text: str) -> str:
    return _NOT_WORD.sub("", normalize_name(text))


def _gone_from(record: dict, content: str) -> bool:
    """Whether the manuscript sentence a value was taken from is no longer in
    the episode. Without a recorded sentence there's no telling, and the value
    is kept."""
    evidence = _words(record.get("evidence") or "")
    return bool(evidence) and evidence not in _words(content)


def apply_new_information(
    db: Session,
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    episode_index: int,
    content: str,
    claims: list[ExtractedClaim],
    subject_ids: list[uuid.UUID],
    flags: list[Flag],
) -> None:
    """subject_ids[i] is claims[i]'s character/location. The caller holds the
    novel's row lock, so the cards read here are the ones being written."""
    flagged = {(flag.claim_index, flag.attribute) for flag in flags}
    source = str(episode_id)
    # Cards entity matching just created go in first: the state history
    # below references them.
    db.flush()

    # (kind, id) -> {key: (value, evidence)}, first mention in the episode wins
    card_values: dict[tuple[str, uuid.UUID], dict[str, tuple[str, str | None]]] = {}
    states: dict[uuid.UUID, dict[str, str]] = {}
    for index, (claim, subject_id) in enumerate(zip(claims, subject_ids, strict=True)):
        card_keys = FIXED_ATTR_KEYS if claim.subject_kind == "character" else GEO_ATTR_KEYS
        for key, value in claim.attributes.items():
            if key in card_keys and (index, key) not in flagged:
                # The sentence as the manuscript has it — not the claim's
                # restatement, which the manuscript never contains.
                card_values.setdefault((claim.subject_kind, subject_id), {}).setdefault(key, (value, claim.evidence))
            elif claim.subject_kind == "character" and key in MUTABLE_ATTR_KEYS:
                states.setdefault(subject_id, {}).setdefault(key, value)

    for model, attrs_field, kind in ((Character, "fixed_attrs", "character"), (Location, "geo_attrs", "location")):
        ids = [subject_id for (card_kind, subject_id) in card_values if card_kind == kind]
        # The cards this episode says something about, and those with a value
        # an earlier run of it filled in (its id among attr_sources' values).
        for card in db.scalars(
            select(model).where(
                model.novel_id == novel_id,
                or_(model.id.in_(ids), cast(model.attr_sources, Text).contains(source)),
            )
        ):
            attrs = dict(getattr(card, attrs_field) or {})
            sources = dict(card.attr_sources or {})
            from_episodes = source_episodes(sources)
            values = card_values.get((kind, card.id), {})
            for key, from_episode in from_episodes.items():
                if from_episode == source and key not in values and _gone_from(sources[key], content):
                    attrs.pop(key, None)
                    del sources[key]
            for key, (value, evidence) in values.items():
                # Empty, or filled in from this same episode's earlier wording.
                if not attrs.get(key) or from_episodes.get(key) == source:
                    attrs[key] = value
                    sources[key] = {"episode_id": source, "evidence": evidence}
            # Reassigned, not mutated: SQLAlchemy doesn't see changes inside a JSONB value.
            setattr(card, attrs_field, attrs)
            card.attr_sources = sources

    # This episode's state replaces what an earlier run of it recorded.
    db.execute(
        delete(CharacterStateHistory).where(
            CharacterStateHistory.novel_id == novel_id, CharacterStateHistory.episode_index == episode_index
        )
    )
    db.add_all(
        CharacterStateHistory(novel_id=novel_id, character_id=character_id, episode_index=episode_index, state=state)
        for character_id, state in states.items()
    )
