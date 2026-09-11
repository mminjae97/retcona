"""CPU 워커 (설계서 10.4.1).

역할: 클레임 추출 오케스트레이션, 규칙 기반 검증, LLM API 호출.
네트워크 대기 위주라 가볍게 늘릴수록 처리량이 비례 증가한다.
큐 길이 기반 수평 오토스케일링 대상 (Cloud Run).

요구사항 (10.4.4):
- 무상태: job payload와 DB 조회만으로 작업을 완결한다
- 멱등성: job_id로 처리 완료 여부를 DB에 기록해 중복 실행에 안전하게 한다
- Graceful shutdown: SIGTERM 수신 시 처리 중인 job을 마치거나 큐에 반환 후 종료
"""

from infra.queue_client import get_queue_client


def run() -> None:
    queue = get_queue_client()
    while True:
        job = queue.dequeue()
        if job is None:
            break
        # TODO: job["job_id"] 처리 완료 여부 확인(멱등성) -> pipeline 실행 -> ack
        queue.ack(job["job_id"])


if __name__ == "__main__":
    run()
