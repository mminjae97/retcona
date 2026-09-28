"""Evaluates NER models on KLUE-NER dev and the novel set.

    python evaluate.py --model runs/klue [--errors] [--latency]

- KLUE-NER dev: entity-level precision / recall / F1 (span and type exact),
  overall and for PS and LC — the two the extractor uses.
- Novel set (eval/novel.jsonl): PS and LC names per sentence, compared as
  (surface, type) sets — what the extractor needs from a sentence.
--errors lists the novel sentences the model got wrong; --latency times one
sentence at a time on the CPU, as the backend's worker would run it.
"""

import argparse
import time

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

from data import Entity, Sentence, load

USED = ("PS", "LC")


def predict(model, tokenizer, texts: list[str], device: str, batch_size: int = 64) -> list[tuple[Entity, ...]]:
    results = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        encoded = tokenizer(
            batch,
            truncation=True,
            max_length=256,
            padding=True,
            return_offsets_mapping=True,
            return_token_type_ids=False,
            return_tensors="pt",
        )
        offsets = encoded.pop("offset_mapping").tolist()
        with torch.no_grad():
            logits = model(**{key: value.to(device) for key, value in encoded.items()}).logits
        for text, token_offsets, row in zip(batch, offsets, logits.argmax(-1).tolist(), strict=True):
            results.append(decode(text, token_offsets, [model.config.id2label[label] for label in row]))
    return results


def decode(text: str, offsets: list[list[int]], labels: list[str]) -> tuple[Entity, ...]:
    """Token labels back to character spans: B- opens an entity, I- of the
    same type continues it (a stray I- opens one too)."""
    entities = []
    open_start = open_end = open_kind = None
    for (start, end), label in zip(offsets, labels, strict=True):
        if start == end:
            continue
        prefix, _, kind = label.partition("-")
        if open_kind is not None and prefix == "I" and kind == open_kind:
            open_end = end
            continue
        if open_kind is not None:
            entities.append(Entity(open_start, open_end, open_kind))
            open_start = open_end = open_kind = None
        if prefix in ("B", "I"):
            # Offsets can include a leading space.
            while start < end and text[start].isspace():
                start += 1
            open_start, open_end, open_kind = start, end, kind
    if open_kind is not None:
        entities.append(Entity(open_start, open_end, open_kind))
    return tuple(entities)


def _prf(true: int, predicted: int, correct: int) -> tuple[float, float, float]:
    precision = correct / predicted if predicted else 0.0
    recall = correct / true if true else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def klue_scores(sentences: list[Sentence], predictions: list[tuple[Entity, ...]]) -> dict[str, tuple[float, float, float]]:
    scores = {}
    for kinds, name in ((None, "all"), (("PS",), "PS"), (("LC",), "LC")):
        true = predicted = correct = 0
        for sentence, entities in zip(sentences, predictions, strict=True):
            gold = {entity for entity in sentence.entities if kinds is None or entity.kind in kinds}
            guess = {entity for entity in entities if kinds is None or entity.kind in kinds}
            true, predicted, correct = true + len(gold), predicted + len(guess), correct + len(gold & guess)
        scores[name] = _prf(true, predicted, correct)
    return scores


def novel_scores(sentences: list[Sentence], predictions: list[tuple[Entity, ...]]) -> tuple[tuple[float, float, float], list]:
    true = predicted = correct = 0
    errors = []
    for sentence, entities in zip(sentences, predictions, strict=True):
        gold = {item for item in sentence.surfaces() if item[1] in USED}
        guess = {(sentence.text[e.start : e.end], e.kind) for e in entities if e.kind in USED}
        true, predicted, correct = true + len(gold), predicted + len(guess), correct + len(gold & guess)
        if gold != guess:
            errors.append((sentence.text, sorted(gold - guess), sorted(guess - gold)))
    return _prf(true, predicted, correct), errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", nargs="+", required=True)
    parser.add_argument("--errors", action="store_true")
    parser.add_argument("--latency", action="store_true")
    args = parser.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    dev, novel = load("klue-dev"), load("novel")

    for name in args.model:
        tokenizer = AutoTokenizer.from_pretrained(name)
        model = AutoModelForTokenClassification.from_pretrained(name).to(device).eval()
        print(f"== {name}")
        for kind, (p, r, f) in klue_scores(dev, predict(model, tokenizer, [s.text for s in dev], device)).items():
            print(f"KLUE-NER dev {kind:>3}: P {p:.3f} R {r:.3f} F1 {f:.3f}")
        (p, r, f), errors = novel_scores(novel, predict(model, tokenizer, [s.text for s in novel], device))
        print(f"novel PS/LC     : P {p:.3f} R {r:.3f} F1 {f:.3f} ({len(novel) - len(errors)}/{len(novel)} sentences exact)")
        if args.errors:
            for text, missed, extra in errors:
                print(f"  {text}\n    missed {missed} extra {extra}")
        if args.latency:
            model = model.to("cpu")
            texts = [s.text for s in novel]
            begin = time.perf_counter()
            for text in texts:
                predict(model, tokenizer, [text], "cpu")
            print(f"CPU latency: {1000 * (time.perf_counter() - begin) / len(texts):.1f} ms per sentence")


if __name__ == "__main__":
    main()
