"""Google login (design doc 3.1, 3.2) — the only social login provider.

Authorization code flow with PKCE, the code obtained by the frontend (3.2):
the browser goes to Google, comes back to the frontend's callback page with a
code, and posts it here with the PKCE verifier; this exchanges it for Google's
ID token (with the client secret, which never leaves the server) and reads the
account from it.

- A Google account already linked (users.provider/provider_id) logs in, with
  the same deletion-state handling as the email login (complete_login).
- A new one doesn't get an account yet: it gets a short-lived signup token,
  and the account is created once the author has chosen a nickname (3.6 — the
  nickname is never taken from the Google profile). This keeps users.nickname
  required, instead of an account existing without one until that screen is
  done.
- An email already registered with a password is refused (409), not linked:
  accounts created before signup email verification existed
  (users.email_verified_at is null) never proved they own the address, so
  linking by email would let whoever registered someone else's Gmail address
  first sit in the account that person later opens with Google.

Configured by GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET /
GOOGLE_OAUTH_REDIRECT_URI; without them the endpoints answer 503 and the
frontend keeps the Google button disabled (GET /auth/google/config).
"""

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Literal, NamedTuple

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from jose.exceptions import JWEError, JWTError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.jwe import decode_token, issue_token
from auth.router import complete_login, issue_access_token
from auth.schemas import Nickname, TokenResponse, UserPublic
from models.db import get_db
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

PROVIDER = "google"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
_TIMEOUT_SECONDS = 10
# How long a new Google account has to choose a nickname before starting over.
SIGNUP_TOKEN_TTL_SECONDS = 15 * 60
_SIGNUP_PURPOSE = "google_signup"


class _Config(NamedTuple):
    client_id: str
    client_secret: str
    redirect_uri: str


def _config() -> _Config | None:
    values = [os.environ.get(f"GOOGLE_OAUTH_{name}", "").strip() for name in ("CLIENT_ID", "CLIENT_SECRET", "REDIRECT_URI")]
    return _Config(*values) if all(values) else None


def _require_config() -> _Config:
    config = _config()
    if config is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Google login is not configured")
    return config


class GoogleIdentity(NamedTuple):
    sub: str
    email: str


def exchange_code(config: _Config, code: str, code_verifier: str) -> GoogleIdentity:
    """The Google account a code was issued for. 401 if Google rejects the
    code (expired, already used, wrong verifier); 502 if Google can't be
    reached."""
    body = urllib.parse.urlencode(
        {
            "code": code,
            "code_verifier": code_verifier,
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "redirect_uri": config.redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    request = urllib.request.Request(_TOKEN_URL, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        # 400 invalid_grant and the like: the code, not Google, is the problem.
        logger.info("Google rejected an authorization code (%s)", exc.code)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google sign-in failed") from exc
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Could not complete a Google sign-in: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach Google") from exc

    # Straight from Google's token endpoint over TLS, so the ID token's
    # signature needn't be checked (OpenID Connect Core 3.1.3.7); its
    # audience, issuer and expiry still are.
    try:
        claims = jwt.get_unverified_claims(payload["id_token"])
    except (KeyError, JWTError) as exc:
        logger.warning("Google's token response had no usable ID token")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Unexpected response from Google") from exc
    audience = claims.get("aud")
    audiences = audience if isinstance(audience, list) else [audience]
    if config.client_id not in audiences or claims.get("iss") not in _ISSUERS or claims.get("exp", 0) < time.time():
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Google sign-in failed")
    email = claims.get("email")
    if not claims.get("sub") or not email or claims.get("email_verified") is not True:
        # The account's identity is its email here (users.email is unique),
        # so an unverified one isn't enough.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google account has no verified email")
    return GoogleIdentity(sub=str(claims["sub"]), email=email.lower())


class GoogleConfigPublic(BaseModel):
    enabled: bool
    client_id: str | None = None
    redirect_uri: str | None = None


class GoogleLoginRequest(BaseModel):
    code: str = Field(min_length=1, max_length=2048)
    # PKCE (RFC 7636): 43-128 characters.
    code_verifier: str = Field(min_length=43, max_length=128)


class GoogleLoginResponse(BaseModel):
    # logged_in: an existing account, signed in (the TokenResponse fields are
    # set). signup_required: a new Google account; it has signup_token and
    # email, and becomes an account through POST /auth/google/signup.
    status: Literal["logged_in", "signup_required"]
    access_token: str | None = None
    token_type: str = "bearer"
    user: UserPublic | None = None
    deletion_cancelled: bool = False
    signup_token: str | None = None
    email: str | None = None


class GoogleSignupRequest(BaseModel):
    signup_token: str
    nickname: Nickname


@router.get("/config", response_model=GoogleConfigPublic)
def google_config() -> GoogleConfigPublic:
    # The client id and redirect URI are public (they're in the URL the
    # browser is sent to); the secret isn't here.
    config = _config()
    if config is None:
        return GoogleConfigPublic(enabled=False)
    return GoogleConfigPublic(enabled=True, client_id=config.client_id, redirect_uri=config.redirect_uri)


@router.post("/login", response_model=GoogleLoginResponse)
def google_login(body: GoogleLoginRequest, db: Session = Depends(get_db)) -> GoogleLoginResponse:
    identity = exchange_code(_require_config(), body.code, body.code_verifier)

    user = db.scalar(select(User).where(User.provider == PROVIDER, User.provider_id == identity.sub))
    if user is not None:
        result = complete_login(db, user, "Google account not found")
        return GoogleLoginResponse(status="logged_in", **result.model_dump())

    if db.scalar(select(User.id).where(User.email == identity.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")

    signup_token = issue_token(
        identity.sub,
        {"purpose": _SIGNUP_PURPOSE, "email": identity.email},
        ttl_seconds=SIGNUP_TOKEN_TTL_SECONDS,
    )
    return GoogleLoginResponse(status="signup_required", signup_token=signup_token, email=identity.email)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def google_signup(body: GoogleSignupRequest, db: Session = Depends(get_db)) -> TokenResponse:
    _require_config()
    try:
        claims = decode_token(body.signup_token)
        if claims.get("purpose") != _SIGNUP_PURPOSE:
            raise ValueError("not a Google signup token")
        sub, email = str(claims["sub"]), str(claims["email"])
    except (JWEError, JWTError, ValueError, KeyError, TypeError) as exc:
        # Expired (the author took too long on the nickname screen) or not one of ours.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired signup token") from exc

    # Google only hands over verified emails (exchange_code checks email_verified).
    user = User(
        email=email,
        nickname=body.nickname,
        provider=PROVIDER,
        provider_id=sub,
        password_hash=None,
        email_verified_at=datetime.now(UTC),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # The email was registered since the signup token was issued (or the
        # same Google account finished signing up in another tab).
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered") from exc
    db.refresh(user)
    return TokenResponse(access_token=issue_access_token(user), user=UserPublic.model_validate(user))
