"""Evaluates extractive QA models on KLUE-MRC dev and the novel set.

    python evaluate.py --model runs/klue [--errors] [--latency] [--null-margin 0]

An answer is the best-scoring span of the context (start and end logits
summed, at most --max-answer tokens), unless "no answer" (the [CLS] token)
scores higher by more than --null-margin. Scores, per set:
- exact match and character F1 (answers compared with spaces and punctuation
  removed; against the best of the gold answers), over all questions;
- no-answer accuracy: how often an unanswerable question gets no answer, and
  an answerable one gets one.
--errors lists the novel questions the model got wrong; --latency times one
question at a time on the CPU, as the backend's worker would run it.
"""

import argparse
import re
import time
from collections import Counter

import torch
from transformers import AutoModelForQuestionAnswering, AutoTokenizer

from data import Example, load

_NOT_WORD = re.compile(r"[\W_]+")


def predict(
    model, tokenizer, examples: list[Example], device: str, *, null_margin: float = 0.0, max_answer: int = 30,
    batch_size: int = 32, max_length: int = 384, stride: int = 128,
) -> list[str]:
    """Each example's answer ("" for none)."""
    best: list[tuple[float, str]] = [(float("-inf"), "")] * len(examples)
    null: list[float] = [float("-inf")] * len(examples)
    for begin in range(0, len(examples), batch_size):
        batch = examples[begin : begin + batch_size]
        encoded = tokenizer(
            [example.question for example in batch],
            [example.context for example in batch],
            truncation="only_second",
            max_length=max_length,
            stride=stride,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            return_token_type_ids=False,
            padding=True,
            return_tensors="pt",
        )
        offsets = encoded.pop("offset_mapping").tolist()
        owners = encoded.pop("overflow_to_sample_mapping").tolist()
        with torch.no_grad():
            output = model(**{key: value.to(device) for key, value in encoded.items()})
        starts, ends = output.start_logits.float().cpu(), output.end_logits.float().cpu()
        for window, owner in enumerate(owners):
            index = begin + owner
            example = examples[index]
            sequence_ids = encoded.sequence_ids(window)
            null[index] = max(null[index], float(starts[window, 0] + ends[window, 0]))
            context = [i for i, sequence in enumerate(sequence_ids) if sequence == 1]
            top_starts = sorted(context, key=lambda i: float(starts[window, i]), reverse=True)[:20]
            top_ends = sorted(context, key=lambda i: float(ends[window, i]), reverse=True)[:20]
            for start in top_starts:
                for end in top_ends:
                    if end < start or end - start + 1 > max_answer:
                        continue
                    score = float(starts[window, start] + ends[window, end])
                    if score > best[index][0]:
                        text = example.context[offsets[window][start][0] : offsets[window][end][1]].strip()
                        best[index] = (score, text)
    return [text if score > null_score + null_margin else "" for (score, text), null_score in zip(best, null, strict=True)]


def _normalize(text: str) -> str:
    return _NOT_WORD.sub("", text.lower())


def _f1(prediction: str, gold: str) -> float:
    prediction, gold = _normalize(prediction), _normalize(gold)
    if not prediction or not gold:
        return float(prediction == gold)
    common = sum((Counter(prediction) & Counter(gold)).values())
    if not common:
        return 0.0
    precision, recall = common / len(prediction), common / len(gold)
    return 2 * precision * recall / (precision + recall)


def scores(examples: list[Example], answers: list[str]) -> tuple[dict[str, float], list]:
    exact = f1 = right_null = 0.0
    errors = []
    for example, answer in zip(examples, answers, strict=True):
        golds = [gold.text for gold in example.answers] or [""]
        example_exact = max(float(_normalize(answer) == _normalize(gold)) for gold in golds)
        exact += example_exact
        f1 += max(_f1(answer, gold) for gold in golds)
        right_null += float(bool(answer) == bool(example.answers))
        if not example_exact:
            errors.append((example.context, example.question, golds[0], answer))
    count = len(examples)
    return {"exact": exact / count, "f1": f1 / count, "null_accuracy": right_null / count}, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", nargs="+", required=True)
    parser.add_argument("--null-margin", type=float, default=0.0)
    parser.add_argument("--errors", action="store_true")
    parser.add_argument("--latency", action="store_true")
    parser.add_argument("--skip-klue", action="store_true", help="only the novel set")
    args = parser.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    novel = load("novel")

    for name in args.model:
        tokenizer = AutoTokenizer.from_pretrained(name)
        model = AutoModelForQuestionAnswering.from_pretrained(name).to(device).eval()
        print(f"== {name} (null margin {args.null_margin})")
        if not args.skip_klue:
            dev = load("klue-dev")
            result, _ = scores(dev, predict(model, tokenizer, dev, device, null_margin=args.null_margin))
            print("KLUE-MRC dev: " + " ".join(f"{key} {value:.3f}" for key, value in result.items()))
        result, errors = scores(novel, predict(model, tokenizer, novel, device, null_margin=args.null_margin))
        print("novel       : " + " ".join(f"{key} {value:.3f}" for key, value in result.items()))
        if args.errors:
            for context, question, gold, answer in errors:
                print(f"  {context} / {question}\n    gold {gold!r} got {answer!r}")
        if args.latency:
            model = model.to("cpu")
            begin = time.perf_counter()
            for example in novel:
                predict(model, tokenizer, [example], "cpu", null_margin=args.null_margin)
            print(f"CPU latency: {1000 * (time.perf_counter() - begin) / len(novel):.1f} ms per question")


if __name__ == "__main__":
    main()
