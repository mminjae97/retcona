"""flag_dismissals table (design doc 2.4, 7.5).

What the author dismissed as a false positive, kept apart from the claims and
contradiction_flags a validation run replaces: a run that doesn't flag the
sentence this time (the model skipped the claim, or scored it just under the
threshold) doesn't lose the dismissal, and a later run that flags it again
finds it here (pipeline/dismissals.py).

One row per (episode, subject, attribute, what the manuscript said, setting it
was judged against) — the same sentence judged against a changed setting is a
new question for the author, so the setting is part of it.
- subject: who or what the claim is about, by kind and name as the manuscript
  names it ("character:레온", normalized) — not the card's id: entity matching
  goes by name, so a card deleted and made again (a new id), or renamed, still
  meets its dismissals when the manuscript names it the same way.
- said: the sentence by its letters and digits ("sentence:..."), or, for a
  claim that came with no sentence, what it said for the attribute ("value:...")
- reference: the setting value, normalized
"""

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, NovelScopedMixin, TimestampMixin


class FlagDismissal(Base, NovelScopedMixin, TimestampMixin):
    __tablename__ = "flag_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "episode_id", "subject", "attribute", "said", "reference", name="uq_flag_dismissals_key"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    attribute: Mapped[str] = mapped_column(String, nullable=False)
    said: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False)
