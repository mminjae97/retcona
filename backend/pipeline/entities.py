"""Entity matching and auto-registration (design doc 7.4).

Each claim's subject is matched against the novel's characters/locations
(resolve_subjects, then match_and_register). Characters can share a name
(two people called 김철수, told apart by their aliases, api/settings.py), so
the extraction step gives the model each known character with a ref, its
name and its aliases, and the model answers with the ref of the one it means
(pipeline/extract_claims.py) — used only where the name it gives is that
character's name or alias. A claim with no usable ref is matched by name,
then by alias; a name that fits more than one character is ambiguous and the
claim is left unlinked — neither guessed at nor made a new card. Locations go
by name (where two share one, the oldest). Embedding similarity (chapter 5)
isn't used yet.

A subject with no match becomes a new card, source=auto_detected. Its fixed
attributes / features are filled in afterwards like any card's empty ones
(pipeline/merge.py); its current state (mutable attributes) is taken from
what this episode's claims say about it (the first mention of each key wins).
What a claim says about an existing card is for the judgment modules to
compare, not to write over it (7.4: changes to existing settings go through
the author).

The caller holds the novel's row lock (FOR UPDATE), which serializes this with
the settings screen's writes and with other runs on the same novel — two
episodes of one novel validated at once can't both create the same character.
"""

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from models.character import MUTABLE_ATTR_KEYS, Character
from models.location import Location
from pipeline.extract_claims import ExtractedClaim


def normalize_name(name: str) -> str:
    # NFC so a name typed on one keyboard matches the same name from the model;
    # whitespace collapsed and case folded, so "레온 하트" / "레온  하트" and
    # "Leon" / "leon" are one entity.
    return " ".join(unicodedata.normalize("NFC", name).split()).casefold()


_NOT_WORD = re.compile(r"[\W_]+")


def comparable_text(text: str) -> str:
    # Letters and digits only: the model's copy of a manuscript sentence may
    # differ from the manuscript (and between runs) in spacing, quotes or
    # punctuation, and is still the same sentence.
    return _NOT_WORD.sub("", normalize_name(text))


class Match(NamedTuple):
    card_id: uuid.UUID | None
    # More than one card fits the name: the claim is left unlinked.
    ambiguous: bool = False


class _Cards:
    """The novel's cards as claims name them, read once."""

    def __init__(self, db: Session, novel_id: uuid.UUID) -> None:
        self.character_names: dict[uuid.UUID, str] = {}
        # id -> its name and aliases, normalized
        self.known_as: dict[uuid.UUID, set[str]] = {}
        self.by_name: dict[str, list[uuid.UUID]] = {}
        self.by_alias: dict[str, list[uuid.UUID]] = {}
        for character in db.scalars(
            select(Character).where(Character.novel_id == novel_id).order_by(Character.created_at, Character.id)
        ):
            self.character_names[character.id] = character.name
            self.by_name.setdefault(normalize_name(character.name), []).append(character.id)
            aliases = {normalize_name(alias) for alias in character.aliases or []}
            for alias in aliases:
                self.by_alias.setdefault(alias, []).append(character.id)
            self.known_as[character.id] = {normalize_name(character.name), *aliases}
        # Oldest first, so where two locations share a name (nothing stops the
        # author from making both), claims keep going to the same, first one.
        self.locations: dict[str, uuid.UUID] = {}
        self.location_ids: set[uuid.UUID] = set()
        locations = db.execute(
            select(Location.id, Location.name)
            .where(Location.novel_id == novel_id)
            .order_by(Location.created_at, Location.id)
        )
        for location_id, name in locations:
            self.locations.setdefault(normalize_name(name), location_id)
            self.location_ids.add(location_id)

    def exists(self, kind: str, card_id: uuid.UUID) -> bool:
        return card_id in (self.character_names if kind == "character" else self.location_ids)

    def find(self, claim: ExtractedClaim, refs: dict[str, uuid.UUID]) -> Match:
        key = normalize_name(claim.subject)
        if claim.subject_kind == "location":
            return Match(self.locations.get(key))
        # The ref only where the name the model gave is that character's name
        # or alias, as it's asked to give: a model that put a character's ref
        # on another (a new character) mustn't hold that one against this
        # card's settings, or fill them in. A dropped ref falls back to the
        # name, as with none.
        ref = refs.get(claim.subject_ref or "")
        if ref is not None and key in self.known_as.get(ref, set()):
            return Match(ref)
        for candidates in (self.by_name.get(key), self.by_alias.get(key)):
            if candidates:
                return Match(candidates[0]) if len(candidates) == 1 else Match(None, ambiguous=True)
        return Match(None)


def resolve_subjects(
    db: Session, novel_id: uuid.UUID, claims: list[ExtractedClaim], refs: dict[str, uuid.UUID]
) -> list[Match]:
    """The card each claim is about, as the novel's cards are now. refs: the
    refs the extraction prompt gave the characters -> their card ids. A claim
    about a character found is named by the character's name from here on
    (the model may have used an alias)."""
    cards = _Cards(db, novel_id)
    matches = [cards.find(claim, refs) for claim in claims]
    for claim, match in zip(claims, matches, strict=True):
        if claim.subject_kind == "character" and match.card_id is not None:
            claim.subject = cards.character_names[match.card_id]
    return matches


@dataclass
class Registration:
    # subject_ids[i]: claims[i]'s card, None where it was ambiguous
    subject_ids: list[uuid.UUID | None] = field(default_factory=list)
    new_characters: list[str] = field(default_factory=list)
    new_locations: list[str] = field(default_factory=list)


def _initial_attrs(claims: list[ExtractedClaim], keys: tuple[str, ...]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for claim in claims:
        for key, value in claim.attributes.items():
            if key in keys:
                attrs.setdefault(key, value)
    return attrs


def match_and_register(
    db: Session, novel_id: uuid.UUID, claims: list[ExtractedClaim], matches: list[Match]
) -> Registration:
    """matches: resolve_subjects' result, from before the judgment. A card
    it found that has since been deleted, or a subject it found none for, is
    looked up again by name now; one still with no card becomes a new one."""
    cards = _Cards(db, novel_id)
    registration = Registration(subject_ids=[None] * len(claims))
    unmatched: dict[tuple[str, str], list[int]] = {}
    for index, (claim, match) in enumerate(zip(claims, matches, strict=True)):
        if match.card_id is not None and cards.exists(claim.subject_kind, match.card_id):
            registration.subject_ids[index] = match.card_id
            continue
        if match.ambiguous:
            continue
        found = cards.find(claim, {})
        if found.card_id is not None:
            registration.subject_ids[index] = found.card_id
        elif not found.ambiguous:
            unmatched.setdefault((claim.subject_kind, normalize_name(claim.subject)), []).append(index)

    for (kind, _), indexes in unmatched.items():
        subject_claims = [claims[index] for index in indexes]
        # The name as the manuscript first wrote it, not the normalized form.
        name = subject_claims[0].subject
        entity_id = uuid.uuid4()
        if kind == "character":
            entity = Character(
                id=entity_id,
                novel_id=novel_id,
                name=name,
                source="auto_detected",
                fixed_attrs={},
                # A new card has no earlier state to contradict, so its
                # current state starts from this episode too.
                mutable_attrs=_initial_attrs(subject_claims, MUTABLE_ATTR_KEYS),
                personality={},
            )
            registration.new_characters.append(name)
        else:
            entity = Location(id=entity_id, novel_id=novel_id, name=name, source="auto_detected", geo_attrs={})
            registration.new_locations.append(name)
        db.add(entity)
        for index in indexes:
            registration.subject_ids[index] = entity_id
    return registration
