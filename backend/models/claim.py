"""claims, contradiction_flags tables (design doc 4.3, chapter 7).

claims: verification-target claim units extracted from the manuscript by the extract_claims step
  - subject_kind / subject_id: the character or location the claim is about, as
    matched or auto-registered by entity matching (7.4). No foreign key, like
    relations: it points at either table. subject_name keeps the name as the
    extraction gave it, so a claim still reads right after its card is deleted
    (subject_id is then cleared).
  - evidence_text: the manuscript sentence the claim came from (shown as the
    basis on the result screen, 2.4)
  - attributes: what the claim says as setting-card keys (e.g. {"eye_color": ...}),
    where it maps onto one — what a new card's initial attributes come from (7.4)
contradiction_flags: a claim that contradicts the novel's settings (7.2)
  - error_type: the judgment module that raised it — appearance | behavior |
    location | spacetime, as claim_type
  - attribute: the setting-card key the claim contradicts (e.g. "eye_color")
  - evidence_text: the manuscript sentence that contradicts it
  - reference_text: the setting's value it contradicts, as the card has it
  - confidence: the judgment's contradiction probability (0-1); the result
    screen sorts by it (2.5)
  - status: open | resolved_by_revalidation | accepted | dismissed (2.4, 7.5)
"""

import uuid

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class Claim(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "claims"
    __table_args__ = (Index("ix_claims_novel_episode", "novel_id", "episode_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String)  # appearance | behavior (OOC) | location | spacetime
    subject_kind: Mapped[str | None] = mapped_column(String)  # character | location
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subject_name: Mapped[str | None] = mapped_column(String)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)


class ContradictionFlag(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "contradiction_flags"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("claims.id"), nullable=False)
    error_type: Mapped[str] = mapped_column(String, nullable=False)  # appearance | behavior (OOC) | location | spacetime
    attribute: Mapped[str | None] = mapped_column(String)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    reference_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="open")
    # open | resolved_by_revalidation | accepted | dismissed
