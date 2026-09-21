"""FastAPI dependency for resolving the authenticated user from a JWE bearer token (design doc 3.3)."""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose.exceptions import JWEError, JWTError
from sqlalchemy.orm import Session

from auth.jwe import decode_token
from models.db import get_db
from models.user import User

_bearer = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    try:
        claims = decode_token(credentials.credentials)
        user_id = uuid.UUID(claims["sub"])
        # Tokens minted before `ver` existed count as version 0.
        token_version = int(claims.get("ver", 0))
    except (JWEError, JWTError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if token_version != user.token_version:
        # Issued before a deletion request (which bumps the version), even if
        # that request has since been cancelled by logging in again. This also
        # covers a pending-deletion account (3.5): the bump and the pending
        # state happen together, and the only way back is logging in, which
        # cancels the deletion and issues a token at the new version.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return user
