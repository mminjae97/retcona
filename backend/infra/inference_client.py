"""InferenceClient interface (design doc 10.4.3).

Wraps NLI/reranker inference. INFERENCE_BACKEND=cpu|gpu selects the implementation.
The judgment modules in chapter 7 only call this interface and don't know the actual backend.
"""

from abc import ABC, abstractmethod


class InferenceClient(ABC):
    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """Cross-encoder score from the bge-reranker-v2-m3-ko family."""

    @abstractmethod
    def nli(self, premise: str, hypothesis: str) -> dict:
        """Entailment/contradiction/neutral judgment based on klue-roberta + KorNLI."""


class CPUInferenceClient(InferenceClient):
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, premise: str, hypothesis: str) -> dict:
        raise NotImplementedError


class GPUInferenceClient(InferenceClient):
    """Implementation assuming batch serving (e.g. vLLM) (10.4.1)."""

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, premise: str, hypothesis: str) -> dict:
        raise NotImplementedError


def get_inference_client() -> InferenceClient:
    import os

    backend = os.environ.get("INFERENCE_BACKEND", "cpu")
    return GPUInferenceClient() if backend == "gpu" else CPUInferenceClient()
