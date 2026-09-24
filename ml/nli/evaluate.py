"""Compares NLI models on KLUE-NLI dev and the novel evaluation set.

    python evaluate.py --model runs/mixed Huffon/klue-roberta-base-nli --data klue-dev novel

For each model and dataset: accuracy, per-label precision/recall/F1, and how
the backend would do with it — a pair is flagged when its contradiction
probability is 0.5 or more (backend/pipeline/judges.py), so flag precision
and recall are about the contradiction label alone. --errors lists the novel
set's misjudged pairs; --latency times CPU inference the way the worker runs
it (batches of 16).
"""

import argparse
import time

import torch
from sklearn.metrics import classification_report, confusion_matrix
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from data import LABEL_IDS, LABELS, Example, load

CONTRADICTION = LABEL_IDS["contradiction"]
FLAG_THRESHOLD = 0.5
BATCH_SIZE = 16
MAX_LENGTH = 256


class Model:
    def __init__(self, name: str, device: str) -> None:
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name).eval().to(device)
        self.device = device
        # This model's output index of each of our labels, by name.
        by_name = {label.lower(): int(index) for index, label in self.model.config.id2label.items()}
        self.order = [by_name[label] for label in LABELS]
        # RoBERTa-style models have a single token type (see train.py).
        self.token_types = getattr(self.model.config, "type_vocab_size", 1) > 1

    def probabilities(self, examples: list[Example]) -> torch.Tensor:
        """Rows of (entailment, neutral, contradiction) probabilities."""
        rows = []
        for start in range(0, len(examples), BATCH_SIZE):
            batch = examples[start : start + BATCH_SIZE]
            encoded = self.tokenizer(
                [example.premise for example in batch],
                [example.hypothesis for example in batch],
                padding=True,
                truncation=True,
                max_length=MAX_LENGTH,
                return_tensors="pt",
                return_token_type_ids=self.token_types,
            ).to(self.device)
            with torch.no_grad():
                rows.append(self.model(**encoded).logits.softmax(dim=-1)[:, self.order].cpu())
        return torch.cat(rows)


def _report(model: Model, name: str, examples: list[Example], errors: bool) -> None:
    probs = model.probabilities(examples)
    gold = [example.label for example in examples]
    predicted = probs.argmax(dim=-1).tolist()
    flagged = (probs[:, CONTRADICTION] >= FLAG_THRESHOLD).tolist()
    is_contradiction = [label == CONTRADICTION for label in gold]

    true_flags = sum(f and c for f, c in zip(flagged, is_contradiction))
    flag_precision = true_flags / max(sum(flagged), 1)
    flag_recall = true_flags / max(sum(is_contradiction), 1)
    accuracy = sum(p == g for p, g in zip(predicted, gold)) / len(gold)
    print(f"\n## {name} ({len(examples)} pairs)  accuracy {accuracy:.3f}  "
          f"flag precision {flag_precision:.3f}  flag recall {flag_recall:.3f}")
    print(classification_report(gold, predicted, labels=range(len(LABELS)), target_names=LABELS, digits=3, zero_division=0))
    print("confusion (rows: gold, columns: predicted)", LABELS)
    print(confusion_matrix(gold, predicted, labels=range(len(LABELS))))
    if errors:
        for example, row, pred in zip(examples, probs.tolist(), predicted):
            if pred != example.label:
                print(f"  gold={LABELS[example.label]:<13} pred={LABELS[pred]:<13} "
                      f"cont={row[CONTRADICTION]:.2f} | {example.premise} || {example.hypothesis}")


def _latency(name: str, examples: list[Example]) -> None:
    model = Model(name, "cpu")
    sample = (examples * (64 // len(examples) + 1))[:64]
    model.probabilities(sample[:BATCH_SIZE])  # warm-up
    start = time.perf_counter()
    model.probabilities(sample)
    elapsed = time.perf_counter() - start
    print(f"\nCPU latency: {elapsed / len(sample) * 1000:.1f} ms per pair ({torch.get_num_threads()} threads)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", nargs="+", required=True, help="Hugging Face ids or local directories")
    parser.add_argument("--data", nargs="+", default=["klue-dev", "novel"], choices=["klue-dev", "novel"])
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--errors", action="store_true", help="list the novel set's misjudged pairs")
    parser.add_argument("--latency", action="store_true", help="also time CPU inference")
    args = parser.parse_args()

    datasets = {name: load(name) for name in args.data}
    for name in args.model:
        print(f"\n# {name}")
        model = Model(name, args.device)
        for data_name, examples in datasets.items():
            _report(model, data_name, examples, errors=args.errors and data_name == "novel")
        if args.latency:
            _latency(name, datasets.get("novel") or next(iter(datasets.values())))


if __name__ == "__main__":
    main()
