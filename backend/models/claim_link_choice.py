"""claim_link_choices table (design doc 7.1.1).

Which card the author picked for a claim the extraction couldn't tie to one —
a pronoun that fits two characters, a name two share — kept apart from the
claims a validation run replaces, so the same sentence isn't asked about
again on the next run (pipeline/claim_links.py applies them).

One row per (episode, said): the sentence by its letters and digits, and the
name the claim gave for its subject (none for a bare pronoun).
- subject_id: the character picked; None where the author said the sentence
  isn't about any of them ("해당 없음"), and the claim is dropped. No FK, like
  claims.subject_id. Deleting the card deletes the choices naming it
  (api/settings.py).
"""

import uuid

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class ClaimLinkChoice(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "claim_link_choices"
    __table_args__ = (UniqueConstraint("episode_id", "said", name="uq_claim_link_choices_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False)
    said: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
