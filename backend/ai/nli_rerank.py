"""Reranker · NLI wrapper (design doc chapter 5, 7.2).

Delegates actual inference to an infra.inference_client.InferenceClient
implementation (cpu/gpu). pipeline/judges.py only calls this module and has
no knowledge of what the backend actually is.
"""

from infra.inference_client import NLIScores, get_inference_client


class InferenceError(Exception):
    """The model couldn't be loaded (a download on first use) or run."""


def load_models() -> None:
    """Loads the models now rather than on first use (worker startup)."""
    get_inference_client().load()


def rerank(query: str, candidates: list[str]) -> list[float]:
    return get_inference_client().rerank(query, candidates)


def check_contradictions(pairs: list[tuple[str, str]]) -> list[NLIScores]:
    """NLI scores of each (premise, hypothesis), in order. klue-roberta + KorNLI
    based; needs re-finetuning for the novel narration/dialogue domain (chapter 5)."""
    try:
        return get_inference_client().nli(pairs)
    except Exception as exc:
        raise InferenceError(str(exc)) from exc
