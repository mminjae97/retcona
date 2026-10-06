"""InferenceClient interface (design doc 10.4.3).

Wraps NLI/reranker inference and the NER / extractive QA models of claim
extraction (7.1.1). INFERENCE_BACKEND=cpu|gpu selects the implementation.
The judgment modules in chapter 7 only call this interface and don't know the actual backend.
"""

import functools
import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from infra import span_inference
from infra.span_inference import NamedEntity

logger = logging.getLogger(__name__)

# The NLI model is the one trained in ml/nli (klue/roberta-base on KorNLI +
# KLUE-NLI, "mixed" in ml/nli/RESULTS.md), which is kept on the machine that
# trained it for now: this directory, or wherever NLI_MODEL points (a local
# directory or a Hugging Face id). Without it, the worker falls back to a
# public checkpoint (klue-roberta on KLUE-NLI, downloaded on first use,
# ~440 MB) that misses about half the contradictions in novel prose.
LOCAL_NLI_MODEL = Path(__file__).resolve().parents[2] / "ml" / "nli" / "runs" / "mixed"
FALLBACK_NLI_MODEL = "Huffon/klue-roberta-base-nli"
# The NER and QA models of claim extraction (ml/ner, ml/qa: klue/roberta-base on
# KLUE-NER and KLUE-MRC), also kept on the machine that trained them; NER_MODEL
# and QA_MODEL point elsewhere. There's no public checkpoint to fall back to.
LOCAL_NER_MODEL = Path(__file__).resolve().parents[2] / "ml" / "ner" / "runs" / "klue"
LOCAL_QA_MODEL = Path(__file__).resolve().parents[2] / "ml" / "qa" / "runs" / "klue"
# How much more "no answer" must score than the best span to be the answer
# (ml/qa/RESULTS.md: about -10 is where novel prose does best; the model
# declines nearly everything at 0).
DEFAULT_QA_NULL_MARGIN = -10.0
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
    def load(self) -> str:
        """Loads the models ahead of the first call, where that means anything,
        and says which they are (for the worker's startup log)."""
        return type(self).__name__

    @abstractmethod
    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        """Cross-encoder score from the bge-reranker-v2-m3-ko family."""

    @abstractmethod
    def nli(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        """Entailment/contradiction/neutral of each (premise, hypothesis),
        in order — klue-roberta + KorNLI based."""

    @abstractmethod
    def ner(self, texts: list[str]) -> list[list[NamedEntity]]:
        """The named entities of each text (a sentence), in order — klue-roberta
        on KLUE-NER; all six types, of which the extractor uses PS and LC."""

    @abstractmethod
    def answer(self, questions: list[tuple[str, str]], null_margin: float = DEFAULT_QA_NULL_MARGIN) -> list[str]:
        """The answer to each (question, context), in order, "" where the context
        doesn't give one — klue-roberta on KLUE-MRC."""


class CPUInferenceClient(InferenceClient):
    """Runs the models in this process with transformers on the CPU (10.4.1:
    the cost-minimized configuration, 10.5.1). The model is loaded on first
    use and kept for the life of the process."""

    def __init__(self, nli_model: str, ner_model: str | None = None, qa_model: str | None = None) -> None:
        self._nli_model_name = nli_model
        self._ner_model_name = ner_model
        self._qa_model_name = qa_model
        self._nli = None
        self._ner = None
        self._qa = None
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

    def _load_span_model(self, kind: str):
        # kind: "ner" or "qa"
        name = self._ner_model_name if kind == "ner" else self._qa_model_name
        with self._load_lock:
            if (loaded := getattr(self, f"_{kind}")) is not None:
                return loaded
            if name is None:
                local = LOCAL_NER_MODEL if kind == "ner" else LOCAL_QA_MODEL
                raise RuntimeError(
                    f"No trained {kind.upper()} model at {local} and {kind.upper()}_MODEL isn't set "
                    f"(train one with ml/{kind}, see its README)"
                )
            from transformers import (
                AutoModelForQuestionAnswering,
                AutoModelForTokenClassification,
                AutoTokenizer,
            )

            auto = AutoModelForTokenClassification if kind == "ner" else AutoModelForQuestionAnswering
            loaded = (AutoTokenizer.from_pretrained(name), auto.from_pretrained(name).eval())
            setattr(self, f"_{kind}", loaded)
            return loaded

    def load(self) -> str:
        self._load_nli()
        self._load_span_model("ner")
        self._load_span_model("qa")
        return f"NLI {self._nli_model_name}, NER {self._ner_model_name}, QA {self._qa_model_name}"

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

    def ner(self, texts: list[str]) -> list[list[NamedEntity]]:
        if not texts:
            return []
        tokenizer, model = self._load_span_model("ner")
        return span_inference.recognize(model, tokenizer, texts)

    def answer(self, questions: list[tuple[str, str]], null_margin: float = DEFAULT_QA_NULL_MARGIN) -> list[str]:
        if not questions:
            return []
        tokenizer, model = self._load_span_model("qa")
        return span_inference.answer(model, tokenizer, questions, null_margin)


class GPUInferenceClient(InferenceClient):
    """Implementation assuming batch serving (e.g. vLLM) (10.4.1)."""

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        raise NotImplementedError

    def ner(self, texts: list[str]) -> list[list[NamedEntity]]:
        raise NotImplementedError

    def answer(self, questions: list[tuple[str, str]], null_margin: float = DEFAULT_QA_NULL_MARGIN) -> list[str]:
        raise NotImplementedError


def _trained_model(env_var: str, local: Path) -> str | None:
    # Like NLI_MODEL: a directory is best given as an absolute path.
    if configured := os.environ.get(env_var, "").strip():
        return configured
    return str(local) if (local / "config.json").is_file() else None


def _nli_model() -> str:
    # A directory is best given as an absolute path: the worker runs from
    # backend/, and a relative one that isn't found there reads as a Hugging
    # Face id.
    if configured := os.environ.get("NLI_MODEL", "").strip():
        return configured
    if (LOCAL_NLI_MODEL / "config.json").is_file():
        return str(LOCAL_NLI_MODEL)
    logger.warning(
        "No trained NLI model at %s and NLI_MODEL isn't set; using %s, which misses more contradictions "
        "(train one with ml/nli, see its README)",
        LOCAL_NLI_MODEL,
        FALLBACK_NLI_MODEL,
    )
    return FALLBACK_NLI_MODEL


@functools.cache
def get_inference_client() -> InferenceClient:
    # One per process: the CPU client holds the loaded model.
    if os.environ.get("INFERENCE_BACKEND", "cpu") == "gpu":
        return GPUInferenceClient()
    return CPUInferenceClient(
        nli_model=_nli_model(),
        ner_model=_trained_model("NER_MODEL", LOCAL_NER_MODEL),
        qa_model=_trained_model("QA_MODEL", LOCAL_QA_MODEL),
    )
