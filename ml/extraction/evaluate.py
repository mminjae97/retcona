"""Evaluates the claim extractor on novel passages.

    python evaluate.py [--errors] [--tag pronoun] [--json runs/baseline.json]

Runs backend/pipeline/extract_claims.py — sentence splitting, names, cues, the
NER and QA models, pronoun rules — on each passage of eval/passages.jsonl with
the passage's cast registered, and compares what it extracts with what the
passage says.

A passage (one JSON object per line):
- cast: a key of casts.json (the registered characters and locations);
  characters have a unique label, which gold and predictions are compared by
  (two characters called 김철수 are told apart by it)
- text: the manuscript
- tags: kinds of case the passage tests; the scores are also broken down by them
- gold: what the passage says about a registered or new subject, one item per
  subject and attribute: {"subject", "kind": character|location, "attribute",
  "values": [surface forms that count as right]}; "mutable": true marks an
  attribute the extractor doesn't extract yet (hairstyle, outfit, ...)
- pending: what the extractor should leave for the author to pick, because
  the text doesn't say which of several characters: {"candidates": [labels],
  "attribute", "values"}
Anything extracted that isn't in gold or pending is a false positive — a
sentence about someone else's eyes, a line of dialogue, an idiom.

An item counts as right when its subject (or, for a pending claim, its
candidates), attribute and value all match. "Attribute and value only" is
reported too, to tell a wrong subject from a wrong or missing value.
"""

import argparse
import json
import re
import sys
import time
import unicodedata
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from pipeline.extract_claims import extract_claims  # noqa: E402

PENDING = "?"
_NOT_WORD = re.compile(r"[\W_]+")


def normalize(text: str) -> str:
    return _NOT_WORD.sub("", unicodedata.normalize("NFC", text).lower())


@dataclass(frozen=True)
class Item:
    subject: str  # a label, a new subject's name, or PENDING
    kind: str  # character | location
    attribute: str
    value: str  # a predicted value, or the first accepted form of a gold one
    values: tuple[str, ...] = ()  # gold: every accepted form
    candidates: tuple[str, ...] = ()  # pending: the labels it could be
    sentence: str = ""
    mutable: bool = False


@dataclass
class Counts:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    def add(self, other: "Counts") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn

    def scores(self) -> tuple[float | None, float | None, float | None]:
        """None where there is nothing to divide by: no claim (precision), no gold (recall),
        neither (F1). A tag that misses all its gold has an F1 of 0, not None."""
        precision = self.tp / (self.tp + self.fp) if self.tp + self.fp else None
        recall = self.tp / (self.tp + self.fn) if self.tp + self.fn else None
        total = 2 * self.tp + self.fp + self.fn
        f1 = 2 * self.tp / total if total else None
        return precision, recall, f1


@dataclass
class Result:
    strict: Counts = field(default_factory=Counts)
    relaxed: Counts = field(default_factory=Counts)
    by_attribute: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    by_tag: dict[str, Counts] = field(default_factory=lambda: defaultdict(Counts))
    errors: list[str] = field(default_factory=list)


def value_matches(predicted: str, accepted: tuple[str, ...]) -> bool:
    got = normalize(predicted)
    if not got:
        return False
    return any(form and (normalize(form) in got or got in normalize(form)) for form in accepted)


def gold_items(passage: dict) -> list[Item]:
    items = [
        Item(
            g["subject"], g.get("kind", "character"), g["attribute"], g["values"][0], tuple(g["values"]),
            sentence=g.get("sentence", ""), mutable=g.get("mutable", False),
        )
        for g in passage.get("gold", [])
    ]  # fmt: skip
    items += [
        Item(
            PENDING, "character", p["attribute"], p["values"][0], tuple(p["values"]),
            candidates=tuple(sorted(p["candidates"])), sentence=p.get("sentence", ""),
        )
        for p in passage.get("pending", [])
    ]  # fmt: skip
    return items


def predicted_items(cast: dict, extraction) -> list[Item]:
    labels = {f"c{i}": c["label"] for i, c in enumerate(cast["characters"], start=1)}
    items = []
    for claim in extraction.claims:
        pending = bool(claim.candidates)
        subject = PENDING if pending else labels.get(claim.subject_ref or "", claim.subject)
        candidates = tuple(sorted(labels[ref] for ref in claim.candidates)) if pending else ()
        for attribute, value in claim.attributes.items():
            items.append(
                Item(subject, claim.subject_kind, attribute, value, candidates=candidates, sentence=claim.evidence or "")
            )
    return items


def same_subject(predicted: Item, gold: Item) -> bool:
    if predicted.subject == PENDING or gold.subject == PENDING:
        return predicted.subject == gold.subject and predicted.candidates == gold.candidates
    return normalize(predicted.subject) == normalize(gold.subject)


def compare(predicted: list[Item], gold: list[Item], strict: bool) -> tuple[list[tuple[Item, Item]], list[Item], list[Item]]:
    """(matched pairs, false positives, misses). Each gold item matches one prediction."""
    open_gold = list(gold)
    matched, extra = [], []
    for item in predicted:
        for candidate in open_gold:
            if (
                candidate.kind == item.kind
                and candidate.attribute == item.attribute
                and value_matches(item.value, candidate.values)
                and (not strict or same_subject(item, candidate))
            ):
                open_gold.remove(candidate)
                matched.append((item, candidate))
                break
        else:
            extra.append(item)
    return matched, extra, open_gold


def evaluate(passages: list[dict], casts: dict, tag: str | None) -> Result:
    result = Result()
    for passage in passages:
        if tag and tag not in passage.get("tags", []):
            continue
        cast = casts[passage["cast"]]
        characters = [
            {"ref": f"c{i}", "name": c["name"], "aliases": c["aliases"], "gender": c["gender"], "pronoun": c["pronoun"]}
            for i, c in enumerate(cast["characters"], start=1)
        ]
        extraction = extract_claims(uuid.uuid4(), passage["text"], characters, cast["locations"])
        predicted, gold = predicted_items(cast, extraction), gold_items(passage)
        # Attributes the extractor doesn't extract yet are scored as misses,
        # reported on their own below, not mixed into the main score.
        main_gold = [g for g in gold if not g.mutable]
        for strict, counts in ((True, result.strict), (False, result.relaxed)):
            matched, extra, missed = compare(predicted, main_gold, strict)
            counts.add(Counts(len(matched), len(extra), len(missed)))
            if strict:
                for group in [result.by_tag[t] for t in passage.get("tags", [])]:
                    group.add(Counts(len(matched), len(extra), len(missed)))
                for item, _ in matched:
                    result.by_attribute[item.attribute].tp += 1
                for item in extra:
                    result.by_attribute[item.attribute].fp += 1
                for item in missed:
                    result.by_attribute[item.attribute].fn += 1
                for item in extra:
                    result.errors.append(f"[{passage['id']}] extra   {describe(item)}")
                for item in missed:
                    result.errors.append(f"[{passage['id']}] missed  {describe(item)}")
        for item in (g for g in gold if g.mutable):
            result.by_attribute[item.attribute].fn += 1
            result.by_tag["mutable"].fn += 1
    return result


def describe(item: Item) -> str:
    who = f"? {list(item.candidates)}" if item.subject == PENDING else item.subject
    value = item.values[0] if item.values else item.value
    return f"{who} · {item.attribute} = {value!r}" + (f"   ← {item.sentence}" if item.sentence else "")


def row(name: str, counts: Counts) -> str:
    # "-" where there is nothing to divide by: precision with no claim, recall with no gold.
    precision, recall, f1 = (f"{x:.3f}" if x is not None else "-" for x in counts.scores())
    return f"| {name} | {counts.tp} | {counts.fp} | {counts.fn} | {precision} | {recall} | {f1} |"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--errors", action="store_true", help="list every extra and missed item")
    parser.add_argument("--tag", help="only the passages with this tag")
    parser.add_argument("--json", type=Path, help="write the scores here")
    args = parser.parse_args()

    casts = json.loads((HERE / "casts.json").read_text(encoding="utf-8"))
    with (HERE / "eval" / "passages.jsonl").open(encoding="utf-8") as file:
        passages = [json.loads(line) for line in file if line.strip()]

    started = time.time()
    result = evaluate(passages, casts, args.tag)
    seconds = time.time() - started
    selected = [p for p in passages if not args.tag or args.tag in p.get("tags", [])]
    sentences = sum(p["text"].count("\n") + 1 for p in selected)
    print(f"{len(selected)} passages ({sentences} lines of text) in {seconds:.1f} s\n")

    header = "| | right | extra | missed | precision | recall | F1 |\n|---|---|---|---|---|---|---|"
    print("Subject, attribute and value all right\n\n" + header)
    print(row("all", result.strict))
    print("\nAttribute and value only (a right value for the wrong subject counts)\n\n" + header)
    print(row("all", result.relaxed))
    print("\nBy attribute (strict; \"missed\" includes the ones not extracted yet)\n\n" + header)
    for attribute in sorted(result.by_attribute):
        print(row(attribute, result.by_attribute[attribute]))
    print("\nBy kind of case (strict)\n\n" + header)
    for name in sorted(result.by_tag):
        print(row(name, result.by_tag[name]))
    if args.errors:
        print("\nErrors\n")
        print("\n".join(result.errors))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        summary = {
            "strict": vars(result.strict),
            "relaxed": vars(result.relaxed),
            "by_attribute": {k: vars(v) for k, v in result.by_attribute.items()},
            "by_tag": {k: vars(v) for k, v in result.by_tag.items()},
        }
        args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
