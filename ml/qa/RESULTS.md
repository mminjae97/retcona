# Extractive QA experiment results

A running record of every model trained or compared here, with enough of the setup to reproduce it. Newest round last. Raw logs live in `runs/` (not committed); the numbers below are copied from them.

Metrics (`evaluate.py`):
- **Exact / F1**: the answer against the gold one with spaces and punctuation removed — exact match, and character-overlap F1 (partial credit for a span that's a little longer or shorter). An unanswerable question counts as right only when the model gives no answer.
- **Null acc.**: how often the model's answer-or-not matches the gold (answers an answerable question, declines an unanswerable one), whatever the span.
- **Null margin**: "no answer" wins unless the best span scores higher by more than this. Negative values answer more often.

## Setup common to all runs

| | |
|---|---|
| Machine | RTX 3060 12 GB, Windows 10, 6 CPU threads |
| Environment | `retcona-ml`: Python 3.12, PyTorch 2.14.0+cu126, transformers 5.17.0 |
| Base model | `klue/roberta-base` |
| Training defaults (`train.py`) | 2 epochs, batch 16, max length 384, stride 128, lr 3e-5, warmup 6%, weight decay 0.01, fp16, seed 42; the final model is saved |
| Data | KLUE-MRC train 17,554 questions (30,527 windows) · dev 5,841 · novel set 40 questions (8 unanswerable) |

## Round 1 — 2026-09-28

### Runs

| Run | Init | Training data | Epochs | Time |
|---|---|---|---|---|
| `klue` | klue/roberta-base | KLUE-MRC train | 2 | 20 min (3,816 steps, 3.1 steps/s) |

### Results by null margin (`klue`)

| Null margin | Novel exact | Novel F1 | Novel null acc. | KLUE-MRC dev exact | Dev F1 | Dev null acc. |
|---|---|---|---|---|---|---|
| 0 | 0.275 | 0.275 | 0.275 | 0.600 | 0.638 | 0.693 |
| -2 | 0.375 | 0.406 | 0.425 | 0.614 | 0.661 | 0.736 |
| -4 | 0.400 | 0.444 | 0.475 | 0.609 | 0.662 | 0.753 |
| -6 | 0.450 | 0.556 | 0.650 | 0.594 | 0.649 | 0.752 |
| -8 | 0.475 | 0.581 | 0.675 | 0.573 | 0.631 | 0.747 |
| **-10** | **0.525** | **0.663** | **0.775** | 0.550 | 0.611 | 0.742 |
| -15 | 0.500 | 0.677 | 0.800 | 0.497 | 0.563 | 0.714 |

### What the novel set shows

- **At margin 0 the model declines nearly everything in novel prose** (29 of 32 answerable questions): KLUE-MRC's questions are long, natural questions over news and Wikipedia passages, ours a short templated one over a sentence. A margin of about -10 is where novel prose does best; it costs KLUE-MRC dev a little, which isn't what the extractor runs on.
- **About half of the misses at -10 are span boundaries, not wrong answers**: `붉은 눈동자` for `붉은`, `은빛 머리카락` for `은빛`, `화상 자국` for `오른손등에는 화상 자국`, `작은 어촌` for `강을 끼고 늘어선 작은 어촌` — usable as a card value.
- **Real misses**: figurative or indirect values — `칠흑 같은` (hair), `백발`, `노인`, `바다 같구나`, `부산에서 올라온` (origin), `눈 덮인`.
- **Wrong answers**: `열일곱 살` from `열일곱 살이 되던 해` (an age in the past, not now), `긴 생머리` as a hair *color*.
- The judgment itself doesn't depend on this: NLI compares the manuscript sentence with the setting, not the extracted value. The value is what accepting writes to a card, what fills a new card's empty attributes, and what the "repeats the setting" check reads.

Next: novel-domain training questions (templated attribute questions over novel sentences) on top of `klue`, and comparing with rule-based value extraction for the attributes with regular wording (colors, ages, heights).
