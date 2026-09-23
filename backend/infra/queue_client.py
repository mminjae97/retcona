"""QueueClient interface (design doc 10.4.3, 10.2).

Exposes only three methods: enqueue(job) / dequeue() / ack(job_id).
Business logic (pipeline/, workers/) uses only this interface and doesn't know the implementation.

- Production (GCP): PubSubQueueClient
- Local dev: RedisQueueClient

The QUEUE_PROVIDER environment variable selects the implementation.
"""

import json
import uuid
from abc import ABC, abstractmethod
from typing import Any

import redis


class QueueClient(ABC):
    @abstractmethod
    def enqueue(self, job: dict[str, Any]) -> str:
        """Register a job on the queue and return its job_id."""

    @abstractmethod
    def dequeue(self) -> dict[str, Any] | None:
        """Pop the next job. Returns None if there isn't one."""

    @abstractmethod
    def ack(self, job_id: str) -> None:
        """Acknowledge that a job finished processing (assumes at-least-once delivery; see 10.4.4 idempotency)."""


class RedisQueueClient(QueueClient):
    """Local dev implementation (REDIS_URL): one Redis list, LPUSH in and BRPOP out.

    At-most-once: a job is off the list once dequeued, so a worker that dies
    mid-job loses it, and ack has nothing to do. The job's own record in the
    DB makes that visible instead of silent — a validation run left running
    is given up on after a while and can be run again (api/episodes.py).
    Pub/Sub (production) redelivers instead, which the workers' idempotency
    covers (10.4.4).
    """

    QUEUE_KEY = "retcona:jobs"
    # dequeue waits this long for a job before returning None, so a worker
    # loop gets to check for shutdown in between.
    BLOCK_SECONDS = 5
    CONNECT_TIMEOUT_SECONDS = 5

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        self._redis = redis.Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=self.CONNECT_TIMEOUT_SECONDS,
            # Longer than a BRPOP's own wait, which is the longest a healthy call takes.
            socket_timeout=self.BLOCK_SECONDS + self.CONNECT_TIMEOUT_SECONDS,
        )

    def enqueue(self, job: dict[str, Any]) -> str:
        job_id = str(job.get("job_id") or uuid.uuid4())
        self._redis.lpush(self.QUEUE_KEY, json.dumps({**job, "job_id": job_id}))
        return job_id

    def dequeue(self) -> dict[str, Any] | None:
        popped = self._redis.brpop([self.QUEUE_KEY], timeout=self.BLOCK_SECONDS)
        if popped is None:
            return None
        return json.loads(popped[1])

    def ack(self, job_id: str) -> None:
        pass


class PubSubQueueClient(QueueClient):
    """Production (GCP) implementation."""

    def __init__(self, topic: str):
        self.topic = topic
        # TODO: initialize the google-cloud-pubsub client

    def enqueue(self, job: dict[str, Any]) -> str:
        raise NotImplementedError

    def dequeue(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def ack(self, job_id: str) -> None:
        raise NotImplementedError


def get_queue_client() -> QueueClient:
    import os

    provider = os.environ.get("QUEUE_PROVIDER", "redis")
    if provider == "pubsub":
        return PubSubQueueClient(topic=os.environ.get("PUBSUB_TOPIC", "retcona-validation"))
    return RedisQueueClient(redis_url=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
