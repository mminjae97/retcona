"""Pydantic request/response schemas for the auth endpoints."""

import uuid
from datetime import datetime

from typing import Annotated

from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator


def _normalize_email(value: str) -> str:
    return value.lower()


def _strip_nickname(value: str) -> str:
    # Strip before length-checking, so surrounding whitespace can't push a
    # nickname over the 20-char limit or hide an all-whitespace value.
    value = value.strip()
    if not 2 <= len(value) <= 20:
        raise ValueError("Nickname must be 2-20 characters")
    return value


# Shared by every request that takes a pen name, so the rule lives in one place.
Nickname = Annotated[str, Field(min_length=2), AfterValidator(_strip_nickname)]  # 2-20 chars after stripping (3.6)


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
