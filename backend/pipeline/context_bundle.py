"""Shared context lookup (design doc 7.1, 7.3).

Instead of each judgment module (appearance/behavior, location, spacetime)
querying the DB separately, they share the context bundle this function
assembles once (avoids context silos, 7.3).

Today the bundle is the setting cards of the characters/locations the
episode's claims are about, as entity matching found them
(pipeline/entities.py resolve_subjects). The appearance and location judgments compare a
claim with its card's attributes key by key, so the card is all they need.
Narrowing past settings and state history down by similarity (pgvector +
reranker, chapter 5) comes with the modules that read free text: behavior
(OOC) and spacetime.

novel_id is a required argument, passed through unchanged to every underlying query (10.1).
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.character import Character
from models.location import Location
from pipeline.entities import Match


@dataclass(frozen=True)
class Card:
    kind: str  # character | location
    id: uuid.UUID
    name: str
    # fixed_attrs of a character, geo_attrs of a location
    attrs: dict[str, str]
    # {key: the episode id it was filled in from}, from attr_sources
    sources: dict[str, str]


@dataclass
class ContextBundle:
    # The episode being validated: a card value filled in from it is its own
    # earlier wording, not a setting to hold it to (models/character.py).
    episode_id: uuid.UUID
    # claims[i]'s card, None for a subject with no card yet (or ambiguous)
    claim_cards: list[Card | None] = field(default_factory=list)

    def card_for(self, claim_index: int) -> Card | None:
        return self.claim_cards[claim_index]


def _text_values(attrs: object) -> dict[str, str]:
    # Values as text, blanks dropped: what's stored may be anything JSON.
    if not isinstance(attrs, dict):
        return {}
    return {str(key): str(value).strip() for key, value in attrs.items() if value is not None and str(value).strip()}


def source_episodes(attr_sources: object) -> dict[str, str]:
    """{key: episode id} of a card's attr_sources (models/character.py)."""
    if not isinstance(attr_sources, dict):
        return {}
    return {
        str(key): str(record["episode_id"])
        for key, record in attr_sources.items()
        if isinstance(record, dict) and record.get("episode_id")
    }


def get_context_bundle(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, matches: list[Match]) -> ContextBundle:
    """matches[i]: claims[i]'s card, from resolve_subjects."""
    wanted = {match.card_id for match in matches if match.card_id is not None}
    cards: dict[uuid.UUID, Card] = {}
    for character in db.scalars(select(Character).where(Character.novel_id == novel_id, Character.id.in_(wanted))):
        cards[character.id] = Card(
            kind="character",
            id=character.id,
            name=character.name,
            attrs=_text_values(character.fixed_attrs),
            sources=source_episodes(character.attr_sources),
        )
    for location in db.scalars(select(Location).where(Location.novel_id == novel_id, Location.id.in_(wanted))):
        cards[location.id] = Card(
            kind="location",
            id=location.id,
            name=location.name,
            attrs=_text_values(location.geo_attrs),
            sources=source_episodes(location.attr_sources),
        )
    return ContextBundle(
        episode_id=episode_id,
        claim_cards=[cards.get(match.card_id) if match.card_id is not None else None for match in matches],
    )
