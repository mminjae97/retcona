# Claim extraction results

How the extractor (`backend/pipeline/extract_claims.py`) does on the novel passages of `eval/passages.jsonl`, and what each change to it did. Every change is measured here, so the effect of a rule is on record. Data and scoring: [README.md](README.md).

## Setup common to all rounds

| | |
|---|---|
| Machine | CPU, 6 threads (about 13 s for the 45 passages, models loaded) |
| Models | NER `ml/ner/runs/klue`, QA `ml/qa/runs/klue` (null margin -10) |
| Data | 45 passages, 47 lines of text · 52 gold items, 4 pending (to be left for the author), 6 mutable (not extracted yet) |
| Scoring | an item is right when subject (a pending claim: its candidates), attribute and value all match; extra = false positive, missed = gold the extractor didn't find |

## Round 1 — 2026-10-06: the extractor as merged (#40 – #46)

| | right | extra | missed | precision | recall | F1 |
|---|---|---|---|---|---|---|
| all (strict) | 32 | 0 | 24 | 1.000 | 0.571 | 0.727 |
| attribute and value only | 32 | 0 | 24 | 1.000 | 0.571 | 0.727 |

By attribute: origin 3/3, scars 3/4, age 6/8, eye color 13/21, height 1/3, hair color 5/12, location features 1/5; the 6 mutable ones are all missed (not extracted yet).

By kind of case (right / right + missed): origin 2/2, scars 2/2, age 2/2, multi-attribute 2/2, NER-only names 3/3, particle on a name 1/1, possessive 1/1, disguise 2/2, pending 4/5, alias 3/6, basic 4/5, dialogue 3/5, pronoun-gender 2/3, pronoun-he 7/15, pronoun-she 8/16, scenes 8/15, location 1/5, plural 0/2, multi-subject 0/2, figurative 0/1.

**The extractor never claims what it shouldn't here, and misses about 4 in 10 of what it should.** No false positive on the passages built to produce them (someone else's eyes, a line of dialogue, snow, footprints, "열심히 살았다", a place only passed through, a "그녀" for a character the text doesn't name), and where it does claim, it's about the right character every time (the two tables are the same). What it loses is recall, mostly after a pronoun.

### Where the 24 misses are

Looking at the question asked and the answer the QA model gave for each:

- **The question names someone the sentence doesn't (10)**: after a pronoun or an alias the sentence says "그녀의 은빛 머리카락이…" or "철수형의 눈동자는…" and the question is "세린의 머리색은?" / "김철수의 눈 색깔은?"; the model answers "no answer" to a question about a person the context doesn't mention (p02, p04, p08, p18, p34, p39 ×2, p41, p43, p44). It's the largest loss, and across every attribute, so it'll cost the mutable ones too.
- **A place's features (4)**: "특징은?" is a poor question for a sentence like "벨로스 성은 산 위에 우뚝 서 있었다"; the QA model answers for 1 of 5 (p16, p38 ×2, p45).
- **By design (6)**: two names in a sentence with no possessor (p23, 2 items), a plural "그들" (p29, 2), "그녀의" in a sentence that names someone else (p42), and a pronoun three sentences from its name (p35: the window is two; design doc 7.1.1 says two or three).
- **The QA model's own limits (2)**: a figurative value ("칠흑 같았다", p24) and a height said as a verb ("키가 컸다", p14).
- **A cue's color word is out of reach (1)**: "그의 눈이 어둠 속에서 붉게 번뜩였다" has it four words after the noun, the window is three (p03).
- **A body part taken for another person (1)**: in "카엘은 … 오른손의 흉터를 문질렀다" the possessor "오른손" isn't a character, so the cue is skipped as "somebody else's" (p39).

### What to try next, in order of what it should be worth

1. Ask the QA model about what the sentence says: the pronoun or alias as written ("그녀의 머리색은?"), or the sentence with the name put in for the pronoun. (10)
2. Take the place's features from the sentence itself instead of asking for them. (up to 4)
3. Treat a body part ("오른손의", "왼팔의") as no possessor at all; a longer window for a cue's color word; how far back a pronoun looks. (1 + 1 + 1)
4. Extract the mutable attributes (6, once there's a question for each).

The set is small (one or two items is noise), so each of these is judged by the whole table and by `--errors`, not by one number.
