"""Pydantic request/response schemas for the auth endpoints."""

import unicodedata
import uuid
from datetime import datetime

from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator

from models.nickname_rules import NICKNAME_RULES as _NICKNAME_RULES


def _normalize_email(value: str) -> str:
    return value.lower()


# The length/mark-count numbers in the pen-name rule (3.6) come from
# models.nickname_rules (shared/nickname-rules.json), also read by
# models/user.py (the nickname column's length) and the frontend
# (utils/nickname.ts), so they can't drift apart on *these* numbers. The
# character-class check itself (which Unicode categories are allowed) still
# can't be shared this way — a regex (frontend) and unicodedata.category()
# (here) are different engines — and is instead kept in sync by hand,
# cross-checked over every code point.

# What a pen name may contain (3.6): letters, numbers, combining marks and the
# ordinary space, from the Basic Multilingual Plane only. Everything else is out:
# emoji and other pictographs, punctuation and symbols, other kinds of space,
# format and control characters (zero-width joiner, NUL, ...) and rare astral
# characters. The frontend applies the same rule (utils/nickname.ts). Every
# allowed character is one UTF-16 unit, so len() here and String.length there
# agree.
_NICKNAME_MARK_CATEGORIES = {"Mn", "Mc"}
# Longest run of combining marks allowed on one character; more is zalgo-style stacking.
_NICKNAME_MAX_MARKS = _NICKNAME_RULES["maxMarks"]
# Letters or marks that render as nothing (fillers, joiners, variation
# selectors); they'd let a name look blank or hide characters.
_NICKNAME_INVISIBLE = (
    {chr(code) for code in (0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180F, 0x3164, 0xFFA0)}
    | {chr(code) for code in range(0x180B, 0x180E)}
    | {chr(code) for code in range(0xFE00, 0xFE10)}
)


def _is_allowed_nickname_char(char: str) -> bool:
    if ord(char) > 0xFFFF or char in _NICKNAME_INVISIBLE:
        return False
    if char == " ":
        return True
    category = unicodedata.category(char)
    return category[0] in ("L", "N") or category in _NICKNAME_MARK_CATEGORIES


def _check_nickname_marks(value: str) -> None:
    run = 0
    previous = " "  # the start of the name counts like a space: nothing to attach to
    for char in value:
        if unicodedata.category(char) in _NICKNAME_MARK_CATEGORIES:
            run += 1
            if previous == " " or run > _NICKNAME_MAX_MARKS:
                raise ValueError("Nickname has combining marks with nothing to attach to, or too many in a row")
        else:
            run = 0
        previous = char


def _strip_nickname(value: str) -> str:
    # NFC first, so the same visible name has one form and one length however
    # it was typed (Hangul as separate jamo, letters with combining accents) —
    # otherwise decomposed text slips past the 2-char minimum and 20-char cap.
    # Then strip before length-checking, so surrounding whitespace can't push
    # a nickname over the limit or hide an all-whitespace value.
    value = unicodedata.normalize("NFC", value).strip()
    if not _NICKNAME_RULES["minLength"] <= len(value) <= _NICKNAME_RULES["maxLength"]:
        raise ValueError(f"Nickname must be {_NICKNAME_RULES['minLength']}-{_NICKNAME_RULES['maxLength']} characters")
    # Also what keeps NUL out (Postgres text columns reject it: a 500 from the
    # INSERT/UPDATE instead of a 422 here) along with emoji and symbols.
    if not all(_is_allowed_nickname_char(char) for char in value):
        raise ValueError("Nickname may only contain letters, numbers and spaces")
    # Marks only attach to something; a name made of nothing else would render blank.
    if not any(unicodedata.category(char)[0] in ("L", "N") for char in value):
        raise ValueError("Nickname must contain at least one letter or number")
    _check_nickname_marks(value)
    return value


# Shared by every request that takes a pen name, so the rule lives in one place.
# The raw cap is generous (20 characters, each possibly decomposed into jamo or
# carrying a few marks, plus padding) and only there so an unauthenticated
# request can't make normalization chew through megabytes before the real 2-20
# check rejects it.
Nickname = Annotated[
    str,
    Field(min_length=_NICKNAME_RULES["minLength"], max_length=_NICKNAME_RULES["maxRawLength"]),
    AfterValidator(_strip_nickname),  # min-max chars after stripping (3.6)
]


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: Nickname

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)

    @field_validator("password")
    @classmethod
    def check_password_byte_length(cls, value: str) -> str:
        # bcrypt only hashes the first 72 bytes, so cap by UTF-8 bytes, not characters
        if len(value.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes")
        # bcrypt refuses a NUL byte (passlib raises PasswordValueError), which
        # would otherwise surface from hash_password as a 500 instead of a 422.
        if "\x00" in value:
            raise ValueError("Password must not contain NUL characters")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class NicknameUpdate(BaseModel):
    nickname: Nickname


class DeletionRequest(BaseModel):
    password: str


class DeletionResponse(BaseModel):
    # The account the request was made for (the one the token belonged to), so
    # the client can clear that account's local data rather than guess at it.
    user_id: uuid.UUID
    deletion_requested_at: datetime
    purge_after: datetime


class UserPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    nickname: str
    has_password: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
    # True when this login cancelled a pending account deletion (3.5).
    deletion_cancelled: bool = False
