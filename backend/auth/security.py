"""Password hashing for direct login (design doc 3.1) — scheme configurable via PASSWORD_HASH_SCHEME."""

import os

from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=[os.environ.get("PASSWORD_HASH_SCHEME", "bcrypt")], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _pwd_context.verify(password, password_hash)
