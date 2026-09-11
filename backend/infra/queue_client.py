"""QueueClient 인터페이스 (설계서 10.4.3, 10.2).

enqueue(job) / dequeue() / ack(job_id) 세 메서드만 노출한다.
비즈니스 로직(pipeline/, workers/)은 이 인터페이스만 사용하고 구현체를 알지 못한다.

- 운영 환경(GCP): PubSubQueueClient
- 로컬 개발: RedisQueueClient

QUEUE_PROVIDER 환경변수로 구현체를 고른다.
"""

from abc import ABC, abstractmethod
from typing import Any


class QueueClient(ABC):
    @abstractmethod
    def enqueue(self, job: dict[str, Any]) -> str:
        """job을 큐에 등록하고 job_id를 반환한다."""

    @abstractmethod
    def dequeue(self) -> dict[str, Any] | None:
        """다음 job을 꺼낸다. 없으면 None."""

    @abstractmethod
    def ack(self, job_id: str) -> None:
        """job 처리 완료를 알린다 (at-least-once 전달 전제, 10.4.4 멱등성 참고)."""


class RedisQueueClient(QueueClient):
    """로컬 개발용 구현체 (REDIS_URL)."""

    def __init__(self, redis_url: str):
        self.redis_url = redis_url
        # TODO: redis-py 클라이언트 초기화

    def enqueue(self, job: dict[str, Any]) -> str:
        raise NotImplementedError

    def dequeue(self) -> dict[str, Any] | None:
        raise NotImplementedError

    def ack(self, job_id: str) -> None:
        raise NotImplementedError


class PubSubQueueClient(QueueClient):
    """운영(GCP) 구현체."""

    def __init__(self, topic: str):
        self.topic = topic
        # TODO: google-cloud-pubsub 클라이언트 초기화

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
