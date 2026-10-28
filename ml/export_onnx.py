"""Exports a trained checkpoint to ONNX, for the app's ONNX Runtime
(design doc 5, 10.3: the app runs no PyTorch).

    python ml/export_onnx.py nli ml/nli/runs/mixed
    python ml/export_onnx.py ner ml/ner/runs/klue
    python ml/export_onnx.py qa ml/qa/runs/klue

Writes <checkpoint>/onnx/: model.onnx, with the tokenizer and config.json
(the labels) beside it — the directory the backend loads
(backend/infra/inference_client.py), on DirectML or the CPU. The model takes
input_ids and attention_mask, batch and sequence length free; it gives logits
(nli, ner) or start_logits and end_logits (qa), as the PyTorch model does.
Checks ONNX Runtime's outputs against PyTorch's on a few inputs of different
shapes, and fails if they differ by more than TOLERANCE. The export is built
beside the directory and replaces it only once checked: a failed one leaves
the earlier export as it was.

Needs, besides a model directory's requirements.txt: onnx, onnxscript,
onnxruntime.
"""

import argparse
import shutil
import tempfile
from pathlib import Path

import numpy as np
import onnx
import onnxruntime
import torch
from onnx import numpy_helper
from transformers import (
    AutoModelForQuestionAnswering,
    AutoModelForSequenceClassification,
    AutoModelForTokenClassification,
    AutoTokenizer,
)

MODELS = {
    "nli": (AutoModelForSequenceClassification, ["logits"]),
    "ner": (AutoModelForTokenClassification, ["logits"]),
    "qa": (AutoModelForQuestionAnswering, ["start_logits", "end_logits"]),
}
# The ONNX opset: DirectML, the app's GPU path, takes up to 20.
OPSET = 18
# Largest difference allowed between PyTorch's and ONNX Runtime's logits.
TOLERANCE = 1e-3
# Inputs to check with: pairs for nli and qa, single texts for ner.
_TEXTS = ["레온은 푸른 눈동자로 성문을 바라보았다.", "그녀의 머리카락은 은빛이었다. 바람이 불었다.", "성"]
_PAIRS = [
    ("레온의 눈 색깔은 푸른색이다.", "레온은 붉은 눈동자로 성문을 바라보았다."),
    ("레온의 눈 색깔은?", "레온은 붉은 눈동자로 성문을 바라보았다. 그는 검을 뽑았다. 바람이 거셌다."),
    ("나이는?", "그는 스무 살이었다."),
]


class _Outputs(torch.nn.Module):
    """The model as a function of the two inputs the app gives it, returning
    its logits as a tuple (what the exporter takes)."""

    def __init__(self, model: torch.nn.Module, outputs: list[str]) -> None:
        super().__init__()
        self.model = model
        self.outputs = outputs

    def forward(self, input_ids: torch.Tensor, attention_mask: torch.Tensor) -> tuple[torch.Tensor, ...]:
        result = self.model(input_ids=input_ids, attention_mask=attention_mask)
        return tuple(getattr(result, name) for name in self.outputs)


def _encode(tokenizer, kind: str, framework: str, count: int | None = None):
    # The first count inputs (all by default).
    if kind == "ner":
        args = (_TEXTS[:count],)
    else:
        args = ([first for first, _ in _PAIRS[:count]], [second for _, second in _PAIRS[:count]])
    # As the backend encodes: RoBERTa has one token type, so no token_type_ids.
    return tokenizer(*args, padding=True, return_token_type_ids=False, return_tensors=framework)


def export(kind: str, checkpoint: Path, out: Path) -> None:
    auto, outputs = MODELS[kind]
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = auto.from_pretrained(checkpoint).eval()
    wrapped = _Outputs(model, outputs)
    sample = _encode(tokenizer, kind, "pt")

    _check_replaceable(out, checkpoint)
    out.parent.mkdir(parents=True, exist_ok=True)
    building = Path(tempfile.mkdtemp(prefix=f".{out.name}-", dir=out.parent))
    try:
        _build(kind, wrapped, tokenizer, sample, building)
        _replace(out, building)
    finally:
        shutil.rmtree(building, ignore_errors=True)
    print(f"Wrote {out / 'model.onnx'} ({(out / 'model.onnx').stat().st_size / 2**20:.0f} MB)")


def _replace(out: Path, new: Path) -> None:
    """Puts new at out. An earlier export is moved aside, not deleted, until
    new is in place: a move that fails (Windows refuses one while a file in
    the directory is open, as an antivirus scan may hold it) leaves it whole."""
    if not out.exists():
        new.rename(out)
        return
    # new's name is unique (mkdtemp), so this one is too.
    earlier = new.with_name(f"{new.name}-earlier")
    out.rename(earlier)
    try:
        new.rename(out)
    except BaseException:
        earlier.rename(out)
        raise
    shutil.rmtree(earlier, ignore_errors=True)
    if earlier.exists():
        print(f"Could not delete the earlier export, moved to {earlier}; delete it by hand")


def _build(kind: str, wrapped: _Outputs, tokenizer, sample, out: Path) -> None:
    outputs = wrapped.outputs
    path = out / "model.onnx"
    # The torch.export-based exporter: the older tracing one gets transformers
    # 5's attention masks wrong (logits off by more than 1).
    axes = {0: torch.export.Dim("batch"), 1: torch.export.Dim("sequence")}
    program = torch.onnx.export(
        wrapped,
        (sample["input_ids"], sample["attention_mask"]),
        dynamo=True,
        input_names=["input_ids", "attention_mask"],
        output_names=outputs,
        dynamic_shapes={"input_ids": axes, "attention_mask": axes},
        opset_version=OPSET,
    )
    # One file (a base-size model is well under ONNX's 2 GB limit).
    program.save(str(path), external_data=False)
    _without_allowzero(path)
    tokenizer.save_pretrained(out)
    wrapped.model.config.save_pretrained(out)

    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    try:
        # The export's sample, another batch size and length, and one input alone,
        # unpadded (the backend often runs one: a revalidated flag, a picked claim).
        for batch in (sample, _cut(sample, 2, 2), _encode(tokenizer, kind, "pt", count=1)):
            with torch.no_grad():
                expected = wrapped(batch["input_ids"], batch["attention_mask"])
            got = session.run(outputs, {name: batch[name].numpy() for name in ("input_ids", "attention_mask")})
            for name, want, have in zip(outputs, expected, got, strict=True):
                difference = float(np.abs(want.numpy() - have).max())
                print(f"{kind} {name} {tuple(have.shape)}: largest difference {difference:.2e}")
                if difference > TOLERANCE:
                    raise SystemExit(f"ONNX Runtime differs from PyTorch by {difference} (> {TOLERANCE})")
    finally:
        # Closed, failed or not: Windows can't move or delete a directory with a file in it open.
        del session


def _check_replaceable(out: Path, checkpoint: Path) -> None:
    """Fails unless out is free or an earlier export, which the new one may
    replace: not a directory with no model.onnx, one holding weights or
    folders (a checkpoint, given as --out by mistake), or the checkpoint or
    one of its parents."""
    if not out.exists():
        return
    earlier_export = (
        (out / "model.onnx").is_file()
        and not any(each.is_dir() or each.suffix in {".safetensors", ".bin", ".pt"} for each in out.iterdir())
        and not checkpoint.resolve().is_relative_to(out.resolve())
    )
    if not earlier_export:
        raise SystemExit(f"{out} isn't an earlier export (it has no model.onnx, or holds a checkpoint); not replacing it")


def _constant(node) -> np.ndarray | None:
    for attribute in node.attribute:
        if attribute.name == "value":
            return numpy_helper.to_array(attribute.t)
        if attribute.name in ("value_int", "value_ints"):
            return np.array(attribute.ints if attribute.name == "value_ints" else [attribute.i])
    return None


def _without_allowzero(path: Path) -> None:
    """The exporter marks its Reshapes allowzero=1 (a 0 in the shape is a 0,
    not "keep this dimension"), which DirectML refuses (E_INVALIDARG) — and
    the session fails. The two only differ where the shape has a 0: here it's
    built from the inputs' sizes, never 0, and constants, checked for one.
    Fails on a Reshape inside a local function, which isn't looked into."""
    model = onnx.load(str(path))
    constants = {each.name: numpy_helper.to_array(each) for each in model.graph.initializer}
    constants |= {
        node.output[0]: value
        for node in model.graph.node
        if node.op_type == "Constant" and (value := _constant(node)) is not None
    }
    made_by = {output: node for node in model.graph.node for output in node.output}
    for node in model.graph.node:
        if node.op_type != "Reshape":
            continue
        for attribute in node.attribute:
            if attribute.name == "allowzero" and attribute.i == 1:
                shape = made_by.get(node.input[1])
                parts = shape.input if shape is not None and shape.op_type == "Concat" else [node.input[1]]
                if any(part in constants and (constants[part] == 0).any() for part in parts):
                    raise SystemExit(f"{node.name} reshapes to a 0-sized dimension; it can't drop allowzero")
                attribute.i = 0
    if any(node.op_type == "Reshape" for function in model.functions for node in function.node):
        raise SystemExit("A Reshape is inside a local function; check its allowzero by hand before using this export")
    onnx.save(model, str(path))


def _cut(batch, rows: int, tokens: int):
    """The batch's first rows, its last tokens dropped: another shape than the
    export's sample (the axes are free)."""
    return {name: tensor[:rows, : tensor.shape[1] - tokens] for name, tensor in batch.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=sorted(MODELS))
    parser.add_argument("checkpoint", type=Path, help="a trained model directory (runs/...)")
    parser.add_argument("--out", type=Path, help="default: <checkpoint>/onnx")
    args = parser.parse_args()
    export(args.kind, args.checkpoint, args.out or args.checkpoint / "onnx")


if __name__ == "__main__":
    main()
