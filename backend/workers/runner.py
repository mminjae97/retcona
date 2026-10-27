"""The job runner (design doc 10.2, 10.4.1): runs the queue's jobs one at a time,
in a thread of the backend process (api/main.py starts it), so no worker
process or queue server has to be started besides the app. One at a time also
keeps the models' memory in bounds.

Jobs (each takes its row: a job whose row isn't waiting for it is skipped, 10.4.4):
- validate_episode {novel_id, episode_id}, target = the validation run: the
  "run validation" button (2.2), enqueued by api/episodes.py
- revalidate_flag {novel_id}, target = the flag revalidation: one flag judged
  again after its setting was supplemented (7.5), enqueued by api/episodes.py
- judge_linked_claim {novel_id}, target = the claim: a claim the author picked
  a card for (7.1.1), judged against it; enqueued by api/episodes.py

At startup the runner takes the database's runner lock — a second backend
process on the same database runs no jobs, so none runs in two places — then
queues again the jobs an earlier start was in the middle of (10.4.4), and loads
the models before taking the first job. A job is acked (leaves the queue) when
it returns or raises: the jobs record their own failures on their rows, and a
row a job couldn't record on is failed by the API once no job for it is
pending (api/episodes.py, abandoned). Closing the app in the middle of a job
puts it back without counting the attempt.
"""

import logging
import threading
import uuid
from collections.abc import Callable

from ai.nli_rerank import load_models
from infra.queue_client import QueueClient, QueuedJob
from pipeline.extraction_rules import load_tagger
from pipeline.judge_linked_claim import judge_linked_claim
from pipeline.revalidate_flag import revalidate_flag
from pipeline.validate_episode import validate_episode

logger = logging.getLogger(__name__)

# How often an idle runner looks at the queue anyway. A job committed in this
# process wakes it at once (QueueClient.wait_for_job); this is the fallback.
POLL_SECONDS = 30.0
# How long to wait before trying the queue again after it failed (the database down).
QUEUE_RETRY_SECONDS = 5.0
# How often a runner without the lock (another backend process has it) tries again.
LOCK_RETRY_SECONDS = 10.0
# A job started this many times without finishing (the app crashed, or was
# killed, in the middle of it each time) isn't started again.
MAX_ATTEMPTS = 3

HANDLERS: dict[str, Callable[[uuid.UUID, uuid.UUID], None]] = {
    "validate_episode": validate_episode,
    "revalidate_flag": revalidate_flag,
    "judge_linked_claim": judge_linked_claim,
}


def load_resources() -> None:
    """The models (NLI, NER, QA, and the extraction rules' part-of-speech
    tagger) now, not inside the first job: loading takes a while (a ~440 MB
    download, for a Hugging Face checkpoint not cached yet). If it fails, the
    runner still starts; the first job that needs them tries again."""
    logger.info("Loading the models")
    try:
        logger.info("Loaded %s", load_models())
    except Exception:
        logger.exception("Could not load the models; jobs will try again when they need them")
    try:
        load_tagger()
    except Exception:
        logger.exception("Could not load the part-of-speech tagger; jobs will try again when they need it")


def handle(job: QueuedJob) -> None:
    handler = HANDLERS.get(job.type)
    if handler is None:
        logger.warning("Dropping job %s of unknown type %r", job.id, job.type)
        return
    if job.target_id is None:
        logger.warning("Dropping job %s (%s): it names no row to work on", job.id, job.type)
        return
    handler(uuid.UUID(job.payload["novel_id"]), job.target_id)


class JobRunner:
    def __init__(self, queue: QueueClient, load: Callable[[], None] = load_resources) -> None:
        self._queue = queue
        self._load = load
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="job-runner", daemon=True)
        # The job being run, for stop() to put back.
        self._current: uuid.UUID | None = None

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Takes no further job and waits a little for the current one. One
        still going then is put back on the queue, not counted as an attempt,
        and is cut off with the process (a daemon thread): it runs again at the
        next start."""
        self._stop.set()
        self._queue.wake()
        self._thread.join(timeout)
        if self._thread.is_alive() and (job_id := self._current) is not None:
            try:
                self._queue.release(job_id)
            except Exception:
                # Left running: the next start queues it again, as one attempt.
                logger.exception("Could not put job %s back on the queue", job_id)

    def _run(self) -> None:
        if not self._take_lock() or not self._recover():
            return
        self._load()
        logger.info("Job runner started")
        while not self._stop.is_set():
            self.run_once()
        logger.info("Job runner stopped")

    def _take_lock(self) -> bool:
        told = False
        while not self._stop.is_set():
            try:
                if self._queue.hold_runner_lock():
                    return True
                if not told:
                    logger.warning(
                        "Another backend process is running this database's jobs; this one runs none while it does"
                    )
                    told = True
                self._stop.wait(LOCK_RETRY_SECONDS)
            except Exception:
                logger.exception("Could not take the job runner lock; retrying in %d s", QUEUE_RETRY_SECONDS)
                self._stop.wait(QUEUE_RETRY_SECONDS)
        return False

    def _recover(self) -> bool:
        # Before taking any job: until it succeeds, those jobs would stay
        # running, pending to the API, and never run.
        while not self._stop.is_set():
            try:
                if requeued := self._queue.recover():
                    logger.info("Queued again %d job(s) an earlier start didn't finish", requeued)
                return True
            except Exception:
                logger.exception(
                    "Could not queue again the jobs an earlier start didn't finish; retrying in %d s",
                    QUEUE_RETRY_SECONDS,
                )
                self._stop.wait(QUEUE_RETRY_SECONDS)
        return False

    def run_once(self) -> None:
        """Takes and runs one job, or waits for one if there's none."""
        try:
            job = self._queue.dequeue()
        except Exception:
            logger.exception("Could not read from the job queue; retrying in %d s", QUEUE_RETRY_SECONDS)
            self._stop.wait(QUEUE_RETRY_SECONDS)
            return
        if job is None:
            self._queue.wait_for_job(POLL_SECONDS)
            return
        self._current = job.id
        try:
            if job.attempts > MAX_ATTEMPTS:
                logger.error(
                    "Giving up on job %s (%s): started %d times without finishing", job.id, job.type, MAX_ATTEMPTS
                )
            else:
                try:
                    handle(job)
                except Exception:
                    # The jobs record their own failures (on the run / the
                    # revalidation / the claim); this is what they couldn't (a
                    # malformed job, the database gone).
                    logger.exception("Job %s failed", job.id)
            self._ack(job.id)
        finally:
            self._current = None

    def _ack(self, job_id: uuid.UUID) -> None:
        # Retried rather than left: a job left running in the table stays
        # pending to the API (until JOB_RUNNING_LIMIT), and the next one can't
        # be taken while the database is down anyway.
        while True:
            try:
                self._queue.ack(job_id)
                return
            except Exception:
                logger.exception("Could not take job %s off the queue; retrying in %d s", job_id, QUEUE_RETRY_SECONDS)
            if self._stop.wait(QUEUE_RETRY_SECONDS):
                # Closing: left running, queued again at the next start (its
                # row tells the job whether anything is left to do).
                return
