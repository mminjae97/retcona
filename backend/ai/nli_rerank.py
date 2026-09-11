"""Reranker · NLI wrapper (design doc chapter 5, 7.2).

Delegates actual inference to an infra.inference_client.InferenceClient
implementation (cpu/gpu). pipeline/judges.py only calls this module and has
no knowledge of what the backend actually is.
"""

from infra.inference_client import get_inference_client


def rerank(query: str, candidates: list[str]) -> list[float]:
    return get_inference_client().rerank(query, candidates)


def check_contradiction(premise: str, hypothesis: str) -> dict:
    """Based on klue-roberta + KorNLI. Needs re-finetuning for the novel narration/dialogue domain (chapter 5)."""
    return get_inference_client().nli(premise, hypothesis)
