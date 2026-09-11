"""claims, contradiction_flags tables (design doc 4.3, chapter 7).

claims: verification-target claim units extracted from the manuscript by the extract_claims step
contradiction_flags:
  - status: open | resolved_by_revalidation | accepted | dismissed (2.4, 7.5)
"""

import uuid

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class Claim(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "claims"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String)  # appearance | behavior (OOC) | location | spacetime


class ContradictionFlag(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "contradiction_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=False)
    error_type: Mapped[str] = mapped_column(String, nullable=False)  # appearance mismatch | OOC | location error | spacetime contradiction
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="open")
    # open | resolved_by_revalidation | accepted | dismissed
