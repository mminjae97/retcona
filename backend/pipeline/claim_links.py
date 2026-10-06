"""The author's picks for claims the extraction couldn't tie to one card (design doc 7.1.1).

A claim about "그" that fits two characters, or about a name two characters
share, comes out of the extraction with the characters it could be
(ExtractedClaim.candidates) and no card. A validation run stores it as pending
(models/claim.py) for the result screen to ask the author about; what the
author picks is kept (models/claim_link_choice.py), and the next run applies
it before judging, so the same sentence isn't asked about again.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from models.claim_link_choice import ClaimLinkChoice
from pipeline.entities import comparable_text, normalize_name
from pipeline.extract_claims import ExtractedClaim
from pipeline.statements import CHARACTER_ATTR_TOPICS, character_statement


def link_key(evidence: str | None, subject: str) -> str:
    """What identifies such a claim across runs: the sentence by its letters
    and digits (the extraction's copy of it can differ between runs) and the
    name it gave for its subject, none for a bare pronoun."""
    return f"sentence:{comparable_text(evidence or '')}|{normalize_name(subject)}"


def load_choices(db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID) -> dict[str, uuid.UUID | None]:
    """{link_key: the card picked, None for "not any of them"}."""
    return {
        row.said: row.subject_id
        for row in db.execute(
            select(ClaimLinkChoice.said, ClaimLinkChoice.subject_id).where(
                ClaimLinkChoice.novel_id == novel_id, ClaimLinkChoice.episode_id == episode_id
            )
        )
    }


def record_choice(
    db: Session, novel_id: uuid.UUID, episode_id: uuid.UUID, key: str, subject_id: uuid.UUID | None
) -> None:
    """The caller commits."""
    statement = insert(ClaimLinkChoice).values(
        novel_id=novel_id, episode_id=episode_id, said=key, subject_id=subject_id
    )
    db.execute(statement.on_conflict_do_update(constraint="uq_claim_link_choices_key", set_={"subject_id": subject_id}))


def apply_choices(
    claims: list[ExtractedClaim],
    choices: dict[str, uuid.UUID | None],
    refs: dict[str, uuid.UUID],
    cards: dict[str, dict],
) -> list[ExtractedClaim]:
    """The claims with the author's picks applied: a claim picked a card for
    becomes a claim about it (as if the extraction had known), one the author
    said isn't about any of them is dropped. A pick whose card isn't among the
    claim's candidates any more (deleted, or the sentence now fits others)
    leaves it pending. refs: the extraction's refs -> card ids; cards: ref ->
    the card as the extraction was given it ({"name", ...})."""
    refs_of = {card_id: ref for ref, card_id in refs.items()}
    kept = []
    for claim in claims:
        if claim.candidates:
            key = link_key(claim.evidence, claim.subject)
            if key in choices:
                picked = choices[key]
                if picked is None:
                    continue
                ref = refs_of.get(picked)
                if ref is not None and ref in claim.candidates:
                    claim.subject, claim.subject_ref, claim.candidates = cards[ref]["name"], ref, []
                    # Said with the card's name, not "그": where the sentence doesn't
                    # name it, the judgment reads this instead (pipeline/judges.py).
                    statements = [
                        character_statement(claim.subject, key, value)
                        for key, value in claim.attributes.items()
                        if key in CHARACTER_ATTR_TOPICS
                    ]
                    claim.text = " ".join(statements) or claim.text
        kept.append(claim)
    return kept
