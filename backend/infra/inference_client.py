"""InferenceClient interface (design doc 10.4.3).

Wraps NLI/reranker inference and the NER / extractive QA models of claim
extraction (7.1.1). The judgment modules in chapter 7 only call this
interface and don't know where the models run.

OnnxInferenceClient runs them with ONNX Runtime (10.3): on the GPU through
DirectML where there is one that works, otherwise on the CPU, with the same
results either way. INFERENCE_DEVICE=auto (the default) | gpu | cpu; cpu
never tries the GPU, and gpu (like auto) falls back to the CPU when the GPU
fails. The models are the ones trained in ml/ and exported with
ml/export_onnx.py; there is no PyTorch in the app.
"""

import functools
import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from infra import span_inference
from infra.span_inference import NamedEntity

logger = logging.getLogger(__name__)

# The models trained in ml/ (klue/roberta-base fine-tuned on KorNLI + KLUE-NLI,
# "mixed" in ml/nli/RESULTS.md; on KLUE-NER; on KLUE-MRC), exported to ONNX
# (ml/export_onnx.py, into the run's onnx/ directory). They're kept on the
# machine that trained them for now; NLI_MODEL, NER_MODEL and QA_MODEL point
# elsewhere: an exported directory (model.onnx), or a run directory with one
# in its onnx/. There's no public checkpoint to fall back to yet.
LOCAL_NLI_MODEL = Path(__file__).resolve().parents[2] / "ml" / "nli" / "runs" / "mixed"
LOCAL_NER_MODEL = Path(__file__).resolve().parents[2] / "ml" / "ner" / "runs" / "klue"
LOCAL_QA_MODEL = Path(__file__).resolve().parents[2] / "ml" / "qa" / "runs" / "klue"
# How much more "no answer" must score than the best span to be the answer
# (ml/qa/RESULTS.md: about -10 is where novel prose does best; the model
# declines nearly everything at 0).
DEFAULT_QA_NULL_MARGIN = -10.0
# Pairs per forward pass: bounds memory on a long episode's many claims.
_NLI_BATCH_SIZE = 16
_NLI_MAX_TOKENS = 256
_GPU_PAD_TO_MULTIPLE = 32
_DIRECTML = "DmlExecutionProvider"
_CPU = "CPUExecutionProvider"


@dataclass(frozen=True)
class NLIScores:
    """Probabilities of the three NLI labels, summing to 1."""

    entailment: float
    neutral: float
    contradiction: float


class InferenceClient(ABC):
    def load(self) -> str:
        """Loads the models ahead of the first call, where that means anything,
        and says which they are (for the job runner's startup log)."""
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


def _session(path: Path, provider: str):
    import onnxruntime

    options = onnxruntime.SessionOptions()
    if provider == _DIRECTML:
        # What DirectML requires of a session.
        options.enable_mem_pattern = False
        options.execution_mode = onnxruntime.ExecutionMode.ORT_SEQUENTIAL
        # The fastest GPU of a PC with two (a laptop's integrated one and its own).
        providers = [(_DIRECTML, {"performance_preference": "high_performance", "device_filter": "gpu"}), _CPU]
    else:
        providers = [_CPU]
    return onnxruntime.InferenceSession(str(path), options, providers=providers)


class OnnxModel:
    """One exported model (ml/export_onnx.py): its tokenizer, labels and an
    ONNX Runtime session, on the GPU if asked and it works there, else on the
    CPU. A GPU that fails a run — out of memory, a driver reset — gives way
    to the CPU for the rest of the process, and the run is done again there."""

    def __init__(self, directory: Path, device: str) -> None:
        import onnxruntime
        from transformers import AutoTokenizer

        self.directory = directory
        self.tokenizer = AutoTokenizer.from_pretrained(directory)
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        # Empty for QA, whose two outputs aren't labels.
        self.id2label = {int(index): label for index, label in config.get("id2label", {}).items()}
        self._path = directory / "model.onnx"
        self._lock = threading.Lock()
        self.on_gpu = False
        self._session = None
        if device != "cpu" and _DIRECTML in onnxruntime.get_available_providers():
            try:
                self._session = _session(self._path, _DIRECTML)
                self.on_gpu = _DIRECTML in self._session.get_providers()
            except Exception:
                # Any exception: DirectML's errors can come back undecodable
                # (a UnicodeDecodeError on a non-English Windows).
                logger.warning("Could not run %s on the GPU; using the CPU", directory, exc_info=True)
        if not self.on_gpu:
            if device == "gpu":
                logger.warning("No GPU ONNX Runtime can use (DirectML); %s runs on the CPU", directory)
            self._session = _session(self._path, _CPU)

    @property
    def device(self) -> str:
        return "GPU (DirectML)" if self.on_gpu else "CPU"

    @property
    def pad_to_multiple_of(self) -> int | None:
        """What the tokenizer pads sequences to a multiple of. On the GPU, 32:
        DirectML prepares each input shape it hasn't seen, which costs more
        than running a small batch, so fewer shapes run faster (the padding is
        masked out; the results are the same). On the CPU the padding is only
        more work."""
        return _GPU_PAD_TO_MULTIPLE if self.on_gpu else None

    def run(self, outputs: list[str], encoded) -> list[np.ndarray]:
        feed = {name: np.asarray(encoded[name], dtype=np.int64) for name in ("input_ids", "attention_mask")}
        with self._lock:
            session, on_gpu = self._session, self.on_gpu
        try:
            return session.run(outputs, feed)
        except Exception:
            if not on_gpu:
                raise
            logger.warning("%s failed on the GPU; using the CPU from now on", self.directory, exc_info=True)
            with self._lock:
                # Unless another run already did.
                if self._session is session:
                    self._session = _session(self._path, _CPU)
                    self.on_gpu = False
                session = self._session
            return session.run(outputs, feed)


def model_directory(name: str) -> Path:
    """An exported model's directory, from what NLI_MODEL (...) names or the
    local default: the directory with model.onnx, or a run directory with one
    in its onnx/."""
    path = Path(name)
    for directory in (path, path / "onnx"):
        if (directory / "model.onnx").is_file():
            return directory
    raise RuntimeError(
        f"No exported model in {path} or {path / 'onnx'} (train one in ml/, then export it with ml/export_onnx.py)"
    )


class OnnxInferenceClient(InferenceClient):
    """Runs the models in this process with ONNX Runtime. Each is loaded on
    first use and kept for the life of the process."""

    def __init__(self, nli_model: str, ner_model: str, qa_model: str, device: str = "auto") -> None:
        self._names = {"nli": nli_model, "ner": ner_model, "qa": qa_model}
        self._device = device
        self._models: dict[str, OnnxModel] = {}
        self._load_lock = threading.Lock()

    def _model(self, kind: str) -> OnnxModel:
        with self._load_lock:
            if (model := self._models.get(kind)) is None:
                model = OnnxModel(model_directory(self._names[kind]), self._device)
                if kind == "nli":
                    labels = {label.lower() for label in model.id2label.values()}
                    if missing := {"entailment", "neutral", "contradiction"} - labels:
                        raise RuntimeError(f"NLI model {model.directory} has no {sorted(missing)} label(s)")
                self._models[kind] = model
            return model

    def load(self) -> str:
        # Each on its own: a missing model (a machine that hasn't trained or
        # exported it) is one warning, and doesn't hide the others. A run that
        # needs it tries again and fails with the same message.
        loaded = []
        for kind in ("nli", "ner", "qa"):
            try:
                model = self._model(kind)
                loaded.append(f"{kind.upper()} {model.directory} on the {model.device}")
            except Exception as exc:  # noqa: BLE001 — whatever the load hit, it's a warning here
                logger.warning("Could not load the %s model: %s", kind.upper(), exc)
        return ", ".join(loaded) or "no models"

    def rerank(self, query: str, candidates: list[str]) -> list[float]:
        raise NotImplementedError

    def nli(self, pairs: list[tuple[str, str]]) -> list[NLIScores]:
        if not pairs:
            return []
        model = self._model("nli")
        label_index = {label.lower(): index for index, label in model.id2label.items()}
        scores: list[NLIScores] = []
        for start in range(0, len(pairs), _NLI_BATCH_SIZE):
            batch = pairs[start : start + _NLI_BATCH_SIZE]
            encoded = model.tokenizer(
                [premise for premise, _ in batch],
                [hypothesis for _, hypothesis in batch],
                padding=True,
                pad_to_multiple_of=model.pad_to_multiple_of,
                truncation=True,
                max_length=_NLI_MAX_TOKENS,
                return_tensors="np",
                # RoBERTa has a single token type; the ids the tokenizer would
                # add for the second sentence are out of its embedding's range.
                return_token_type_ids=False,
            )
            [logits] = model.run(["logits"], encoded)
            probs = _softmax(logits)
            scores.extend(
                NLIScores(
                    entailment=float(row[label_index["entailment"]]),
                    neutral=float(row[label_index["neutral"]]),
                    contradiction=float(row[label_index["contradiction"]]),
                )
                for row in probs
            )
        return scores

    def ner(self, texts: list[str]) -> list[list[NamedEntity]]:
        if not texts:
            return []
        return span_inference.recognize(self._model("ner"), texts)

    def answer(self, questions: list[tuple[str, str]], null_margin: float = DEFAULT_QA_NULL_MARGIN) -> list[str]:
        if not questions:
            return []
        return span_inference.answer(self._model("qa"), questions, null_margin)


def _softmax(logits: np.ndarray) -> np.ndarray:
    exp = np.exp(logits - logits.max(axis=-1, keepdims=True))
    return exp / exp.sum(axis=-1, keepdims=True)


def _model_name(env_var: str, local: Path) -> str:
    # A directory is best given as an absolute path: the backend runs from backend/.
    return os.environ.get(env_var, "").strip() or str(local)


@functools.cache
def get_inference_client() -> InferenceClient:
    # One per process: it holds the loaded models.
    device = os.environ.get("INFERENCE_DEVICE", "auto").strip().lower() or "auto"
    if device not in ("auto", "gpu", "cpu"):
        logger.warning("INFERENCE_DEVICE=%r isn't auto, gpu or cpu; using auto", device)
        device = "auto"
    return OnnxInferenceClient(
        nli_model=_model_name("NLI_MODEL", LOCAL_NLI_MODEL),
        ner_model=_model_name("NER_MODEL", LOCAL_NER_MODEL),
        qa_model=_model_name("QA_MODEL", LOCAL_QA_MODEL),
        device=device,
    )
