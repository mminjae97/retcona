"""One "run validation" job on an episode (design doc 2.2, 7.1), as the CPU worker runs it.

The pipeline (7.1): claim extraction, then the context bundle, the judgment
modules (appearance and location so far, pipeline/judges.py) and the merge,
then entity matching / auto-registration and applying what the episode adds
to the settings (7.4).

The run row (models/validation_run.py) carries the job through
queued -> running -> succeeded | failed. Steps:
1. Claim the run: queued -> running, in one conditional UPDATE, so a job
   delivered twice runs once (10.4.4).
2. Read the episode and the novel's known names, in a short transaction.
3. Call the model with no transaction open: it can take a while, and holding
   the novel's row lock through it would block the author's saves.
4. Read the setting cards the claims are about (the context bundle), and
   judge the claims against them — NLI, also with no transaction open.
5. Write everything in one transaction under the novel's row lock: replace
   this episode's earlier claims and flags, match or register entities,
   store the new claims and their flags, fill in what the episode adds to the
   settings, finish the run. A run the API gave up on in the meantime
   (api/episodes.py, abandoned) writes nothing. A card the author edited
   between steps 4 and 5 is judged as it was at step 4; its new values are
   kept either way (only empty attributes are filled in).

A failure is recorded on the run as an error code the editor turns into a
message: episode_missing, empty_manuscript, llm_failed, bad_llm_response,
inference_failed, internal.
"""

import logging
import uuid
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ai.nli_rerank import InferenceError
from models.character import Character
from models.claim import Claim, ContradictionFlag
from models.db import SessionLocal
from models.episode import Episode
from models.location import Location
from models.novel import Novel
from models.validation_run import ValidationRun
from pipeline.context_bundle import get_context_bundle
from pipeline.entities import match_and_register
from pipeline.extract_claims import Extraction, ExtractionError, extract_claims
from pipeline.judges import Flag, judge_appearance, judge_location
from pipeline.merge import apply_new_information, merge_and_dedupe

logger = logging.getLogger(__name__)


class RunFailed(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _claim_run(novel_id: uuid.UUID, run_id: uuid.UUID) -> uuid.UUID | None:
    with SessionLocal() as db:
        episode_id = db.scalar(
            update(ValidationRun)
            .where(ValidationRun.id == run_id, ValidationRun.novel_id == novel_id, ValidationRun.status == "queued")
            .values(status="running", started_at=func.now())
            .returning(ValidationRun.episode_id)
        )
        db.commit()
        return episode_id


def _finish_failed(novel_id: uuid.UUID, run_id: uuid.UUID, code: str) -> None:
    with SessionLocal() as db:
        db.execute(
            update(ValidationRun)
            .where(ValidationRun.id == run_id, ValidationRun.novel_id == novel_id, ValidationRun.status == "running")
            .values(status="failed", error=code, finished_at=func.now())
        )
        db.commit()


def _lock_novel(db: Session, novel_id: uuid.UUID) -> None:
    # A soft-deleted novel's runs have nowhere to show their results.
    novel = db.scalar(
        select(Novel.id).where(Novel.id == novel_id, Novel.deleted_at.is_(None)).with_for_update()
    )
    if novel is None:
        raise RunFailed("episode_missing")


def _read_input(novel_id: uuid.UUID, episode_id: uuid.UUID) -> tuple[str, datetime, list[str], list[str]]:
    with SessionLocal() as db:
        row = db.execute(
            select(Episode.content, Episode.updated_at)
            .join(Novel, Novel.id == Episode.novel_id)
            .where(Episode.id == episode_id, Episode.novel_id == novel_id, Novel.deleted_at.is_(None))
        ).one_or_none()
        if row is None:
            raise RunFailed("episode_missing")
        if not row.content.strip():
            raise RunFailed("empty_manuscript")
        characters = list(db.scalars(select(Character.name).where(Character.novel_id == novel_id)))
        # Distinct: nothing stops two locations sharing a name, and the model needs it once.
        locations = list(db.scalars(select(Location.name).where(Location.novel_id == novel_id).distinct()))
        return row.content, row.updated_at, characters, locations


def _judge(novel_id: uuid.UUID, episode_id: uuid.UUID, extraction: Extraction) -> list[Flag]:
    with SessionLocal() as db:
        bundle = get_context_bundle(db, novel_id, episode_id, extraction.claims)
    try:
        return merge_and_dedupe(
            [judge_appearance(extraction.claims, bundle), judge_location(extraction.claims, bundle)]
        )
    except InferenceError as exc:
        logger.exception("Novel %s: the NLI model failed", novel_id)
        raise RunFailed("inference_failed") from exc


def _store(
    novel_id: uuid.UUID,
    run_id: uuid.UUID,
    episode_id: uuid.UUID,
    content_updated_at: datetime,
    extraction: Extraction,
    flags: list[Flag],
) -> None:
    with SessionLocal() as db:
        _lock_novel(db, novel_id)
        run = db.scalar(
            select(ValidationRun).where(ValidationRun.id == run_id, ValidationRun.novel_id == novel_id)
        )
        if run is None or run.status != "running":
            logger.warning("Validation run %s was given up on before it finished; discarding its results", run_id)
            return
        episode_index = db.scalar(
            select(Episode.episode_index).where(Episode.id == episode_id, Episode.novel_id == novel_id)
        )
        if episode_index is None:
            raise RunFailed("episode_missing")

        # A new run replaces the episode's earlier claims (and their flags):
        # they describe content that has since been validated again.
        earlier = select(Claim.id).where(Claim.novel_id == novel_id, Claim.episode_id == episode_id)
        db.execute(
            delete(ContradictionFlag).where(
                ContradictionFlag.novel_id == novel_id, ContradictionFlag.claim_id.in_(earlier)
            )
        )
        db.execute(delete(Claim).where(Claim.novel_id == novel_id, Claim.episode_id == episode_id))

        registration = match_and_register(db, novel_id, episode_id, extraction.claims)
        subject_ids = [registration.subject_id(claim) for claim in extraction.claims]
        claim_ids = [uuid.uuid4() for _ in extraction.claims]
        db.add_all(
            Claim(
                id=claim_id,
                novel_id=novel_id,
                episode_id=episode_id,
                text=claim.text,
                claim_type=claim.claim_type,
                subject_kind=claim.subject_kind,
                subject_id=subject_id,
                subject_name=claim.subject,
                evidence_text=claim.evidence,
                attributes=claim.attributes,
            )
            for claim_id, claim, subject_id in zip(claim_ids, extraction.claims, subject_ids, strict=True)
        )
        db.add_all(
            ContradictionFlag(
                novel_id=novel_id,
                claim_id=claim_ids[flag.claim_index],
                error_type=flag.error_type,
                attribute=flag.attribute,
                confidence=flag.confidence,
                evidence_text=flag.evidence_text,
                reference_text=flag.reference_text,
                status="open",
            )
            for flag in flags
        )
        apply_new_information(db, novel_id, episode_id, episode_index, extraction.claims, subject_ids, flags)

        run.status = "succeeded"
        run.finished_at = func.now()
        run.content_updated_at = content_updated_at
        run.summary = {
            "claims": len(extraction.claims),
            "dropped_claims": extraction.dropped,
            "new_characters": registration.new_characters,
            "new_locations": registration.new_locations,
            "flags": len(flags),
        }
        # "submitted" means validated (2.2) — only if what was validated is
        # still what's saved (a save during the run already made it a draft).
        # updated_at is set to itself: left out, its onupdate would bump it,
        # and this run would read as out of date the moment it finished.
        db.execute(
            update(Episode)
            .where(
                Episode.id == episode_id,
                Episode.novel_id == novel_id,
                Episode.updated_at == content_updated_at,
            )
            .values(status="submitted", updated_at=Episode.updated_at)
        )
        db.commit()


def validate_episode(novel_id: uuid.UUID, run_id: uuid.UUID) -> None:
    episode_id = _claim_run(novel_id, run_id)
    if episode_id is None:
        logger.info("Validation run %s isn't queued (already taken, or given up on); skipping", run_id)
        return
    try:
        content, content_updated_at, characters, locations = _read_input(novel_id, episode_id)
        try:
            extraction = extract_claims(novel_id, content, characters, locations)
        except ExtractionError as exc:
            logger.warning("Validation run %s: couldn't read the model's response (%s)", run_id, exc)
            raise RunFailed("bad_llm_response") from exc
        except Exception as exc:
            logger.exception("Validation run %s: the model call failed", run_id)
            raise RunFailed("llm_failed") from exc
        flags = _judge(novel_id, episode_id, extraction)
        _store(novel_id, run_id, episode_id, content_updated_at, extraction, flags)
    except RunFailed as exc:
        _finish_failed(novel_id, run_id, exc.code)
    except Exception:
        logger.exception("Validation run %s failed", run_id)
        _finish_failed(novel_id, run_id, "internal")
