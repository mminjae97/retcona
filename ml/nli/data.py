"""Reads the NLI datasets download.py fetched, as (premise, hypothesis, label) examples.

Labels are the three NLI classes, in the order the model's outputs use
(LABELS). The novel evaluation set (eval/novel.jsonl) is read the same way.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
EVAL_DIR = Path(__file__).parent / "eval"

# Output index -> label. Saved into the model's config (id2label), which the
# backend reads (backend/infra/inference_client.py matches the names, not the order).
LABELS = ("entailment", "neutral", "contradiction")
LABEL_IDS = {label: index for index, label in enumerate(LABELS)}


@dataclass(frozen=True)
class Example:
    premise: str
    hypothesis: str
    label: int


def _kornli(name: str) -> list[Example]:
    with (DATA_DIR / name).open(encoding="utf-8", newline="") as file:
        # QUOTE_NONE: sentences contain bare quotation marks.
        rows = csv.DictReader(file, delimiter="\t", quoting=csv.QUOTE_NONE)
        return [
            Example(row["sentence1"], row["sentence2"], LABEL_IDS[row["gold_label"]])
            for row in rows
            if row["gold_label"] in LABEL_IDS
        ]


def _klue(name: str) -> list[Example]:
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        return [
            Example(item["premise"], item["hypothesis"], LABEL_IDS[item["gold_label"]])
            for item in json.load(file)
            if item["gold_label"] in LABEL_IDS
        ]


def _jsonl(path: Path) -> list[Example]:
    with path.open(encoding="utf-8") as file:
        items = [json.loads(line) for line in file if line.strip()]
    return [Example(item["premise"], item["hypothesis"], LABEL_IDS[item["label"]]) for item in items]


DATASETS = {
    # KorNLI train: SNLI + MNLI, machine-translated (942,854 pairs)
    "kornli": lambda: _kornli("snli_1.0_train.ko.tsv") + _kornli("multinli.train.ko.tsv"),
    # KLUE-NLI train, written in Korean (24,998 pairs)
    "klue": lambda: _klue("klue-nli-v1.1_train.json"),
    # KLUE-NLI dev: the evaluation set (3,000 pairs)
    "klue-dev": lambda: _klue("klue-nli-v1.1_dev.json"),
    # Our own: setting-card premise vs. novel prose (eval/novel.jsonl)
    "novel": lambda: _jsonl(EVAL_DIR / "novel.jsonl"),
}


def load(name: str) -> list[Example]:
    return DATASETS[name]()
