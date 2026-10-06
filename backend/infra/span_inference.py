"""Runs the two span models of claim extraction (design doc 7.1.1): the NER
model (ml/ner) and the extractive QA model (ml/qa).

The decoding here is the one those directories evaluate with (their
evaluate.py), so the numbers in their RESULTS.md describe what runs here.
Torch and transformers are imported where used: the API server never loads
the models.
"""

from dataclasses import dataclass

NER_MAX_TOKENS = 256
QA_MAX_TOKENS = 384
QA_STRIDE = 128
# Longest answer, in tokens; a value is a short phrase.
QA_MAX_ANSWER_TOKENS = 30
# Candidate start and end positions kept per window before pairing them up.
_QA_TOP_POSITIONS = 20
# Sentences or questions per forward pass: bounds memory on a long episode.
_BATCH_SIZE = 32


@dataclass(frozen=True)
class NamedEntity:
    start: int  # character offsets into the text, end exclusive
    end: int
    kind: str  # PS person, LC location, OG organization, DT date, TI time, QT quantity

    def surface(self, text: str) -> str:
        return text[self.start : self.end]


def decode_entities(text: str, offsets: list[list[int]], labels: list[str]) -> list[NamedEntity]:
    """Token labels back to character spans: B- opens an entity, I- of the
    same type continues it (a stray I- opens one too)."""
    entities: list[NamedEntity] = []
    # The entity being read: [start, end, kind].
    current: list | None = None
    for (start, end), label in zip(offsets, labels, strict=True):
        if start == end:  # a special token
            continue
        prefix, _, kind = label.partition("-")
        if current is not None and prefix == "I" and kind == current[2]:
            current[1] = end
            continue
        if current is not None:
            entities.append(NamedEntity(*current))
            current = None
        if prefix in ("B", "I"):
            # Offsets can include a leading space.
            while start < end and text[start].isspace():
                start += 1
            current = [start, end, kind]
    if current is not None:
        entities.append(NamedEntity(*current))
    return entities


def recognize(model, tokenizer, texts: list[str]) -> list[list[NamedEntity]]:
    import torch

    results: list[list[NamedEntity]] = []
    for begin in range(0, len(texts), _BATCH_SIZE):
        batch = texts[begin : begin + _BATCH_SIZE]
        encoded = tokenizer(
            batch,
            truncation=True,
            max_length=NER_MAX_TOKENS,
            padding=True,
            return_offsets_mapping=True,
            return_token_type_ids=False,
            return_tensors="pt",
        )
        offsets = encoded.pop("offset_mapping").tolist()
        with torch.no_grad():
            predicted = model(**encoded).logits.argmax(-1).tolist()
        for text, token_offsets, row in zip(batch, offsets, predicted, strict=True):
            results.append(decode_entities(text, token_offsets, [model.config.id2label[label] for label in row]))
    return results


def answer(model, tokenizer, questions: list[tuple[str, str]], null_margin: float) -> list[str]:
    """The answer to each (question, context), "" for none.

    The best span (start + end logits) unless "no answer" scores higher by
    more than null_margin: raising it answers less often, a negative one more
    often. A context longer than the model takes is read in overlapping windows.
    """
    import torch

    best: list[tuple[float, str]] = [(float("-inf"), "")] * len(questions)
    null: list[float] = [float("-inf")] * len(questions)
    for begin in range(0, len(questions), _BATCH_SIZE):
        batch = questions[begin : begin + _BATCH_SIZE]
        encoded = tokenizer(
            [question for question, _ in batch],
            [context for _, context in batch],
            truncation="only_second",
            max_length=QA_MAX_TOKENS,
            stride=QA_STRIDE,
            return_overflowing_tokens=True,
            return_offsets_mapping=True,
            return_token_type_ids=False,
            padding=True,
            return_tensors="pt",
        )
        offsets = encoded.pop("offset_mapping").tolist()
        owners = encoded.pop("overflow_to_sample_mapping").tolist()
        with torch.no_grad():
            output = model(**encoded)
        starts, ends = output.start_logits.float(), output.end_logits.float()
        for window, owner in enumerate(owners):
            index = begin + owner
            context = batch[owner][1]
            null[index] = max(null[index], float(starts[window, 0] + ends[window, 0]))
            positions = [i for i, sequence in enumerate(encoded.sequence_ids(window)) if sequence == 1]
            top_starts = sorted(positions, key=lambda i: float(starts[window, i]), reverse=True)[:_QA_TOP_POSITIONS]
            top_ends = sorted(positions, key=lambda i: float(ends[window, i]), reverse=True)[:_QA_TOP_POSITIONS]
            for start in top_starts:
                for end in top_ends:
                    if end < start or end - start + 1 > QA_MAX_ANSWER_TOKENS:
                        continue
                    score = float(starts[window, start] + ends[window, end])
                    if score > best[index][0]:
                        best[index] = (score, context[offsets[window][start][0] : offsets[window][end][1]].strip())
    return [text if score > null_score + null_margin else "" for (score, text), null_score in zip(best, null, strict=True)]
