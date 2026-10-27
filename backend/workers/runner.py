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

At startup the jobs an earlier start was in the middle of are queued again
(10.4.4), and the models are loaded before the first job is taken. A job is
acked (leaves the queue) when it returns or raises: the jobs record their own
failures on their rows, and a row a job couldn't record on is failed by the
API once no job for it is left (api/episodes.py, abandoned).

One backend process per database: a second one's startup would queue again
the jobs the first is running.
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

# How often an idle runner looks at the queue: a job waits at most this long
# to start, and an idle look is one small query.
POLL_SECONDS = 1.0
# How long to wait before trying the queue again after it failed (the database down).
QUEUE_RETRY_SECONDS = 5.0
# A job started this many times without finishing (the app closed, or crashed,
# in the middle of it each time) isn't started again.
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
    if handler is None or job.target_id is None:
        logger.warning("Dropping job %s of unknown type %r", job.id, job.type)
        return
    handler(uuid.UUID(job.payload["novel_id"]), job.target_id)


class JobRunner:
    def __init__(self, queue: QueueClient, load: Callable[[], None] = load_resources) -> None:
        self._queue = queue
        self._load = load
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="job-runner", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Takes no further job and waits a little for the current one. One
        still going then is cut off with the process (a daemon thread) and
        runs again at the next start."""
        self._stop.set()
        self._thread.join(timeout)

    def _run(self) -> None:
        try:
            if requeued := self._queue.recover():
                logger.info("Queued again %d job(s) an earlier start didn't finish", requeued)
        except Exception:
            # They stay running (and pending to the API) until a start that can.
            logger.exception("Could not queue again the jobs an earlier start didn't finish")
        self._load()
        logger.info("Job runner started")
        while not self._stop.is_set():
            self.run_once()
        logger.info("Job runner stopped")

    def run_once(self) -> None:
        """Takes and runs one job, or waits a little if there's none."""
        try:
            job = self._queue.dequeue()
        except Exception:
            logger.exception("Could not read from the job queue; retrying in %d s", QUEUE_RETRY_SECONDS)
            self._stop.wait(QUEUE_RETRY_SECONDS)
            return
        if job is None:
            self._stop.wait(POLL_SECONDS)
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
        try:
            self._queue.ack(job.id)
        except Exception:
            # Still running in the table: queued again at the next start, where
            # its row (finished by now) makes it a no-op.
            logger.exception("Could not take job %s off the queue", job.id)
