"""Email verification for email/password signup (design doc 3.1).

Before an account is created, the address has to prove it receives mail:

1. POST /auth/signup/code {email}: a 6-digit code is emailed, valid for
   CODE_TTL. Asking again replaces the code — no sooner than RESEND_COOLDOWN
   after the last one, and at most MAX_SENDS_PER_HOUR an hour per address, so
   this can't be used to flood someone's inbox.
2. POST /auth/signup/verify {email, code}: a right code (MAX_ATTEMPTS wrong
   guesses per code, then a new one is needed — 5 guesses out of a million
   can't be brute-forced) returns a verification token.
3. POST /auth/signup takes that token (auth/router.py), for the same email.

The code is stored only as an HMAC under the server key (jwe.keyed_hash).
Rows live in email_verifications, one per address, and are deleted once the
code is used.
"""

import hmac
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.jwe import issue_token, keyed_hash
from auth.schemas import (
    SignupCodeRequest,
    SignupCodeSent,
    SignupCodeVerified,
    SignupCodeVerify,
)
from infra.email_client import EmailSendError, get_email_client
from models.db import get_db
from models.email_verification import EmailVerification
from models.user import User

logger = logging.getLogger(__name__)

router = APIRouter()

CODE_TTL = timedelta(minutes=5)
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_SENDS_PER_HOUR = 5
MAX_ATTEMPTS = 5
# How long a verified address stays good for finishing the signup form.
VERIFICATION_TOKEN_TTL_SECONDS = 30 * 60
VERIFIED_PURPOSE = "email_verified"

_SUBJECT = "[Retcona] 이메일 인증번호"
_BODY = """Retcona 회원가입 인증번호입니다.

인증번호: {code}

{minutes}분 안에 가입 화면에 입력해주세요.
본인이 요청하지 않았다면 이 메일은 무시하셔도 됩니다.
"""


def _code_hash(email: str, code: str) -> str:
    return keyed_hash(f"{email}:{code}")


def _too_many(detail: str, retry_after: timedelta) -> HTTPException:
    seconds = max(1, int(retry_after.total_seconds()))
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail, headers={"Retry-After": str(seconds)})


def _locked_row(db: Session, email: str) -> EmailVerification | None:
    # Locked, so two requests for the same address (a double click, two tabs)
    # can't both pass the sending limits or both spend the same guess.
    return db.scalar(select(EmailVerification).where(EmailVerification.email == email).with_for_update())


@router.post("/code", response_model=SignupCodeSent, status_code=status.HTTP_202_ACCEPTED)
def request_code(body: SignupCodeRequest, db: Session = Depends(get_db)) -> SignupCodeSent:
    if db.scalar(select(User.id).where(User.email == body.email)) is not None:
        # Same answer as POST /auth/signup for a registered address.
        raise HTTPException(status.HTTP_409_CONFLICT, "Email is already registered")

    now = datetime.now(UTC)
    row = _locked_row(db, body.email)
    if row is None:
        row = EmailVerification(email=body.email, window_started_at=now, sends_in_window=0, attempts=0)
        db.add(row)
    else:
        if now < row.sent_at + RESEND_COOLDOWN:
            raise _too_many("Wait before requesting another code", row.sent_at + RESEND_COOLDOWN - now)
        if now >= row.window_started_at + timedelta(hours=1):
            row.window_started_at, row.sends_in_window = now, 0
        elif row.sends_in_window >= MAX_SENDS_PER_HOUR:
            raise _too_many("Too many codes requested", row.window_started_at + timedelta(hours=1) - now)

    code = f"{secrets.randbelow(10**6):06d}"
    row.code_hash = _code_hash(body.email, code)
    row.expires_at = now + CODE_TTL
    row.attempts = 0
    row.sent_at = now
    row.sends_in_window += 1
    try:
        db.flush()
    except IntegrityError as exc:
        # Another request created this address's row first, just now.
        db.rollback()
        raise _too_many("Wait before requesting another code", RESEND_COOLDOWN) from exc

    # Sent before committing: if it fails, the row (and the sending limits)
    # stay as they were, and the author can simply try again.
    try:
        get_email_client().send(body.email, _SUBJECT, _BODY.format(code=code, minutes=int(CODE_TTL.total_seconds() // 60)))
    except EmailSendError as exc:
        db.rollback()
        logger.error("Could not send a verification code: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not send the verification email") from exc
    db.commit()
    return SignupCodeSent(expires_in=int(CODE_TTL.total_seconds()), resend_after=int(RESEND_COOLDOWN.total_seconds()))


@router.post("/verify", response_model=SignupCodeVerified)
def verify_code(body: SignupCodeVerify, db: Session = Depends(get_db)) -> SignupCodeVerified:
    now = datetime.now(UTC)
    row = _locked_row(db, body.email)
    if row is None or now >= row.expires_at:
        raise HTTPException(status.HTTP_410_GONE, "No valid code for this email; request a new one")
    if row.attempts >= MAX_ATTEMPTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many wrong codes; request a new one")
    if not hmac.compare_digest(row.code_hash, _code_hash(body.email, body.code)):
        row.attempts += 1
        db.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Wrong code")

    db.delete(row)
    db.commit()
    token = issue_token(body.email, {"purpose": VERIFIED_PURPOSE}, ttl_seconds=VERIFICATION_TOKEN_TTL_SECONDS)
    return SignupCodeVerified(verification_token=token)
