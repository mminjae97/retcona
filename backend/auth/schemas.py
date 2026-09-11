"""Pydantic request/response schemas for the auth endpoints."""

import uuid

from pydantic import BaseModel, EmailStr, Field, field_validator


def _normalize_email(value: str) -> str:
    return value.lower()


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    nickname: str = Field(min_length=2)  # pen name constraint (3.6): 2-20 chars after stripping

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

    @field_validator("nickname")
    @classmethod
    def strip_nickname(cls, value: str) -> str:
        # Strip before length-checking, so surrounding whitespace can't push a
        # nickname over the 20-char limit or hide an all-whitespace value.
        value = value.strip()
        if not 2 <= len(value) <= 20:
            raise ValueError("Nickname must be 2-20 characters")
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        return _normalize_email(value)


class UserPublic(BaseModel):
    model_config = {"from_attributes": True}

    id: uuid.UUID
    email: str
    nickname: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
