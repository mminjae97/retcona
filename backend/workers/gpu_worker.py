"""GPU worker (design doc 10.4.1).

Role: embedding, reranker, NLI inference.
Needs batching for efficiency, so batch serving (e.g. vLLM) + limited scaling.
Autoscaled on a combined queue-depth + GPU-utilization metric; cold-start cost
is high, so keeping a minimum instance count (warm pool) should be considered (10.4.5).
"""

from infra.queue_client import get_queue_client


def run() -> None:
    queue = get_queue_client()
    while True:
        job = queue.dequeue()
        if job is None:
            break
        # TODO: batch and run embedding/reranker/NLI inference -> ack
        queue.ack(job["job_id"])


if __name__ == "__main__":
    run()
