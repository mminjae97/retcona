"""Exports a trained checkpoint to ONNX, for the app's ONNX Runtime
(design doc 5, 10.3: the app runs no PyTorch).

    python export_onnx.py nli ml/nli/runs/kornli-3ep
    python export_onnx.py ner ml/ner/runs/klue
    python export_onnx.py qa ml/qa/runs/klue

Writes <checkpoint>/onnx/: model.onnx, with the tokenizer and config.json
(the labels) beside it — the directory the backend loads
(backend/infra/inference_client.py), on DirectML or the CPU. The model takes input_ids and
attention_mask, batch and sequence length free; it gives logits (nli, ner)
or start_logits and end_logits (qa), as the PyTorch model does. Then checks
ONNX Runtime's outputs against PyTorch's on a few inputs of different
lengths, and fails if they differ by more than TOLERANCE.

Needs, besides a model directory's requirements.txt: onnx, onnxscript,
onnxruntime.
"""

import argparse
import shutil
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


def _encode(tokenizer, kind: str, framework: str):
    if kind == "ner":
        args = (_TEXTS,)
    else:
        args = ([first for first, _ in _PAIRS], [second for _, second in _PAIRS])
    # As the backend encodes: RoBERTa has one token type, so no token_type_ids.
    return tokenizer(*args, padding=True, return_token_type_ids=False, return_tensors=framework)


def export(kind: str, checkpoint: Path, out: Path) -> None:
    auto, outputs = MODELS[kind]
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = auto.from_pretrained(checkpoint).eval()
    wrapped = _Outputs(model, outputs)
    sample = _encode(tokenizer, kind, "pt")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
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
    model.config.save_pretrained(out)

    session = onnxruntime.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    for batch in (_encode(tokenizer, kind, "pt"), _shorter(_encode(tokenizer, kind, "pt"))):
        with torch.no_grad():
            expected = wrapped(batch["input_ids"], batch["attention_mask"])
        got = session.run(outputs, {name: batch[name].numpy() for name in ("input_ids", "attention_mask")})
        for name, want, have in zip(outputs, expected, got, strict=True):
            difference = float(np.abs(want.numpy() - have).max())
            print(f"{kind} {name} {tuple(have.shape)}: largest difference {difference:.2e}")
            if difference > TOLERANCE:
                raise SystemExit(f"ONNX Runtime differs from PyTorch by {difference} (> {TOLERANCE})")
    print(f"Wrote {path} ({path.stat().st_size / 2**20:.0f} MB)")


def _without_allowzero(path: Path) -> None:
    """The exporter marks its Reshapes allowzero=1 (a 0 in the shape is a 0,
    not "keep this dimension"), which DirectML refuses (E_INVALIDARG) — and
    the session fails. The two only differ where the shape has a 0: here it's
    built from the inputs' sizes, never 0, and constants, checked for one."""
    model = onnx.load(str(path))
    constants = {each.name: numpy_helper.to_array(each) for each in model.graph.initializer}
    constants |= {
        node.output[0]: numpy_helper.to_array(node.attribute[0].t)
        for node in model.graph.node
        if node.op_type == "Constant" and node.attribute and node.attribute[0].name == "value"
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
    onnx.save(model, str(path))


def _shorter(batch):
    # Another batch size and sequence length than the export's sample: the axes are free.
    return {name: tensor[:2, : tensor.shape[1] - 2] for name, tensor in batch.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=sorted(MODELS))
    parser.add_argument("checkpoint", type=Path, help="a trained model directory (runs/...)")
    parser.add_argument("--out", type=Path, help="default: <checkpoint>/onnx")
    args = parser.parse_args()
    export(args.kind, args.checkpoint, args.out or args.checkpoint / "onnx")


if __name__ == "__main__":
    main()
