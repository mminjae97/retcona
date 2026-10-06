"""Reranker · NLI · NER · extractive QA wrapper (design doc chapter 5, 7.1.1, 7.2).

Delegates actual inference to an infra.inference_client.InferenceClient
implementation (cpu/gpu). pipeline/judges.py and the claim extraction only
call this module and have no knowledge of what the backend actually is.
"""

from infra.inference_client import (
    DEFAULT_QA_NULL_MARGIN,
    NLIScores,
    get_inference_client,
)
from infra.span_inference import NamedEntity


class InferenceError(Exception):
    """The model couldn't be loaded (a download on first use) or run."""


def load_models() -> str:
    """Loads the models now rather than on first use (worker startup); says which."""
    return get_inference_client().load()


def rerank(query: str, candidates: list[str]) -> list[float]:
    return get_inference_client().rerank(query, candidates)


def check_contradictions(pairs: list[tuple[str, str]]) -> list[NLIScores]:
    """NLI scores of each (premise, hypothesis), in order. klue-roberta + KorNLI
    based; needs re-finetuning for the novel narration/dialogue domain (chapter 5)."""
    try:
        return get_inference_client().nli(pairs)
    except Exception as exc:
        raise InferenceError(str(exc)) from exc


def recognize_entities(texts: list[str]) -> list[list[NamedEntity]]:
    """The named entities of each text (a sentence), in order. The extractor
    uses the PS (person) and LC (location) ones."""
    try:
        return get_inference_client().ner(texts)
    except Exception as exc:
        raise InferenceError(str(exc)) from exc


def answer_questions(
    questions: list[tuple[str, str]], null_margin: float = DEFAULT_QA_NULL_MARGIN
) -> list[str]:
    """The answer to each (question, context), in order; "" where the context
    doesn't give one."""
    try:
        return get_inference_client().answer(questions, null_margin)
    except Exception as exc:
        raise InferenceError(str(exc)) from exc
