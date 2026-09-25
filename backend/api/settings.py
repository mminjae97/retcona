"""World and character setting cards (design doc 2.3, 4.3).

Both are optional, author-entered context for the validation pipeline: world
settings are a category + title + free-form description; a character card is
a name and aliases plus three sections — fixed attributes, mutable attributes, and
personality/speech (the last one is what OOC judgment reads, 7.2). Cards left
unwritten are meant to be filled in from the manuscript later
(source=auto_detected, 7.4); editing one here makes it the author's
(source=manual).

Every write locks the novel row first, for the same reason as the novel and
episode endpoints: a concurrent soft-delete of the novel can't land between
this request's ownership check and its commit (10.1). The same lock also
serializes the duplicate name/alias check on characters.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session

from api.deps import get_owned_novel as _get_owned_novel
from auth.dependencies import get_current_user
from models.character import Character, CharacterStateHistory
from models.claim import Claim
from models.db import get_db
from models.relation import Relation
from models.story_event import EventParticipant
from models.user import User
from models.world_setting import WorldSetting
from pipeline.dismissals import rename_subject
from pipeline.entities import normalize_name

router = APIRouter()

# 2.3: era/setting, magic·martial-arts system, faction/organization, history,
# other rules. Stored as these codes; the frontend owns the Korean labels.
WorldCategory = Literal["era", "power_system", "faction", "history", "other"]

_ATTR_MAX_LENGTH = 500
_NAME_MAX_LENGTH = 100
_ALIASES_MAX = 20


def _strip_required(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Must not be blank")
    return value


# ---------------------------------------------------------------- world settings


class WorldSettingInput(BaseModel):
    category: WorldCategory
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _strip_required(value)


class WorldSettingPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    category: str
    title: str
    content: str
    created_at: datetime


def _get_world_setting(db: Session, novel_id: uuid.UUID, setting_id: uuid.UUID) -> WorldSetting:
    setting = db.scalar(select(WorldSetting).where(WorldSetting.id == setting_id, WorldSetting.novel_id == novel_id))
    if setting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "World setting not found")
    return setting


@router.get("/{novel_id}/world-settings", response_model=list[WorldSettingPublic])
def list_world_settings(
    novel_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[WorldSetting]:
    _get_owned_novel(db, novel_id, user)
    return list(
        db.scalars(
            select(WorldSetting)
            .where(WorldSetting.novel_id == novel_id)
            .order_by(WorldSetting.created_at, WorldSetting.id)
        )
    )


@router.post("/{novel_id}/world-settings", response_model=WorldSettingPublic, status_code=status.HTTP_201_CREATED)
def create_world_setting(
    novel_id: uuid.UUID,
    body: WorldSettingInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorldSetting:
    _get_owned_novel(db, novel_id, user, for_update=True)
    setting = WorldSetting(novel_id=novel_id, **body.model_dump())
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


@router.put("/{novel_id}/world-settings/{setting_id}", response_model=WorldSettingPublic)
def update_world_setting(
    novel_id: uuid.UUID,
    setting_id: uuid.UUID,
    body: WorldSettingInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorldSetting:
    _get_owned_novel(db, novel_id, user, for_update=True)
    setting = _get_world_setting(db, novel_id, setting_id)
    for field, value in body.model_dump().items():
        setattr(setting, field, value)
    db.commit()
    db.refresh(setting)
    return setting


@router.delete("/{novel_id}/world-settings/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_world_setting(
    novel_id: uuid.UUID,
    setting_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _get_owned_novel(db, novel_id, user, for_update=True)
    db.delete(_get_world_setting(db, novel_id, setting_id))
    db.commit()


# ---------------------------------------------------------------- characters


class _AttrSection(BaseModel):
    # Known fields only (2.3), each optional free text. Blank means "not set"
    # and isn't stored, so an empty card stays an empty JSON object — the
    # "fill it in from the manuscript" state (7.4). An unknown key in a request
    # is rejected rather than dropped, so a client-side typo can't silently
    # lose what the author typed.
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    def stored(self) -> dict[str, str]:
        return {key: value for key, value in self.model_dump().items() if value is not None}


class FixedAttrs(_AttrSection):
    age: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    eye_color: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    hair_color: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    height: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    scars: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    origin: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)


class MutableAttrs(_AttrSection):
    hairstyle: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    outfit: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    condition: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)  # injury/health
    belongings: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)


class Personality(_AttrSection):
    keywords: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    speech: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)
    goals: str | None = Field(None, max_length=_ATTR_MAX_LENGTH)  # goals/values


class CharacterInput(BaseModel):
    name: str = Field(min_length=1, max_length=_NAME_MAX_LENGTH)
    # Other names the manuscript calls it by (models/character.py).
    aliases: list[str] = Field(default_factory=list, max_length=_ALIASES_MAX)
    fixed_attrs: FixedAttrs = Field(default_factory=lambda: FixedAttrs())
    mutable_attrs: MutableAttrs = Field(default_factory=lambda: MutableAttrs())
    personality: Personality = Field(default_factory=lambda: Personality())

    @field_validator("name")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, value: list[str]) -> list[str]:
        # Blank ones dropped, and one of each as matching compares them.
        cleaned: dict[str, str] = {}
        for alias in value:
            alias = alias.strip()
            if len(alias) > _NAME_MAX_LENGTH:
                raise ValueError(f"An alias can be at most {_NAME_MAX_LENGTH} characters")
            if alias:
                cleaned.setdefault(normalize_name(alias), alias)
        return list(cleaned.values())

    @model_validator(mode="after")
    def _aliases_other_than_name(self) -> "CharacterInput":
        name = normalize_name(self.name)
        self.aliases = [alias for alias in self.aliases if normalize_name(alias) != name]
        return self


class CharacterPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    name: str
    aliases: list[str]
    source: str  # manual | auto_detected
    fixed_attrs: FixedAttrs
    mutable_attrs: MutableAttrs
    personality: Personality
    created_at: datetime

    @field_validator("aliases", mode="before")
    @classmethod
    def _stored_aliases(cls, value: object) -> object:
        return [str(alias) for alias in value] if isinstance(value, list) else []

    @field_validator("fixed_attrs", "mutable_attrs", "personality", mode="before")
    @classmethod
    def _stored_to_section(cls, value: object, info: ValidationInfo) -> object:
        # What's stored may come from the auto-detection pass (7.4) too: keys
        # this card doesn't show are left out, and non-string values read as
        # text (an age detected as 17, keywords as a list), rather than
        # failing the whole list.
        if not isinstance(value, dict):
            return value
        known = cls.model_fields[info.field_name].annotation.model_fields
        return {key: _as_text(item) for key, item in value.items() if key in known and item is not None}


def _as_text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value)


def _get_character(db: Session, novel_id: uuid.UUID, character_id: uuid.UUID) -> Character:
    character = db.scalar(select(Character).where(Character.id == character_id, Character.novel_id == novel_id))
    if character is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Character not found")
    return character


def _names(name: str, aliases: list[str]) -> set[str]:
    # A card's names as matching and dismissals compare them (normalized:
    # "Leon" and "leon" are one name).
    return {normalize_name(each) for each in [name, *aliases]}


def _reject_taken_names(
    db: Session, novel_id: uuid.UUID, names: set[str], *, except_id: uuid.UUID | None = None
) -> None:
    # One card per name within a novel, aliases included: entity matching
    # (7.4) looks characters up by them, and two cards with the same one would
    # split what the manuscript says about that character between them. A
    # novel has tens of characters at most, so they're compared here rather
    # than in SQL. Race-free because every caller holds the novel's row lock.
    # Renaming and adding aliases rely on this: a name's dismissals and
    # unlinked claims belong to the one card by that name (_take_over_names).
    if not names:
        return
    others = db.execute(
        select(Character.id, Character.name, Character.aliases).where(Character.novel_id == novel_id)
    )
    if any(other_id != except_id and names & _names(name, aliases or []) for other_id, name, aliases in others):
        raise HTTPException(status.HTTP_409_CONFLICT, "A character with this name or alias already exists")


def _take_over_names(
    db: Session, novel_id: uuid.UUID, character_id: uuid.UUID | None, old_names: list[str], name: str
) -> None:
    # Later runs name the character by its name (extraction answers with it,
    # aliases resolved to it), so what was recorded under its old name, or
    # under a name it now has as an alias (a card by that name, since
    # deleted), follows: the dismissals, its own claims, and the unlinked
    # claims by those names — each claim's flags must still find their
    # dismissals to reopen them. Unlinked claims are few; compared here, as
    # names are normalized.
    for old_name in old_names:
        rename_subject(db, novel_id, "character", old_name, name)
    old = {normalize_name(old_name) for old_name in old_names}
    unlinked = [
        claim_id
        for claim_id, subject_name in db.execute(
            select(Claim.id, Claim.subject_name).where(
                Claim.novel_id == novel_id, Claim.subject_kind == "character", Claim.subject_id.is_(None)
            )
        )
        if normalize_name(subject_name or "") in old
    ]
    # A card being created has no claims of its own yet (and `== None` would
    # match every unlinked claim).
    claims = Claim.id.in_(unlinked)
    if character_id is not None:
        claims = or_(Claim.subject_id == character_id, claims)
    db.execute(
        update(Claim)
        .where(Claim.novel_id == novel_id, Claim.subject_kind == "character", claims)
        .values(subject_name=name)
    )


def _apply(character: Character, body: CharacterInput) -> None:
    fixed_attrs = body.fixed_attrs.stored()
    # A value the author changed or cleared is theirs now, no longer the
    # episode's it was filled in from (models/character.py).
    previous = character.fixed_attrs or {}
    character.attr_sources = {
        key: record
        for key, record in (character.attr_sources or {}).items()
        if fixed_attrs.get(key) == previous.get(key)
    }
    character.name = body.name
    character.aliases = body.aliases
    character.fixed_attrs = fixed_attrs
    character.mutable_attrs = body.mutable_attrs.stored()
    character.personality = body.personality.stored()


@router.get("/{novel_id}/characters", response_model=list[CharacterPublic])
def list_characters(
    novel_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[Character]:
    # Whole cards, not summaries: a novel has tens of characters at most, and
    # the settings screen edits them in place without a fetch per card.
    _get_owned_novel(db, novel_id, user)
    return list(
        db.scalars(select(Character).where(Character.novel_id == novel_id).order_by(Character.created_at, Character.id))
    )


@router.post("/{novel_id}/characters", response_model=CharacterPublic, status_code=status.HTTP_201_CREATED)
def create_character(
    novel_id: uuid.UUID,
    body: CharacterInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Character:
    _get_owned_novel(db, novel_id, user, for_update=True)
    _reject_taken_names(db, novel_id, _names(body.name, body.aliases))
    if body.aliases:
        _take_over_names(db, novel_id, None, body.aliases, body.name)
    character = Character(novel_id=novel_id, source="manual")
    _apply(character, body)
    db.add(character)
    db.commit()
    db.refresh(character)
    return character


@router.put("/{novel_id}/characters/{character_id}", response_model=CharacterPublic)
def update_character(
    novel_id: uuid.UUID,
    character_id: uuid.UUID,
    body: CharacterInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Character:
    _get_owned_novel(db, novel_id, user, for_update=True)
    character = _get_character(db, novel_id, character_id)
    # Only the names it didn't have yet are checked: one it keeps is its own.
    current = _names(character.name, character.aliases or [])
    _reject_taken_names(db, novel_id, _names(body.name, body.aliases) - current, except_id=character_id)
    # What's recorded under its old name and under its new aliases moves to
    # its name, so the current flags and the next run's agree on who they're
    # about.
    old_names = [character.name] if character.name != body.name else []
    old_names += [alias for alias in body.aliases if normalize_name(alias) not in current]
    if old_names:
        _take_over_names(db, novel_id, character_id, old_names, body.name)
    _apply(character, body)
    # An auto-detected card the author has now edited is theirs (7.4: changes
    # to existing settings always go through the author).
    character.source = "manual"
    db.commit()
    db.refresh(character)
    return character


@router.delete("/{novel_id}/characters/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_character(
    novel_id: uuid.UUID,
    character_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    _get_owned_novel(db, novel_id, user, for_update=True)
    character = _get_character(db, novel_id, character_id)
    # What's derived from this character goes with it: its state history and
    # event participation reference it by foreign key, and relations by id
    # (no FK, since they point at characters or locations).
    db.execute(
        delete(CharacterStateHistory).where(
            CharacterStateHistory.novel_id == novel_id, CharacterStateHistory.character_id == character_id
        )
    )
    db.execute(
        delete(EventParticipant).where(EventParticipant.novel_id == novel_id, EventParticipant.character_id == character_id)
    )
    db.execute(
        delete(Relation).where(
            Relation.novel_id == novel_id,
            Relation.entity_kind == "character",
            or_(Relation.from_entity_id == character_id, Relation.to_entity_id == character_id),
        )
    )
    # The author's dismissals of flags about it stay: they're about sentences
    # of the manuscript, by name (models/flag_dismissal.py), and apply again
    # if the character comes back.
    # Claims about it stay (they're the episode's), named but no longer linked.
    db.execute(
        update(Claim)
        .where(Claim.novel_id == novel_id, Claim.subject_kind == "character", Claim.subject_id == character_id)
        .values(subject_id=None)
    )
    db.delete(character)
    db.commit()
