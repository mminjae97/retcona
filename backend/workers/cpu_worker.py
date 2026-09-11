"""CPU worker (design doc 10.4.1).

Role: claim extraction orchestration, rule-based verification, LLM API calls.
Mostly network-wait bound, so throughput scales roughly linearly with more instances.
Target for queue-length-based horizontal autoscaling (Cloud Run).

Requirements (10.4.4):
- Stateless: completes a job using only the job payload and DB queries
- Idempotent: records completion per job_id in the DB so duplicate runs are safe
- Graceful shutdown: on SIGTERM, finish the current job or return it to the queue before exiting
"""

from infra.queue_client import get_queue_client


def run() -> None:
    queue = get_queue_client()
    while True:
        job = queue.dequeue()
        if job is None:
            break
        # TODO: check whether job["job_id"] already completed (idempotency) -> run pipeline -> ack
        queue.ack(job["job_id"])


if __name__ == "__main__":
    run()
