"""InferenceClient interface (design doc 10.4.3).

Wraps NLI/reranker inference. INFERENCE_BACKEND=cpu|gpu selects the implementation.
The judgment modules in chapter 7 only call this interface and don't know the actual backend.
"""

import functools
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass

# A klue-roberta model fine-tuned on KLUE-NLI (chapter 5's klue-roberta +
# KorNLI line). Downloaded from Hugging Face on first use (~440 MB), then
# read from the local cache. NLI_MODEL points at another checkpoint or a
# local directory — e.g. one re-finetuned on novel prose (chapter 5).
DEFAULT_NLI_MODEL = "Huffon/klue-roberta-base-nli"
# Pairs per forward pass: bounds memory on a long episode's many claims.
_NLI_BATCH_SIZE = 16
_NLI_MAX_TOKENS = 256


@dataclass(frozen=True)
class NLIScores:
    """Probabilities of the three NLI labels, summing to 1."""

    entailment: float
    neutral: float
    contradiction: float


class InferenceClient(ABC):
    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """Cross-encoder score from the bge-reranker-v2-m3-ko family."""

    @abstractmethod
    def nli(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        """Entailment/contradiction/neutral of each (premise, hypothesis),
        in order — klue-roberta + KorNLI based."""


class CPUInferenceClient(InferenceClient):
    """Runs the models in this process with transformers on the CPU (10.4.1:
    the cost-minimized configuration, 10.5.1). The model is loaded on first
    use and kept for the life of the process."""

    def __init__(self, nli_model: str) -> None:
        self._nli_model_name = nli_model
        self._nli = None
        self._load_lock = threading.Lock()

    def _load_nli(self):
        with self._load_lock:
            if self._nli is None:
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                tokenizer = AutoTokenizer.from_pretrained(self._nli_model_name)
                model = AutoModelForSequenceClassification.from_pretrained(self._nli_model_name).eval()
                # Which output is which label, from the checkpoint's own config.
                label_index = {label.lower(): int(i) for i, label in model.config.id2label.items()}
                missing = {"entailment", "neutral", "contradiction"} - label_index.keys()
                if missing:
                    raise RuntimeError(f"NLI model {self._nli_model_name} has no {sorted(missing)} label(s)")
                self._nli = (tokenizer, model, label_index)
            return self._nli

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        if not pairs:
            return []
        import torch

        tokenizer, model, label_index = self._load_nli()
        scores: list[NLIScores] = []
        for start in range(0, len(pairs), _NLI_BATCH_SIZE):
            batch = pairs[start : start + _NLI_BATCH_SIZE]
            encoded = tokenizer(
                [premise for premise, _ in batch],
                [hypothesis for _, hypothesis in batch],
                padding=True,
                truncation=True,
                max_length=_NLI_MAX_TOKENS,
                return_tensors="pt",
                # RoBERTa has a single token type; the ids the tokenizer would
                # add for the second sentence are out of its embedding's range.
                return_token_type_ids=False,
            )
            with torch.no_grad():
                probs = model(**encoded).logits.softmax(dim=-1).tolist()
            scores.extend(
                NLIScores(
                    entailment=row[label_index["entailment"]],
                    neutral=row[label_index["neutral"]],
                    contradiction=row[label_index["contradiction"]],
                )
                for row in probs
            )
        return scores


class GPUInferenceClient(InferenceClient):
    """Implementation assuming batch serving (e.g. vLLM) (10.4.1)."""

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        raise NotImplementedError


@functools.cache
def get_inference_client() -> InferenceClient:
    # One per process: the CPU client holds the loaded model.
    if os.environ.get("INFERENCE_BACKEND", "cpu") == "gpu":
        return GPUInferenceClient()
    return CPUInferenceClient(nli_model=os.environ.get("NLI_MODEL") or DEFAULT_NLI_MODEL)
