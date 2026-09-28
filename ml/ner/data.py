"""Reads KLUE-NER (as download.py fetched it) and the novel evaluation set.

KLUE-NER tags each character (BIO over PS, LC, OG, DT, TI, QT). A sentence
comes out as its text plus its entities as character spans, which is what
training (tokens labelled from the characters they cover) and evaluation
(entity spans compared as a whole) both work from.

The novel set (eval/novel.jsonl, ours) lists each sentence's entities by
surface form ("레온", "PS"); that's how it's compared too, as a set per
sentence, since the backend only needs which names a sentence holds.
"""

import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
EVAL_DIR = Path(__file__).parent / "eval"

TYPES = ("PS", "LC", "OG", "DT", "TI", "QT")
# Output index -> label. Saved into the model's config (id2label), which the
# backend reads by name.
LABELS = ("O", *(f"{prefix}-{kind}" for kind in TYPES for prefix in ("B", "I")))
LABEL_IDS = {label: index for index, label in enumerate(LABELS)}


@dataclass(frozen=True)
class Entity:
    start: int  # character offsets into the sentence, end exclusive
    end: int
    kind: str


@dataclass(frozen=True)
class Sentence:
    text: str
    entities: tuple[Entity, ...]

    def surfaces(self) -> set[tuple[str, str]]:
        return {(self.text[entity.start : entity.end], entity.kind) for entity in self.entities}


def _spans(tags: list[str]) -> tuple[Entity, ...]:
    entities = []
    start = kind = None
    for index, tag in enumerate([*tags, "O"]):
        prefix, _, tag_kind = tag.partition("-")
        # An I- that doesn't continue the open entity starts a new one.
        if kind is not None and not (prefix == "I" and tag_kind == kind):
            entities.append(Entity(start, index, kind))
            start = kind = None
        if prefix in ("B", "I") and kind is None:
            start, kind = index, tag_kind
    return tuple(entities)


def _klue(name: str) -> list[Sentence]:
    sentences = []
    chars: list[str] = []
    tags: list[str] = []

    def flush() -> None:
        if chars:
            sentences.append(Sentence("".join(chars), _spans(tags)))
        chars.clear()
        tags.clear()

    with (DATA_DIR / name).open(encoding="utf-8") as file:
        for line in file:
            line = line.rstrip("\n")
            if line.startswith("##"):
                continue
            if not line:
                flush()
                continue
            # The character can be a space: split once, from the right.
            char, _, tag = line.rpartition("\t")
            chars.append(char)
            tags.append(tag)
    flush()
    return sentences


def _novel() -> list[Sentence]:
    sentences = []
    with (EVAL_DIR / "novel.jsonl").open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            item = json.loads(line)
            text = item["text"]
            entities = []
            for surface, kind in item["entities"]:
                start = text.index(surface)
                entities.append(Entity(start, start + len(surface), kind))
            sentences.append(Sentence(text, tuple(entities)))
    return sentences


DATASETS = {
    "klue": lambda: _klue("klue-ner-v1.1_train.tsv"),  # 21,008 sentences
    "klue-dev": lambda: _klue("klue-ner-v1.1_dev.tsv"),  # 5,000: the evaluation set
    "novel": _novel,  # ours: novel prose
}


def load(name: str) -> list[Sentence]:
    return DATASETS[name]()
