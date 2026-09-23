"""Auth token issuance/verification (design doc 3.3 JWE).

Structure (Nested JWT):
  1. Sign the claims (user_id, novel permissions, etc.) as a JWT (JWS) -> guarantees integrity
  2. Encrypt the whole signed token as JWE -> guarantees confidentiality

The design doc's example algorithms (RS256 / RSA-OAEP-256) are asymmetric and would need a
key pair; this solo-deployment implementation uses symmetric HS256 (signing) + direct A256GCM
(encryption) instead, driven by the two single-secret env vars already scaffolded
(JWT_SIGNING_KEY, JWT_ENCRYPTION_KEY). Only the server holds both keys; the client only
stores/sends the encrypted token.
"""

import os
import time

from jose import jwe, jwt

ACCESS_TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days

# RFC 7518 recommends an HS256 key at least as long as the hash output (32
# bytes); .env.example's suggested secrets.token_urlsafe(32) is well over this.
MIN_SIGNING_KEY_LENGTH = 32


def _signing_key() -> str:
    key = os.environ.get("JWT_SIGNING_KEY")
    if not key:
        raise RuntimeError("JWT_SIGNING_KEY is not set")
    if len(key) < MIN_SIGNING_KEY_LENGTH:
        raise RuntimeError(f"JWT_SIGNING_KEY must be at least {MIN_SIGNING_KEY_LENGTH} characters")
    return key


def _to_str(value: str | bytes) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _encryption_key() -> bytes:
    hex_key = os.environ.get("JWT_ENCRYPTION_KEY")
    if not hex_key:
        raise RuntimeError("JWT_ENCRYPTION_KEY is not set")
    key = bytes.fromhex(hex_key)
    if len(key) != 32:
        raise RuntimeError("JWT_ENCRYPTION_KEY must decode to exactly 32 bytes (256 bits) for A256GCM")
    return key


def validate_keys() -> None:
    """Fail fast at startup if the JWT keys are missing/malformed, instead of
    on the first request that needs them."""
    _signing_key()
    _encryption_key()


def issue_token(user_id: str, claims: dict | None = None, *, ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS) -> str:
    now = int(time.time())
    # sub/iat/exp last, so a caller-supplied claims dict can never override them.
    payload = {**(claims or {}), "sub": user_id, "iat": now, "exp": now + ttl_seconds}
    signed = jwt.encode(payload, _signing_key(), algorithm="HS256")
    encrypted = jwe.encrypt(signed, _encryption_key(), algorithm="dir", encryption="A256GCM")
    return _to_str(encrypted)


def decode_token(token: str) -> dict:
    signed = _to_str(jwe.decrypt(token, _encryption_key()))
    return jwt.decode(signed, _signing_key(), algorithms=["HS256"])
