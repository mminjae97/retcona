# Claim extraction evaluation

The claim extractor (`backend/pipeline/extract_claims.py`, design doc 7.1.1) works from a manuscript to claims in several steps — sentence splitting, the names a sentence mentions, a cue for an attribute, the QA model's answer, rules for pronouns — and `ml/ner` and `ml/qa` score only two of them, on their own datasets. This directory scores the whole of it on novel passages, so that a change to any step can be judged by what it does to the claims that come out. What was measured, and what each change did, is in [RESULTS.md](RESULTS.md).

## Data

`eval/passages.jsonl`: 97 passages of novel prose (fantasy and contemporary), written for this repository, with the claims each one holds. `casts.json` has the characters and locations registered when a passage is run (names, aliases, gender, pronoun), so the same cast serves several passages.

A passage lists what the extractor should find — `gold`, one item per subject and attribute with the surface forms that count as the right value — and `pending`, what it should leave for the author to pick because the text doesn't say which of several characters it is. Everything else it extracts is a false positive. The passages are short on purpose and each has tags for the kind of case it tests, so a score can be read by case: a pronoun that gender settles, a possessor that isn't a named character ("노인의 눈"), a line of dialogue, an idiom that looks like a cue ("눈을 뜨자", "발자국"), a name two characters share, an alias, a name only the NER model knows, a figurative value ("칠흑 같은"), and longer scenes that mix them.

The mutable attributes (hairstyle, outfit, condition, belongings) are in the data too, marked `"mutable": true`: the extractor doesn't extract them yet, and they're counted as misses on their own, apart from the main score, so that adding them shows.

The gold was written by hand, by one person, from the sentences as a reader would understand them: where a reader would link "그녀" to a character the text doesn't name within a few sentences, the gold links it, even though the extractor doesn't. 97 passages is a small set: a difference of one or two items is noise. The passages tagged `review` (p56–p97) are the sentences reviewers found the rules getting wrong, kept so that a change is judged on all of them at once.

## Setup

The backend's environment (`pip install -e backend`) with the NER and QA models trained in `ml/ner` and `ml/qa` (the NLI model isn't needed). No database.

## Steps

Run from `backend/`:

```bash
python ../ml/extraction/evaluate.py                       # the scores
python ../ml/extraction/evaluate.py --errors              # + every extra and missed item
python ../ml/extraction/evaluate.py --tag pronoun-he      # only the passages with a tag
```

An item is right when its subject (for a pending claim, its candidates), attribute and value all match; the "attribute and value only" table tells a wrong subject from a wrong value. A run takes about 15 s on a CPU.
