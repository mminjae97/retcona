"""Email/password auth endpoints (design doc 3.1).

Social login (Google/Kakao/Naver) is handled separately in auth/oauth.py.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from auth.jwe import issue_token
from auth.schemas import (
    DeletionRequest,
    DeletionResponse,
    LoginRequest,
    NicknameUpdate,
    SignupRequest,
    TokenResponse,
    UserPublic,
)
from auth.security import DUMMY_PASSWORD_HASH, hash_password, verify_password
from models.db import get_db
from models.user import DELETION_GRACE_PERIOD, User

router = APIRouter()

def _issue_access_token(user: User) -> str:
    # `ver` ties the token to users.token_version so a deletion request can revoke it.
    return issue_token(str(user.id), {"ver": user.token_version})


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def signup(body: SignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if db.scalar(select(User).where(User.email == body.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")

    user = User(email=body.email, nickname=body.nickname, password_hash=hash_password(body.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")
    db.refresh(user)

    return TokenResponse(access_token=_issue_access_token(user), user=UserPublic.model_validate(user))


@router.post("/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    # Always run verify_password, even for a nonexistent user, so response time
    # doesn't leak whether the email is registered.
    password_hash = user.password_hash if user and user.password_hash else DUMMY_PASSWORD_HASH
    password_ok = verify_password(body.password, password_hash)
    if user is None or user.password_hash is None or not password_ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")

    # Re-read under a row lock, taken only now that the slow password check is
    # done. That serializes this login with request_deletion, so the state and
    # token_version used below are current: either the deletion committed
    # first (and this login cancels it, or is refused once the grace period
    # has run out), or this login completes first and the deletion revokes the
    # token afterwards — never a "successful" login whose token was already
    # dead when it was issued.
    locked = db.scalar(
        select(User).where(User.id == user.id).with_for_update().execution_options(populate_existing=True)
    )
    if locked is None:
        # Purged (3.5) between the lookup and the lock.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    user = locked
    deletion_cancelled = False
    if user.deletion_requested_at is not None:
        if datetime.now(timezone.utc) >= user.deletion_requested_at + DELETION_GRACE_PERIOD:
            # Past the grace period the account can no longer be recovered
            # (3.5), even if the purge job hasn't got to it yet.
            raise HTTPException(status.HTTP_410_GONE, "Account deletion grace period has passed")
        # Logging back in during the grace period cancels the deletion (3.5).
        user.deletion_requested_at = None
        deletion_cancelled = True

    # Snapshot before commit(), which expires the instance and would make the
    # validation below re-query; commit() (even with nothing to write) also
    # releases the row lock.
    access_token = _issue_access_token(user)
    user_public = UserPublic.model_validate(user)
    db.commit()

    return TokenResponse(access_token=access_token, user=user_public, deletion_cancelled=deletion_cancelled)


@router.get("/me", response_model=UserPublic)
def me(current_user: User = Depends(get_current_user)) -> UserPublic:
    return UserPublic.model_validate(current_user)


@router.patch("/me", response_model=UserPublic)
def update_nickname(
    body: NicknameUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> User:
    current_user.nickname = body.nickname
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/me/deletion", response_model=DeletionResponse)
def request_deletion(
    body: DeletionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DeletionResponse:
    """Schedule account deletion after the grace period (3.5).

    Identity is re-confirmed with the password first. Social-login accounts
    have no password and are meant to re-authenticate with their provider
    instead, which isn't implemented yet (auth/oauth.py).
    """
    if current_user.password_hash is None:
        raise HTTPException(status.HTTP_501_NOT_IMPLEMENTED, "Re-authentication for social accounts is not supported yet")
    if not verify_password(body.password, current_user.password_hash):
        # 403, not 401: the bearer token is fine, and a 401 would read as an
        # expired session.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Incorrect password")

    # Re-read under a row lock, and re-check the token_version that
    # get_current_user matched the token against before the lock: if a
    # concurrent request already revoked this token's generation (and a login
    # may have cancelled that deletion since), this one must not start a
    # second deletion with a token that is no longer valid.
    token_version = current_user.token_version
    db.refresh(current_user, with_for_update=True)
    if current_user.token_version != token_version:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")

    current_user.deletion_requested_at = datetime.now(timezone.utc)
    # Kills every token issued so far for good, even if a later login
    # cancels the deletion (see get_current_user).
    current_user.token_version += 1
    db.commit()
    db.refresh(current_user)

    return DeletionResponse(
        deletion_requested_at=current_user.deletion_requested_at,
        purge_after=current_user.deletion_requested_at + DELETION_GRACE_PERIOD,
    )
