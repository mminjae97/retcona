"""The job runner (design doc 10.2, 10.4.1): runs the queue's jobs one at a time,
in a thread of the backend process (api/main.py starts it), so no worker
process or queue server has to be started besides the app. One at a time also
keeps the models' memory in bounds.

Jobs (each takes its row: a job whose row isn't waiting for it is skipped, 10.4.4):
- validate_episode {novel_id}, target = the validation run: the
  "run validation" button (2.2), enqueued by api/episodes.py
- revalidate_flag {novel_id}, target = the flag revalidation: one flag judged
  again after its setting was supplemented (7.5), enqueued by api/episodes.py
- judge_linked_claim {novel_id}, target = the claim: a claim the author picked
  a card for (7.1.1), judged against it; enqueued by api/episodes.py
- empty_trash {}, no target: novels in the trash past their 30 days deleted for
  good (2.6); enqueued at startup and hourly by api/main.py

At startup the runner takes the database's runner lock — a second backend
process on the same database runs no jobs; the lock is checked again before
each job — then queues again the jobs an earlier start was in the middle of
(10.4.4), and loads the models before taking the first job. Taking the lock
and recovering are tried once before the API serves anything (prepare), so
the jobs an earlier start left are queued again before any request reads
them. A job is acked (leaves the queue) when it returns or raises: the jobs
record their own failures on their rows, and a row a job couldn't record on
is failed by the API once no job for it is pending (api/episodes.py,
abandoned). A job the app closed in the middle of,
normally or not, is left running and queued again by the next start's
recovery, which counts it as an attempt: a job that hangs every time is given
up on after MAX_ATTEMPTS starts however the app was closed, so the jobs behind
it run.
"""

import logging
import threading
import uuid
from collections.abc import Callable

from ai.nli_rerank import load_models
from infra.queue_client import QueueClient, QueuedJob
from pipeline.empty_trash import empty_trash
from pipeline.extraction_rules import load_tagger
from pipeline.judge_linked_claim import judge_linked_claim
from pipeline.revalidate_flag import revalidate_flag
from pipeline.validate_episode import validate_episode

logger = logging.getLogger(__name__)

# How often an idle runner looks at the queue anyway (and checks it still holds
# the lock). A job committed in this process wakes it at once
# (QueueClient.wait_for_job); this is for one another process committed.
POLL_SECONDS = 5.0
# How long to wait before trying the queue again after it failed (the database
# locked past its busy timeout, or unreadable).
QUEUE_RETRY_SECONDS = 5.0
# How often a runner without the lock (another backend process has it) tries again.
LOCK_RETRY_SECONDS = 10.0
# A job started this many times without finishing (the app closed in the
# middle of it each time) isn't started again.
MAX_ATTEMPTS = 3

HANDLERS: dict[str, Callable[[uuid.UUID, uuid.UUID], None]] = {
    "validate_episode": validate_episode,
    "revalidate_flag": revalidate_flag,
    "judge_linked_claim": judge_linked_claim,
}
# Jobs on the app as a whole: no novel, no row of their own.
APP_HANDLERS: dict[str, Callable[[], None]] = {
    "empty_trash": empty_trash,
}


def load_resources() -> None:
    """The models (NLI, NER, QA, and the extraction rules' part-of-speech
    tagger) now, not inside the first job: loading takes a while (three ~420
    MB models read and prepared, on the GPU if there is one). If it fails, the
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
    if (app_handler := APP_HANDLERS.get(job.type)) is not None:
        app_handler()
        return
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
        # Holding the lock, with the jobs an earlier start left queued again.
        self._ready = False

    def prepare(self) -> None:
        """Takes the lock and recovers now, if that works at once; otherwise the
        runner keeps trying once started. Blocking: run before start()."""
        try:
            if self._queue.hold_runner_lock():
                self._recover_once()
                self._ready = True
        except Exception:
            logger.exception("Could not prepare the job runner; it will keep trying")

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Takes no further job and waits a little for the current one. One
        still going then is cut off with the process (a daemon thread), left
        running in the queue: the next start queues it again, as one attempt."""
        self._stop.set()
        self._queue.wake()
        self._thread.join(timeout)

    def _run(self) -> None:
        if not self._get_ready():
            return
        self._load()
        logger.info("Job runner started")
        while not self._stop.is_set():
            if not self._still_locked() and not self._get_ready():
                break
            self.run_once()
        logger.info("Job runner stopped")

    def _get_ready(self) -> bool:
        self._ready = self._ready or (self._take_lock() and self._recover())
        return self._ready

    def _still_locked(self) -> bool:
        # Between jobs: a QueueClient whose lock can be lost (DatabaseQueueClient's
        # can't) may find it another process's now, which then runs the jobs instead.
        try:
            if self._queue.hold_runner_lock():
                return True
        except Exception:
            logger.exception("Could not check the job runner lock")
        logger.warning("Lost the job runner lock; taking it again before running any job")
        self._ready = False
        return False

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
                self._recover_once()
                return True
            except Exception:
                logger.exception(
                    "Could not queue again the jobs an earlier start didn't finish; retrying in %d s",
                    QUEUE_RETRY_SECONDS,
                )
                self._stop.wait(QUEUE_RETRY_SECONDS)
        return False

    def _recover_once(self) -> None:
        if requeued := self._queue.recover():
            logger.info("Queued again %d job(s) an earlier start didn't finish", requeued)

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
        if job.attempts > MAX_ATTEMPTS:
            logger.error("Giving up on job %s (%s): started %d times without finishing", job.id, job.type, MAX_ATTEMPTS)
        else:
            try:
                handle(job)
            except Exception:
                # The jobs record their own failures (on the run / the
                # revalidation / the claim); this is what they couldn't (a
                # malformed job, the database gone).
                logger.exception("Job %s failed", job.id)
        self._ack(job.id)

    def _ack(self, job_id: uuid.UUID) -> None:
        # Retried rather than left: a job left running in the table stays
        # pending to the API for the rest of the session, and the next one
        # can't be taken while the database is down anyway.
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
