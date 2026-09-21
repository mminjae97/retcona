"""FastAPI dependency for resolving the authenticated user from a JWE bearer token (design doc 3.3)."""

import uuid
from datetime import timezone

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
        issued_at = int(claims["iat"])
    except (JWEError, JWTError, ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if user.deletion_requested_at is not None:
        # Pending deletion (3.5): the account only comes back by logging in again.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is scheduled for deletion")
    # Compared in whole seconds since `iat` has no sub-second part: a token
    # minted by a re-login in the same second as the deletion request must
    # still be accepted, at the cost of one issued in the last instant before
    # the request surviving.
    valid_after = user.sessions_valid_after
    if valid_after is not None:
        if valid_after.tzinfo is None:  # the column is timestamptz; this only guards a driver that drops the zone
            valid_after = valid_after.replace(tzinfo=timezone.utc)
        if issued_at < int(valid_after.timestamp()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    return user
