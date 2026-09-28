"""Reads KLUE-MRC (as download.py fetched it) and the novel evaluation set,
as (context, question, answers) examples.

An example with no answers is a question the context doesn't answer — what
most (sentence, attribute) pairs the extractor asks about are.

The novel set (eval/novel.jsonl, ours) asks what the backend will ask: the
value of one setting-card attribute ("레온의 눈 색깔은?") from a sentence or
two of novel prose; "" for a sentence that doesn't state it.
"""

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
EVAL_DIR = Path(__file__).parent / "eval"


@dataclass(frozen=True)
class Answer:
    text: str
    start: int  # character offset into the context


@dataclass(frozen=True)
class Example:
    context: str
    question: str
    answers: tuple[Answer, ...]  # empty: unanswerable


def _klue(name: str) -> list[Example]:
    with (DATA_DIR / name).open(encoding="utf-8") as file:
        data = json.load(file)["data"]
    examples = []
    for article in data:
        for paragraph in article["paragraphs"]:
            for qa in paragraph["qas"]:
                answers = () if qa.get("is_impossible") else tuple(
                    Answer(answer["text"], answer["answer_start"]) for answer in qa["answers"]
                )
                examples.append(Example(paragraph["context"], qa["question"], answers))
    return examples


def _novel() -> list[Example]:
    examples = []
    with (EVAL_DIR / "novel.jsonl").open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            item = json.loads(line)
            answer = item["answer"]
            answers = (Answer(answer, item["context"].index(answer)),) if answer else ()
            examples.append(Example(item["context"], item["question"], answers))
    return examples


DATASETS = {
    "klue": lambda: _klue("klue-mrc-v1.1_train.json"),  # 17,554 questions
    "klue-dev": lambda: _klue("klue-mrc-v1.1_dev.json"),  # 5,841: the evaluation set
    "novel": _novel,  # ours: attribute questions on novel prose
}


def load(name: str) -> list[Example]:
    return DATASETS[name]()
