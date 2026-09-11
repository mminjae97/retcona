"""InferenceClient 인터페이스 (설계서 10.4.3).

NLI·리랭커 추론을 감싼다. INFERENCE_BACKEND=cpu|gpu 로 구현체를 고른다.
7장의 판단 모듈은 이 인터페이스만 호출하고 실제 백엔드를 알지 못한다.
"""

from abc import ABC, abstractmethod


class InferenceClient(ABC):
    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """bge-reranker-v2-m3-ko 계열 cross-encoder 점수."""

    @abstractmethod
    def nli(self, premise: str, hypothesis: str) -> dict:
        """klue-roberta + KorNLI 기반 함의/모순/중립 판단."""


class CPUInferenceClient(InferenceClient):
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, premise: str, hypothesis: str) -> dict:
        raise NotImplementedError


class GPUInferenceClient(InferenceClient):
    """배치 서빙(vLLM 등)을 전제로 한 구현체 (10.4.1)."""

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, premise: str, hypothesis: str) -> dict:
        raise NotImplementedError


def get_inference_client() -> InferenceClient:
    import os

    backend = os.environ.get("INFERENCE_BACKEND", "cpu")
    return GPUInferenceClient() if backend == "gpu" else CPUInferenceClient()
