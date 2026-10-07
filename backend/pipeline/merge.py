"""Result merging and auto-apply (design doc 7.1, 7.3, 7.4).

- merge_and_dedupe: merges the results of the judgment modules and removes
  duplicate detections of the same underlying error
- apply_new_information: what the episode says that doesn't contradict
  anything goes into the settings (7.4) — strictly adding: a card attribute
  that's still empty is filled in, and the characters' mutable attributes
  (hairstyle, outfit, ...) are recorded in character_state_history for this
  episode, and a location's changes of state ("폐허가 되었다") in
  location_state_history. An attribute the card already has is never changed
  here, flagged or not: changing an existing setting is the author's call
  (2.4). The one
  exception is a value filled in from this same episode by an earlier run:
  that's the episode's own earlier wording, and the new wording replaces it —
  or, once the sentence it was taken from is gone from the episode, the value
  is cleared, so text the author removed isn't held against other episodes.
  (Only then: a run whose extraction merely missed it this time keeps it.) It
  is cleared too when a location's value came from a sentence that is now read
  as a change of state, which belongs in location_state_history, not the card.
"""

import uuid

from sqlalchemy import Text, cast, delete, or_, select
from sqlalchemy.orm import Session

from models.character import (
    FIXED_ATTR_KEYS,
    MUTABLE_ATTR_KEYS,
    Character,
    CharacterStateHistory,
)
from models.location import (
    GEO_ATTR_KEYS,
    STATE_ATTR_KEYS,
    Location,
    LocationStateHistory,
)
from pipeline.context_bundle import source_episodes
from pipeline.entities import comparable_text
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


def _gone_from(record: dict, content: str) -> bool:
    """Whether the manuscript sentence a value was taken from is no longer in
    the episode. Without a recorded sentence there's no telling, and the value
    is kept."""
    evidence = comparable_text(record.get("evidence") or "")
    return bool(evidence) and evidence not in comparable_text(content)


def _now_a_state(record: dict, state_evidence: set[str]) -> bool:
    """Whether the sentence a value was taken from is now read as a change of
    state: an earlier run took it for a feature, and it stays on the card
    otherwise, the sentence being still in the episode."""
    evidence = comparable_text(record.get("evidence") or "")
    return bool(evidence) and evidence in state_evidence


def apply_new_information(
    db: Session,
    novel_id: uuid.UUID,
    episode_id: uuid.UUID,
    episode_index: int,
    content: str,
    claims: list[ExtractedClaim],
    subject_ids: list[uuid.UUID | None],
    flags: list[Flag],
) -> None:
    """subject_ids[i] is claims[i]'s character/location, None where entity
    matching couldn't tell which (pipeline/entities.py): such a claim adds
    nothing. The caller holds the novel's row lock, so the cards read here are
    the ones being written."""
    flagged = {(flag.claim_index, flag.attribute) for flag in flags}
    # A feature held against the place's state is no setting to add either.
    flagged |= {(flag.claim_index, key) for flag in flags if flag.attribute in STATE_ATTR_KEYS for key in GEO_ATTR_KEYS}
    source = str(episode_id)
    # Cards entity matching just created go in first: the state history
    # below references them.
    db.flush()

    # (kind, id) -> {key: (value, evidence)}, first mention in the episode wins
    card_values: dict[tuple[str, uuid.UUID], dict[str, tuple[str, str | None]]] = {}
    states: dict[uuid.UUID, dict[str, str]] = {}
    location_states: dict[uuid.UUID, dict[str, str]] = {}
    # The sentences (comparable) the episode's location claims say as a state.
    state_evidence: dict[uuid.UUID, set[str]] = {}
    for index, (claim, subject_id) in enumerate(zip(claims, subject_ids, strict=True)):
        if subject_id is None:
            continue
        card_keys = FIXED_ATTR_KEYS if claim.subject_kind == "character" else GEO_ATTR_KEYS
        for key, value in claim.attributes.items():
            if key in card_keys and (index, key) not in flagged:
                # The sentence as the manuscript has it — not the claim's
                # restatement, which the manuscript never contains.
                card_values.setdefault((claim.subject_kind, subject_id), {}).setdefault(key, (value, claim.evidence))
            elif claim.subject_kind == "character" and key in MUTABLE_ATTR_KEYS:
                states.setdefault(subject_id, {}).setdefault(key, value)
            elif claim.subject_kind == "location" and key in STATE_ATTR_KEYS:
                # The last one the episode says: the state it leaves the place in.
                location_states.setdefault(subject_id, {})[key] = value
                if claim.evidence:
                    state_evidence.setdefault(subject_id, set()).add(comparable_text(claim.evidence))

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
            reclassified = state_evidence.get(card.id, set()) if kind == "location" else set()
            for key, from_episode in from_episodes.items():
                if (
                    from_episode == source
                    and key not in values
                    and (_gone_from(sources[key], content) or _now_a_state(sources[key], reclassified))
                ):
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
    # (Deleting a location, once there is a way to, deletes these rows first, as
    # api/settings.py's delete_character does the character's.)
    db.execute(
        delete(LocationStateHistory).where(
            LocationStateHistory.novel_id == novel_id, LocationStateHistory.episode_index == episode_index
        )
    )
    db.add_all(
        LocationStateHistory(novel_id=novel_id, location_id=location_id, episode_index=episode_index, state=state)
        for location_id, state in location_states.items()
    )
