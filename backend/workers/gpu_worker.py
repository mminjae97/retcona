"""GPU 워커 (설계서 10.4.1).

역할: 임베딩, 리랭커, NLI 추론.
배치로 묶어야 효율이 나오므로 배치 서빙(vLLM 등) + 제한적 확장.
큐 깊이 + GPU 사용률 복합 지표로 오토스케일링, 콜드스타트 비용이 커서
최소 인스턴스(warm pool) 유지를 고려한다 (10.4.5).
"""

from infra.queue_client import get_queue_client


def run() -> None:
    queue = get_queue_client()
    while True:
        job = queue.dequeue()
        if job is None:
            break
        # TODO: 배치로 묶어 임베딩/리랭커/NLI 추론 실행 -> ack
        queue.ack(job["job_id"])


if __name__ == "__main__":
    run()
