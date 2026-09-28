# NER experiment results

A running record of every model trained or compared here, with enough of the setup to reproduce it. Newest round last. Raw logs live in `runs/` (not committed); the numbers below are copied from them.

Metrics:
- **KLUE-NER dev**: entity-level precision / recall / F1 on the 5,000 dev sentences, span and type exact — all six types, and PS and LC alone (the two the extractor uses).
- **Novel**: PS and LC names per sentence on `eval/novel.jsonl`, compared as (surface, type) sets — P / R / F1, and how many sentences come out exactly right.
- **CPU ms/sentence**: one sentence at a time on the CPU, as the worker would run it.

## Setup common to all runs

| | |
|---|---|
| Machine | RTX 3060 12 GB, Windows 10, 6 CPU threads |
| Environment | `retcona-ml`: Python 3.12, PyTorch 2.14.0+cu126, transformers 5.17.0 |
| Base model | `klue/roberta-base` |
| Training defaults (`train.py`) | 3 epochs, batch 32, max length 256, lr 5e-5, warmup 6%, weight decay 0.01, fp16, seed 42; the final model is saved |
| Data | KLUE-NER train 21,008 · dev 5,000 · novel set 40 sentences (51 names) |

## Round 1 — 2026-09-28

### Runs

| Run | Init | Training data | Epochs | Time |
|---|---|---|---|---|
| `klue` | klue/roberta-base | KLUE-NER train | 3 | 4 min (1,971 steps, 7.9 steps/s) |

### Results

| Run | KLUE-NER dev F1 (all) | PS P / R / F1 | LC P / R / F1 | Novel P / R / F1 | Novel exact | CPU ms/sentence |
|---|---|---|---|---|---|---|
| `klue` | 0.878 (P 0.872, R 0.884) | 0.916 / 0.909 / 0.912 | 0.789 / 0.816 / 0.803 | 0.935 / 0.843 / 0.887 | 32/40 | 35.6 |

### What the novel set shows

- **Particles stuck to a name** (3 of 8 misses): `라일라는`, `벨로스 성의`, `하윤아` — a token that runs the name into its particle can only be labelled whole (README.md). The extractor can recover the name across sentences (the same name recurs with different particles) or strip a particle when the registered names say so.
- **Fantasy place names that read like common noun phrases** (4): `검은 숲`, `잿빛 협곡`, `그림자 숲`, `동쪽 평원` — KLUE-NER's locations are real place names in news. The extractor matches registered names and aliases by string first, which covers places the author has entered; a novel-domain training set (e.g. NIKL's corpus later) is the fix for unregistered ones.
- **A region named inside dialogue** (1): `북부` in `"아버지는 북부 출신이셨어요."`.
- No false names: pronouns and common nouns (`그녀`, `사내`, `소녀`, `여관 주인`) weren't tagged.
