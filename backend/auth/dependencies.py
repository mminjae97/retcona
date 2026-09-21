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
    except (JWEError, JWTError, ValueError, KeyError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found")
    if user.deletion_requested_at is not None:
        # Pending deletion (3.5): the account only comes back by logging in
        # again, so a token issued before the request must stop working.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account is scheduled for deletion")
    return user
