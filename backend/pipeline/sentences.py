"""Splits a manuscript into sentences and marks the dialogue in them (design
doc 7.1.1, step 1).

A sentence ends at ., !, ? or … outside quotes, or at a line break. Quotes
don't end it: `"세린, 기다려." 레온이 낮게 말했다.` is one sentence, so what is
said and who says it stay together. Each sentence carries its narration — the
text with whatever is inside quotes blanked out, the same length as the text —
because what a character says ("눈이 참 푸르구나") isn't the narrator stating a
fact about a card, and a name in a line of dialogue isn't who the narration is
about.
"""

from dataclasses import dataclass

# Opening quote -> closing quote. A straight " opens and closes itself.
_QUOTES = {'"': '"', "“": "”", "‘": "’", "「": "」", "『": "』"}
_TERMINALS = ".!?…"
# After a sentence's last terminal, closers that belong to it.
_TRAILING_CLOSERS = ")]}»”’」』"
# Longest a sentence goes on for the models (they read about 250 tokens);
# a longer one is cut at its last comma or space before this.
MAX_SENTENCE_CHARS = 250


@dataclass(frozen=True)
class Sentence:
    index: int
    text: str  # as written
    narration: str  # text with the quoted parts blanked out, same length

    @property
    def has_narration(self) -> bool:
        return bool(self.narration.strip())


def _end_of_run(text: str, start: int) -> int:
    # start is at a terminal; the run of terminals and closers after it.
    end = start
    while end < len(text) and (text[end] in _TERMINALS or text[end] in _TRAILING_CLOSERS):
        end += 1
    return end


def _cut_long(text: str) -> list[tuple[int, int]]:
    # Spans (start, end) of text, none longer than MAX_SENTENCE_CHARS where a
    # comma or space allows it.
    spans = []
    start = 0
    while len(text) - start > MAX_SENTENCE_CHARS:
        window = text[start : start + MAX_SENTENCE_CHARS]
        cut = max(window.rfind(","), window.rfind("，"))
        cut = cut + 1 if cut > 0 else window.rfind(" ")
        if cut <= 0:
            cut = MAX_SENTENCE_CHARS
        spans.append((start, start + cut))
        start += cut
    spans.append((start, len(text)))
    return spans


def _split_line(paragraph: str) -> list[tuple[int, int]]:
    spans = []
    start = 0
    closer: str | None = None
    position = 0
    while position < len(paragraph):
        char = paragraph[position]
        if closer is not None:
            if char == closer:
                closer = None
            position += 1
            continue
        if char in _QUOTES:
            closer = _QUOTES[char]
            position += 1
            continue
        if char in _TERMINALS:
            end = _end_of_run(paragraph, position)
            # A boundary only where the text goes on after a space or ends:
            # not the dot of "1.5" or "a.b".
            if end >= len(paragraph) or paragraph[end].isspace() or paragraph[end] in _QUOTES:
                spans.append((start, end))
                start = end
            position = end
            continue
        position += 1
    if start < len(paragraph):
        spans.append((start, len(paragraph)))
    return spans


def _blank_quotes(text: str) -> str:
    out = []
    closer: str | None = None
    for char in text:
        if closer is not None:
            out.append(" ")
            if char == closer:
                closer = None
        elif char in _QUOTES:
            closer = _QUOTES[char]
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


def split_sentences(manuscript: str) -> list[Sentence]:
    sentences: list[Sentence] = []
    for line in manuscript.splitlines():
        if not line.strip():
            continue
        for start, end in _split_line(line):
            piece = line[start:end]
            for cut_start, cut_end in _cut_long(piece):
                raw = piece[cut_start:cut_end]
                text = raw.strip()
                if not text:
                    continue
                sentences.append(
                    Sentence(
                        index=len(sentences),
                        text=text,
                        narration=_blank_quotes(text),
                    )
                )
    return sentences
