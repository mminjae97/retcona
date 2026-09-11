"""리랭커 · NLI 래퍼 (설계서 5장, 7.2).

실제 추론은 infra.inference_client.InferenceClient 구현체(cpu/gpu)에 위임한다.
pipeline/judges.py는 이 모듈만 호출하고 backend가 무엇인지 알지 못한다.
"""

from infra.inference_client import get_inference_client


def rerank(query: str, candidates: list[str]) -> list[float]:
    return get_inference_client().rerank(query, candidates)


def check_contradiction(premise: str, hypothesis: str) -> dict:
    """klue-roberta + KorNLI 기반. 소설 서술체/대사체 도메인 재파인튜닝 필요 (5장)."""
    return get_inference_client().nli(premise, hypothesis)
