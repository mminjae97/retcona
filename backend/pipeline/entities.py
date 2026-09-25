"""Entity matching and auto-registration (design doc 7.4).

Each claim's subject is matched against the novel's characters/locations by
name. Aliases are resolved before this, by the extraction step: the model is
given the known names and answers with them (pipeline/extract_claims.py).
Embedding similarity (chapter 5) isn't used yet.

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


@dataclass
class Registration:
    # (subject_kind, normalized name) -> the matched or created entity's id
    ids: dict[tuple[str, str], uuid.UUID] = field(default_factory=dict)
    new_characters: list[str] = field(default_factory=list)
    new_locations: list[str] = field(default_factory=list)

    def subject_id(self, claim: ExtractedClaim) -> uuid.UUID:
        return self.ids[(claim.subject_kind, normalize_name(claim.subject))]


def _initial_attrs(claims: list[ExtractedClaim], keys: tuple[str, ...]) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for claim in claims:
        for key, value in claim.attributes.items():
            if key in keys:
                attrs.setdefault(key, value)
    return attrs


def match_and_register(db: Session, novel_id: uuid.UUID, claims: list[ExtractedClaim]) -> Registration:
    registration = Registration()
    # Oldest first, so where two locations share a name (nothing stops the
    # author from making both), claims keep going to the same, first one.
    for character in db.scalars(
        select(Character).where(Character.novel_id == novel_id).order_by(Character.created_at, Character.id)
    ):
        registration.ids.setdefault(("character", normalize_name(character.name)), character.id)
    for location in db.scalars(
        select(Location).where(Location.novel_id == novel_id).order_by(Location.created_at, Location.id)
    ):
        registration.ids.setdefault(("location", normalize_name(location.name)), location.id)

    unmatched: dict[tuple[str, str], list[ExtractedClaim]] = {}
    for claim in claims:
        key = (claim.subject_kind, normalize_name(claim.subject))
        if key not in registration.ids:
            unmatched.setdefault(key, []).append(claim)

    for (kind, normalized), subject_claims in unmatched.items():
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
        registration.ids[(kind, normalized)] = entity_id
    return registration
