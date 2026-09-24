"""CPU worker (design doc 10.4.1).

Role: claim extraction orchestration, rule-based verification, LLM API calls.
Mostly network-wait bound, so throughput scales roughly linearly with more instances.
Target for queue-length-based horizontal autoscaling (Cloud Run).

Requirements (10.4.4):
- Stateless: completes a job using only the job payload and DB queries
- Idempotent: records completion per job_id in the DB so duplicate runs are safe
  (a validation job's job_id is its validation_runs row, see pipeline/validate_episode.py)
- Graceful shutdown: on SIGTERM, finish the current job or return it to the queue before exiting

Run: python -m workers.cpu_worker (keeps running until SIGINT/SIGTERM)

Jobs:
- validate_episode {novel_id, episode_id, job_id = the validation run's id}:
  the "run validation" button (2.2), enqueued by api/episodes.py
"""

import logging
import signal
import threading
import uuid

from ai.nli_rerank import load_models
from infra.queue_client import get_queue_client
from models.db import check_database
from pipeline.validate_episode import validate_episode

# By name, not __name__: run as `python -m workers.cpu_worker`, __name__ is "__main__".
logger = logging.getLogger("workers.cpu_worker")

# How long to wait before trying the queue again after it failed (Redis down).
QUEUE_RETRY_SECONDS = 5.0


def handle(job: dict) -> None:
    if job.get("type") == "validate_episode":
        validate_episode(uuid.UUID(job["novel_id"]), uuid.UUID(job["job_id"]))
    else:
        logger.warning("Dropping job %s of unknown type %r", job.get("job_id"), job.get("type"))


def run() -> None:
    # The same startup check as the API server's, minus the nickname column
    # (see workers/purge.py). Logging needs no setup: workers/__init__.py did it.
    check_database(nickname_column=False)
    # The NLI model now, not inside the first job: loading takes a while (a
    # ~440 MB download, for a Hugging Face checkpoint not cached yet), and runs
    # queued behind it would wait on it (and could be given up on,
    # api/episodes.py). If it fails, the worker still starts; the first job
    # that needs it tries again.
    try:
        logger.info("Loaded %s", load_models())
    except Exception:
        logger.exception("Could not load the NLI model; runs will try again when they need it")
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())  # finish the current job, then exit
    queue = get_queue_client()
    logger.info("CPU worker started")
    while not stop.is_set():
        try:
            job = queue.dequeue()
        except Exception:
            logger.exception("Could not read from the job queue; retrying in %d s", QUEUE_RETRY_SECONDS)
            stop.wait(QUEUE_RETRY_SECONDS)
            continue
        if job is None:
            continue
        try:
            handle(job)
        except Exception:
            # validate_episode records its own failures on the run; this is
            # what it couldn't (a malformed job, the database gone).
            logger.exception("Job %s failed", job.get("job_id"))
        queue.ack(job["job_id"])
    logger.info("CPU worker stopped")


if __name__ == "__main__":
    run()
