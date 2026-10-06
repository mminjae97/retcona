"""One "judge the claim the author picked a card for" job (design doc 7.1.1), as the CPU worker runs it.

A claim the extraction couldn't tie to one card — a pronoun that fits two
characters, a name two share — waits on the result screen for the author to
pick (pipeline/claim_links.py). The pick is kept for the next run, and this
judges the claim now, against the card picked, the way a run would have
(appearance, NLI): not the whole episode again.

The claim row carries the job (models/claim.py link_status): pending ->
queued (the API, which picked the card) -> judging (here) -> none, a claim
like any other. Steps:
1. Claim it: queued -> judging, in one conditional UPDATE, so a job delivered
   twice runs once (10.4.4).
2. Read the claim, its card (the claim as the card's name would have said it),
   and the names of the episode's other subjects.
3. Judge with no transaction open (NLI, pipeline/judges.judge_appearance).
4. Write under the novel's row lock: the flags it finds (dismissed where the
   author dismissed the same one before), and the claim is a normal claim now.
   Nothing is written if a new run replaced the claim meanwhile.

A failure — the model couldn't run, the card was deleted, anything — puts the
claim back to pending, with no card, for the author to pick again; the pick
stays recorded, and the next run applies it.

Not done here: filling the card's empty attributes from the claim, which a
run does for all its claims (pipeline/merge.py). The next run does.
"""

import logging
import uuid
from typing import NamedTuple

from sqlalchemy import select, update

from ai.nli_rerank import InferenceError
from models.character import Character
from models.claim import Claim, ContradictionFlag
from models.db import SessionLocal
from models.novel import Novel
from pipeline.context_bundle import get_context_bundle
from pipeline.dismissals import dismissal_key, dismissed_keys
from pipeline.entities import Match, normalize_name
from pipeline.extract_claims import ExtractedClaim
from pipeline.judges import Flag, judge_appearance
from pipeline.statements import CHARACTER_ATTR_TOPICS, character_statement

logger = logging.getLogger(__name__)


class _Failed(Exception):
    pass


class _Judged(NamedTuple):
    card_id: uuid.UUID
    text: str
    evidence: str | None
    attributes: dict[str, str]
    flags: list[Flag]


def _take(novel_id: uuid.UUID, claim_id: uuid.UUID) -> bool:
    with SessionLocal() as db:
        taken = db.scalar(
            update(Claim)
            .where(Claim.id == claim_id, Claim.novel_id == novel_id, Claim.link_status == "queued")
            .values(link_status="judging")
            .returning(Claim.id)
        )
        db.commit()
        return taken is not None


def _put_back(novel_id: uuid.UUID, claim_id: uuid.UUID) -> None:
    """Pending again, with no card: for the author to pick again."""
    with SessionLocal() as db:
        db.execute(
            update(Claim)
            .where(Claim.id == claim_id, Claim.novel_id == novel_id, Claim.link_status.in_(("queued", "judging")))
            .values(link_status="pending", subject_id=None, subject_name=None, link_requested_at=None)
        )
        db.commit()


def _judge(novel_id: uuid.UUID, claim_id: uuid.UUID) -> _Judged:
    with SessionLocal() as db:
        claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.novel_id == novel_id))
        if claim is None or claim.subject_id is None:
            raise _Failed("claim_missing")
        card = db.scalar(select(Character).where(Character.id == claim.subject_id, Character.novel_id == novel_id))
        if card is None:
            raise _Failed("card_missing")
        attributes = {key: str(value) for key, value in (claim.attributes or {}).items()}
        # The claim as the card's name would have said it: the judgment reads
        # this where the sentence doesn't name the character (pipeline/judges.py).
        statements = [
            character_statement(card.name, key, value)
            for key, value in attributes.items()
            if key in CHARACTER_ATTR_TOPICS
        ]
        text = " ".join(statements) or claim.text
        extracted = ExtractedClaim(
            claim_type="appearance",
            subject_kind="character",
            subject=card.name,
            text=text,
            evidence=claim.evidence_text,
            attributes=attributes,
        )
        bundle = get_context_bundle(db, novel_id, claim.episode_id, [Match(card.id)])
        # The episode's other subjects, as the run saw them: which sentence the
        # model reads depends on them.
        others = {
            normalize_name(name)
            for name in db.scalars(
                select(Claim.subject_name).where(
                    Claim.novel_id == novel_id,
                    Claim.episode_id == claim.episode_id,
                    Claim.subject_kind == "character",
                    Claim.subject_name.is_not(None),
                )
            )
        }
        card_id, evidence = card.id, claim.evidence_text
    try:
        flags = judge_appearance([extracted], bundle, others)
    except InferenceError as exc:
        logger.exception("Novel %s: the NLI model failed", novel_id)
        raise _Failed("inference_failed") from exc
    return _Judged(card_id, text, evidence, extracted.attributes, flags)


def _store(novel_id: uuid.UUID, claim_id: uuid.UUID, judged: _Judged) -> None:
    with SessionLocal() as db:
        # A soft-deleted novel has nowhere to show the result.
        if (
            db.scalar(select(Novel.id).where(Novel.id == novel_id, Novel.deleted_at.is_(None)).with_for_update())
            is None
        ):
            raise _Failed("novel_missing")
        claim = db.scalar(select(Claim).where(Claim.id == claim_id, Claim.novel_id == novel_id).with_for_update())
        if claim is None or claim.link_status != "judging":
            logger.warning("Claim %s was replaced by a new run before it was judged; discarding", claim_id)
            return
        # The card, still: one deleted meanwhile has nothing to hold the claim to.
        if (
            db.scalar(select(Character.id).where(Character.id == judged.card_id, Character.novel_id == novel_id))
            is None
        ):
            raise _Failed("card_missing")
        dismissed = dismissed_keys(db, novel_id, claim.episode_id)
        for flag in judged.flags:
            key = dismissal_key(
                judged.card_id,
                flag.attribute,
                judged.evidence,
                judged.attributes.get(flag.attribute),
                flag.reference_text,
            )
            db.add(
                ContradictionFlag(
                    novel_id=novel_id,
                    claim_id=claim_id,
                    error_type=flag.error_type,
                    attribute=flag.attribute,
                    confidence=flag.confidence,
                    evidence_text=flag.evidence_text,
                    reference_text=flag.reference_text,
                    status="dismissed" if key in dismissed else "open",
                )
            )
        claim.text = judged.text
        claim.candidates = []
        claim.link_status = None
        claim.link_requested_at = None
        db.commit()


def judge_linked_claim(novel_id: uuid.UUID, claim_id: uuid.UUID) -> None:
    if not _take(novel_id, claim_id):
        logger.info("Claim %s isn't waiting to be judged (already taken, or replaced); skipping", claim_id)
        return
    try:
        _store(novel_id, claim_id, _judge(novel_id, claim_id))
    except _Failed as exc:
        logger.warning("Claim %s couldn't be judged (%s); back to pending", claim_id, exc)
        _put_back(novel_id, claim_id)
    except Exception:
        logger.exception("Claim %s couldn't be judged; back to pending", claim_id)
        _put_back(novel_id, claim_id)
