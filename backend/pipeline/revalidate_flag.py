"""One "revalidate this flag" job (design doc 7.5), as the CPU worker runs it.

The author supplemented the setting a flag was judged against (on the result
screen, or the settings screen) and asked for that flag alone to be judged
again: only the judgment that raised it re-runs, against the card as it is
now — not the whole pipeline.

The revalidation row (models/flag_revalidation.py) carries the job through
queued -> running -> succeeded | failed. Steps:
1. Claim it: queued -> running, in one conditional UPDATE, so a job
   delivered twice runs once (10.4.4).
2. Read the flag, its claim, the card, and the episode's other subjects.
3. Judge with no transaction open (NLI, pipeline/judges.rejudge).
4. Write under the novel's row lock: resolved -> the flag becomes
   resolved_by_revalidation; still contradicting -> it stays open with the
   new setting and confidence. Nothing is written if, meanwhile, the flag was
   handled or replaced (a new run), the revalidation was given up on, or the
   card's value changed again — that value wasn't the one judged.

A failure is recorded as an error code the result screen turns into a
message: flag_missing, flag_handled, card_missing, setting_changed,
inference_failed, internal.
"""

import logging
import uuid
from typing import NamedTuple

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ai.nli_rerank import InferenceError
from models.character import Character
from models.claim import Claim, ContradictionFlag
from models.db import SessionLocal
from models.flag_revalidation import FlagRevalidation
from models.location import Location
from models.novel import Novel
from pipeline.context_bundle import Card, source_episodes, text_values
from pipeline.entities import normalize_name
from pipeline.judges import CONTRADICTION_THRESHOLD, rejudge

logger = logging.getLogger(__name__)

# Which card a flag's claim is about, by subject kind, and where its judged
# attributes live (as the context bundle reads them).
_CARDS = {"character": (Character, "fixed_attrs"), "location": (Location, "geo_attrs")}


class RevalidationFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class _Judged(NamedTuple):
    flag_id: uuid.UUID
    card_id: uuid.UUID
    setting: str | None
    confidence: float | None
    resolved: bool


def _claim(novel_id: uuid.UUID, revalidation_id: uuid.UUID) -> uuid.UUID | None:
    with SessionLocal() as db:
        flag_id = db.scalar(
            update(FlagRevalidation)
            .where(
                FlagRevalidation.id == revalidation_id,
                FlagRevalidation.novel_id == novel_id,
                FlagRevalidation.status == "queued",
            )
            .values(status="running", started_at=func.now())
            .returning(FlagRevalidation.flag_id)
        )
        db.commit()
        return flag_id


def _finish_failed(novel_id: uuid.UUID, revalidation_id: uuid.UUID, code: str) -> None:
    with SessionLocal() as db:
        db.execute(
            update(FlagRevalidation)
            .where(
                FlagRevalidation.id == revalidation_id,
                FlagRevalidation.novel_id == novel_id,
                FlagRevalidation.status == "running",
            )
            .values(status="failed", error=code, finished_at=func.now())
        )
        db.commit()


def _read_card(db: Session, novel_id: uuid.UUID, claim: Claim) -> Card:
    kind = claim.subject_kind or ""
    if kind not in _CARDS or claim.subject_id is None:
        raise RevalidationFailed("card_missing")
    model, attrs_field = _CARDS[kind]
    card = db.scalar(select(model).where(model.id == claim.subject_id, model.novel_id == novel_id))
    if card is None:
        raise RevalidationFailed("card_missing")
    return Card(
        kind=kind,
        id=card.id,
        name=card.name,
        attrs=text_values(getattr(card, attrs_field)),
        sources=source_episodes(card.attr_sources),
    )


def _read_flag(db: Session, novel_id: uuid.UUID, flag_id: uuid.UUID) -> tuple[ContradictionFlag, Claim]:
    row = db.execute(
        select(ContradictionFlag, Claim)
        .join(Claim, Claim.id == ContradictionFlag.claim_id)
        .where(ContradictionFlag.id == flag_id, ContradictionFlag.novel_id == novel_id, Claim.novel_id == novel_id)
    ).one_or_none()
    if row is None:
        raise RevalidationFailed("flag_missing")
    flag, claim = row
    if flag.status != "open":
        raise RevalidationFailed("flag_handled")
    return flag, claim


def _judge(novel_id: uuid.UUID, flag_id: uuid.UUID) -> _Judged:
    with SessionLocal() as db:
        flag, claim = _read_flag(db, novel_id, flag_id)
        card = _read_card(db, novel_id, claim)
        # The episode's subjects of this kind, as the run saw them: which
        # sentence the model reads depends on them (pipeline/judges.py).
        subjects = {
            normalize_name(name or "")
            for name in db.scalars(
                select(Claim.subject_name).where(
                    Claim.novel_id == novel_id,
                    Claim.episode_id == claim.episode_id,
                    Claim.subject_kind == claim.subject_kind,
                    Claim.subject_name.is_not(None),
                )
            )
        }
        attribute = flag.attribute or ""
        value = (claim.attributes or {}).get(attribute)
        subject = claim.subject_name or card.name
        evidence, text, episode_id = claim.evidence_text, claim.text, claim.episode_id
    try:
        confidence = rejudge(card, attribute, value, subject, evidence, text, subjects, episode_id)
    except InferenceError as exc:
        logger.exception("Novel %s: the NLI model failed", novel_id)
        raise RevalidationFailed("inference_failed") from exc
    return _Judged(
        flag_id=flag_id,
        card_id=card.id,
        setting=card.attrs.get(attribute),
        confidence=confidence,
        resolved=confidence is None or confidence < CONTRADICTION_THRESHOLD,
    )


def _store(novel_id: uuid.UUID, revalidation_id: uuid.UUID, judged: _Judged) -> None:
    with SessionLocal() as db:
        novel = db.scalar(select(Novel.id).where(Novel.id == novel_id, Novel.deleted_at.is_(None)).with_for_update())
        if novel is None:
            raise RevalidationFailed("flag_missing")
        revalidation = db.scalar(
            select(FlagRevalidation).where(
                FlagRevalidation.id == revalidation_id, FlagRevalidation.novel_id == novel_id
            )
        )
        if revalidation is None or revalidation.status != "running":
            logger.warning("Revalidation %s was given up on or replaced; discarding its result", revalidation_id)
            return
        flag, claim = _read_flag(db, novel_id, judged.flag_id)
        card = _read_card(db, novel_id, claim)
        if card.id != judged.card_id or card.attrs.get(flag.attribute or "") != judged.setting:
            raise RevalidationFailed("setting_changed")

        if judged.resolved:
            flag.status = "resolved_by_revalidation"
        if judged.setting is not None:
            flag.reference_text = judged.setting
        flag.confidence = judged.confidence
        revalidation.status = "succeeded"
        revalidation.outcome = "resolved" if judged.resolved else "contradicts"
        revalidation.setting = judged.setting
        revalidation.confidence = judged.confidence
        revalidation.finished_at = func.now()
        db.commit()


def revalidate_flag(novel_id: uuid.UUID, revalidation_id: uuid.UUID) -> None:
    flag_id = _claim(novel_id, revalidation_id)
    if flag_id is None:
        logger.info("Revalidation %s isn't queued (already taken, given up on, or replaced); skipping", revalidation_id)
        return
    try:
        _store(novel_id, revalidation_id, _judge(novel_id, flag_id))
    except RevalidationFailed as exc:
        _finish_failed(novel_id, revalidation_id, exc.code)
    except Exception:
        logger.exception("Revalidation %s failed", revalidation_id)
        _finish_failed(novel_id, revalidation_id, "internal")
