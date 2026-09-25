"""The author's false-positive dismissals, kept across validation runs (models/flag_dismissal.py).

The result screen's dismiss records one; reopen removes it; a validation run
marks the flags it finds that match one as dismissed. The caller commits.
"""

import uuid
from typing import NamedTuple

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models.flag_dismissal import FlagDismissal
from pipeline.entities import comparable_text, normalize_name


class DismissalKey(NamedTuple):
    subject: str
    attribute: str
    said: str
    reference: str


def dismissal_key(
    subject_kind: str | None,
    subject_name: str | None,
    attribute: str | None,
    evidence: str | None,
    value: str | None,
    reference: str | None,
) -> DismissalKey | None:
    """What identifies a flag across runs: who or what the claim is about, by
    kind and name (entity matching goes by name too, so a card deleted and made
    again still matches), the attribute, what the manuscript said — the
    sentence by its letters and digits (the model's copy of it can differ
    between runs), or, with no sentence, the value (the claim's restatement
    differs between runs) — and the setting it was judged against. None for a
    flag with no subject or attribute, which can't be matched up."""
    if not subject_kind or not subject_name or not attribute:
        return None
    said = f"sentence:{comparable_text(evidence)}" if evidence else f"value:{normalize_name(value or '')}"
    subject = f"{subject_kind}:{normalize_name(subject_name)}"
    return DismissalKey(subject, attribute, said, normalize_name(reference or ""))


def dismissed_keys(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID) -> set[DismissalKey]:
    return {
        DismissalKey(row.subject, row.attribute, row.said, row.reference)
        for row in db.execute(
            select(FlagDismissal.subject, FlagDismissal.attribute, FlagDismissal.said, FlagDismissal.reference).where(
                FlagDismissal.novel_id == novel_id, FlagDismissal.episode_id == episode_id
            )
        )
    }


def record_dismissal(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, key: DismissalKey) -> None:
    db.execute(
        insert(FlagDismissal)
        .values(novel_id=novel_id, episode_id=episode_id, **key._asdict())
        .on_conflict_do_nothing(constraint="uq_flag_dismissals_key")
    )


def remove_dismissal(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, key: DismissalKey) -> None:
    db.execute(
        delete(FlagDismissal).where(
            FlagDismissal.novel_id == novel_id,
            FlagDismissal.episode_id == episode_id,
            FlagDismissal.subject == key.subject,
            FlagDismissal.attribute == key.attribute,
            FlagDismissal.said == key.said,
            FlagDismissal.reference == key.reference,
        )
    )
