"""email_verifications table: the pending signup verification code for an
email address (auth/email_verification.py).

One row per address, replaced by each new code. Not scoped to a novel or a
user — it exists before the account does, and is deleted once the code has
been used.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin


class EmailVerification(Base, TimestampMixin):
    __tablename__ = "email_verifications"

    email: Mapped[str] = mapped_column(String, primary_key=True)
    # HMAC of the code (never the code itself), keyed with the server secret.
    code_hash: Mapped[str] = mapped_column(String, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Wrong guesses at the current code.
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Sending limits: when the last code was sent (resend cooldown), and how
    # many were sent since window_started_at (hourly cap).
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sends_in_window: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
