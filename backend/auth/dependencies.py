"""FastAPI dependency for resolving the authenticated user from a JWE bearer token (design doc 3.3)."""

import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import JWEError, JWTError
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth.jwe import decode_token
from models.db import get_db
from models.user import User

_bearer = HTTPBearer(auto_error=False)


def _token_claims(credentials: HTTPAuthorizationCredentials | None) -> tuple[uuid.UUID, int]:
    """The user id and token version a bearer token carries, or a 401."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")
    try:
        claims = decode_token(credentials.credentials)
        user_id = uuid.UUID(claims["sub"])
        # Tokens minted before `ver` existed count as version 0.
        token_version = int(claims.get("ver", 0))
    except (JWEError, JWTError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc
    return user_id, token_version


def _require_usable(user: User | None, token_version: int) -> User:
    """The user, if the token's claims still hold for them, else a 401."""
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if token_version != user.token_version:
        # Issued before a deletion request (which bumps the version), even if
        # that request has since been cancelled by logging in again.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if user.deletion_requested_at is not None:
        # A pending-deletion account (3.5) is only reachable by logging in,
        # which cancels the deletion. Checked on its own rather than relying on
        # the version bump that the deletion request happens to make.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is pending deletion")
    return user


# Methods that change data: the user row is locked for these (see get_current_user).
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def get_current_user_unlocked(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """The authenticated user, from a plain read. Only for endpoints that take
    the user row's exclusive lock themselves (lock_current_user) after their own
    slow work — PATCH /auth/me and the deletion request — where the shared lock
    of get_current_user would deadlock against that upgrade, and for reads."""
    user_id, token_version = _token_claims(credentials)
    return _require_usable(db.get(User, user_id), token_version)


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """The authenticated user. For requests that change data the row is read
    once under a shared lock (FOR SHARE) and the token is checked against that:
    a plain read followed by a write would let a deletion request that commits in
    between revoke the token while the write still goes through — and the write
    would survive if the user then logged in to cancel the deletion. Shared, so
    a user's own writes don't block one another, only wait for (and are ordered
    against) a deletion request. Applied by method, so a new write endpoint is
    covered without having to remember it. Reads take no lock."""
    user_id, token_version = _token_claims(credentials)
    if request.method in _MUTATING_METHODS:
        return _require_usable(lock_user(db, user_id, shared=True), token_version)
    return _require_usable(db.get(User, user_id), token_version)


def lock_user(db: Session, user_id: uuid.UUID, *, shared: bool = False) -> User | None:
    """Re-read a user row under a lock, overwriting whatever this session had
    loaded, or None if the row no longer exists (purged, 3.5). Login and
    deletion requests take it exclusively, so they stay in step with each
    other; requests that only write the user's data take it shared (FOR
    SHARE), so they don't block one another but do wait for, and are ordered
    against, a deletion request."""
    return db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(read=shared)
        .execution_options(populate_existing=True)
    )


def lock_current_user(db: Session, current_user: User) -> None:
    """Lock the caller's row exclusively and re-check what get_current_user
    matched before the lock: if a concurrent request already revoked this
    token's generation (or put the account up for deletion; a login may have
    cancelled that since), the token is no longer valid and must not be used to
    change anything. For endpoints that change the user row itself (they use
    get_current_user_unlocked); taken after any slow work (the deletion request
    checks the password first)."""
    # Read before locking: the re-read overwrites current_user in place.
    token_version = current_user.token_version
    _require_usable(lock_user(db, current_user.id), token_version)
