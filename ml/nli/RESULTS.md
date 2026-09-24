# NLI experiment results

A running record of every model trained or compared here, with enough of the setup to reproduce it. Newest round last. Raw logs and full reports live in `runs/` (not committed); the numbers below are copied from them.

Metrics:
- **KLUE-NLI dev**: accuracy on the 3,000-pair dev set (general Korean NLI).
- **Novel**: accuracy on `eval/novel.jsonl` (setting-card premise vs. novel prose). This is closest to what the service does.
- **Flag P / R**: precision and recall of the backend's decision — a pair is flagged when P(contradiction) ≥ 0.5 (`backend/pipeline/judges.py`). Recall is how many real contradictions get caught; precision is how many flags are real.
- **CPU ms/pair**: inference on the CPU in batches of 16, as the worker runs it.

## Setup common to all runs

| | |
|---|---|
| Machine | RTX 3060 12 GB, Windows 10, 6 CPU threads |
| Environment | `retcona-ml`: Python 3.12, PyTorch 2.14.0+cu126, transformers 5.17.0 |
| Base model | `klue/roberta-base` |
| Training defaults (`train.py`) | batch 32, max length 128, lr 2e-5, warmup 6%, weight decay 0.01, fp16, seed 42. Rounds 1–3 kept the checkpoint best on KLUE-NLI dev accuracy (for `mixed` and `stage2` that was the final one; `stage1` kept epoch 0.81). `train.py` now keeps the final model instead (see "Training changes" below). |
| Data | KorNLI train 942,854 · KLUE-NLI train 24,998 · KLUE-NLI dev 3,000 · novel set: 77 pairs in round 1, 150 from round 2 — see README.md |

## Round 1 — 2026-09-24

### Runs

| Run | Init | Training data | Epochs | lr | Eval every | Time |
|---|---|---|---|---|---|---|
| `stage1` | klue/roberta-base | KorNLI | 1 | 2e-5 | 2,000 steps | 65 min (29,465 steps, 7.6 steps/s) |
| `stage2` | `stage1` | KLUE-NLI | 3 | 2e-5 | 500 steps | 5 min (2,346 steps) |
| `stage2-1ep` | `stage1` | KLUE-NLI | 1 | 1e-5 | 250 steps | 2 min |
| `mixed` | klue/roberta-base | KorNLI + KLUE-NLI, shuffled together (967,852) | 1 | 2e-5 | 2,000 steps | 67 min (30,246 steps, 7.5 steps/s) |

KLUE-NLI dev accuracy during training (epoch: accuracy):
- `stage1`: 0.07: 0.719 · 0.14: 0.767 · 0.20: 0.756 · 0.27: 0.771 · 0.34: 0.776 · 0.41: 0.790 · 0.48: 0.785 · 0.54: 0.786 · 0.61: 0.798 · 0.68: 0.793 · 0.75: 0.801 · **0.81: 0.808** · 0.88: 0.808 · 0.95: 0.801 · 1.00: 0.805 (best kept: 0.808)
- `stage2`: 0.64: 0.872 · 1.28: 0.884 · 1.92: 0.880 · **2.56: 0.885** · 3.00: 0.885
- `stage2-1ep`: final 0.872

### Comparison

| Model | KLUE-NLI dev | Novel | Flag P | Flag R | CPU ms/pair |
|---|---|---|---|---|---|
| `Huffon/klue-roberta-base-nli` (current backend default; KLUE-NLI) | 0.866 | 0.662 | 0.615 | 0.500 | 22.8 idle |
| `ehdwns1516/klue-roberta-base-kornli` (public; KorNLI) | 0.714 | 0.649 | 0.609 | 0.875 | ~24 |
| **`stage1`** (KorNLI) | 0.808 | **0.779** | **0.788** | **0.812** | ~24 |
| `stage2` (KorNLI → KLUE-NLI 3 ep) | **0.885** | 0.714 | 0.792 | 0.594 | 16.2 idle |
| `stage2-1ep` (KorNLI → KLUE-NLI 1 ep, lr 1e-5) | 0.873 | 0.688 | 0.750 | 0.562 | ~24 |

"~24" was measured while another model trained on the same machine. All five are the same size (roberta-base), so their idle speed is about the same (16–23 ms).

Contradiction-label F1 (KLUE-NLI dev / novel): Huffon 0.856 / 0.552 · ehdwns1516 0.697 / 0.734 · stage1 0.809 / 0.788 · stage2 0.884 / 0.679 · stage2-1ep 0.864 / 0.643.

### Observations

- The current model misses half the novel set's contradictions. It reads `스무 살` against `17살`, `검은 머리카락` against `은발`, or `남부 항구 도시에서 태어난` against `북부 설원` as neutral. It also flags paraphrases (`열일곱`, `은빛`, `벽안`) as contradictions.
- KorNLI alone (`stage1`) gives the best result on novel prose, although it scores lower on KLUE-NLI dev.
- Continuing on KLUE-NLI raises KLUE-NLI dev accuracy (0.808 → 0.885), but novel recall drops (0.81 → 0.59). That still happens with 1 epoch at half the learning rate (0.56). Training on KLUE-NLI pushes the model to read novel-style contradictions as neutral.
- The novel set is small: 32 contradictions, so one pair is about 3 points of recall. The gap between `stage1` and `stage2` (26 vs. 19 caught) is large enough to take seriously, but a bigger set is needed before choosing.

### Next

- `mixed`: KorNLI and KLUE-NLI in one run, to see whether it keeps `stage1`'s novel recall while gaining on KLUE-NLI.
- Grow the novel set to about 150 pairs, then compare `stage1`, `stage2` and `mixed` again.

## Round 2 — 2026-09-24, novel set grown to 150 pairs

The novel set has 73 new pairs: new characters and places (이안, 델리아, 루카, 은빛 호수, 하쿠 성채, 붉은 사막, 로웰 마을), dialogue, numbers (`7살` vs. `열일곱 살`, `180cm` vs. `150센티미터`), color words (흑안, 적안, 적발), two-subject sentences, and the restatements the backend uses for pronoun sentences. It now has 150 pairs: 62 contradiction, 61 neutral, 27 entailment. KLUE-NLI dev numbers are unchanged from round 1.

| Model | Novel (150) | Flag P | Flag R | Contradiction F1 | Caught / 62 |
|---|---|---|---|---|---|
| `Huffon/klue-roberta-base-nli` | 0.687 | 0.707 | 0.468 | 0.563 | 29 |
| `ehdwns1516/klue-roberta-base-kornli` | 0.693 | 0.671 | 0.823 | 0.738 | 51 |
| **`stage1`** | **0.820** | **0.836** | 0.823 | **0.816** | 51 |
| `stage2` | 0.733 | 0.833 | 0.565 | 0.673 | 35 |
| `stage2-1ep` | 0.733 | 0.833 | 0.565 | 0.673 | 35 |

(`stage2` and `stage2-1ep` get the same confusion matrix on this set — `[[18 4 5] [2 57 2] [0 27 35]]` — with different probabilities; they're different models that happen to decide the same.)

Round 1's picture holds on the larger set. `stage1` catches as many contradictions as the public KorNLI model (51/62) with far fewer false flags (precision 0.836 vs. 0.671). Continuing on KLUE-NLI loses 16 of those catches. `stage2`'s 27 misses are almost all contradictions it reads as neutral, e.g. `적발` → `푸른 머리카락`, `17살` → `서른을 훌쩍 넘긴`, and dialogue (`"내 눈이 원래 이렇게 붉었던가."`).

Full reports: `runs/eval-round1.txt`, `runs/eval-novel150.txt`.

## Round 3 — 2026-09-24, `mixed`

`mixed` was trained on KorNLI and KLUE-NLI shuffled into one set (KLUE-NLI is 2.6% of it), for 1 epoch with the round-1 defaults.

KLUE-NLI dev during training (epoch: accuracy): 0.07: 0.763 · 0.13: 0.788 · 0.20: 0.792 · 0.26: 0.794 · 0.33: 0.820 · 0.40: 0.825 · 0.46: 0.817 · 0.53: 0.840 · 0.60: 0.832 · 0.66: 0.835 · 0.73: 0.849 · 0.79: 0.854 · 0.86: 0.844 · 0.93: 0.844 · 0.99: 0.855 · **1.00: 0.855**

| Model | KLUE-NLI dev | Novel (150) | Flag P | Flag R | Caught / 62 | CPU ms/pair |
|---|---|---|---|---|---|---|
| `Huffon/klue-roberta-base-nli` (current) | **0.866** | 0.687 | 0.707 | 0.468 | 29 | 22.8 |
| `stage1` (KorNLI) | 0.808 | **0.820** | **0.836** | **0.823** | **51** | ~24* |
| `stage2` (KorNLI → KLUE-NLI) | **0.885** | 0.733 | 0.833 | 0.565 | 35 | 16.2 |
| **`mixed`** (KorNLI + KLUE-NLI together) | 0.855 | **0.820** | 0.823 | **0.823** | **51** | 15.3 |

\* measured while another model was training.

Novel confusion for `mixed` (rows gold, columns predicted; entailment / neutral / contradiction): `[[19 1 7] [3 53 5] [0 11 51]]`.

### Observations

- `mixed` keeps `stage1`'s novel result (same accuracy and recall, one more false flag) and gains 4.7 points on KLUE-NLI dev (0.808 → 0.855). Mixed in with KorNLI, KLUE-NLI doesn't pull novel-style contradictions toward neutral the way training on it last does.
- Its 11 misses include Sino-Korean color words (`적발` vs. `푸른 머리카락`, `적안` vs. `잿빛 눈동자`), `금발` vs. `새하얀 머리카락`, implied contradictions (`활엽수들이 붉게 물들어` vs. an evergreen snow forest, `변방의 작은 어촌에서 나고 자란` vs. the capital), and numbers in prose (`150센티미터를 겨우 넘는` vs. `180cm`).
- Its 12 false flags fall into three groups:
  - restated synonyms: `열일곱` vs. `17살`, `노란빛` vs. `금발`, `오른손 등` vs. `오른손 손등`, `까맸다` vs. `흑발`
  - sentences about the subject that don't state the attribute at all: `고향 이야기를 꺼내지 않았다`, `나이를 한 번도 밝힌 적이 없었다`, `눈을 감은 채`
  - the two-subject sentence. The backend already avoids this case by judging the claim's restatement instead.

### Decision

Chosen (2026-09-24): `mixed` is the backend's model, kept locally in `runs/mixed` for now (`backend/infra/inference_client.py` uses it by default). Rationale: it's tied for the best novel result and stays close to the current model on general Korean NLI, at the same size and speed. It's also the combination chosen for the project (KorNLI + KLUE-NLI, official data only). Remaining weak spots for a later round: synonym restatements, attribute-less sentences, Sino-Korean color and number expressions. These could be addressed with more novel-style training pairs or with a check in the backend that the sentence mentions the attribute at all.

## Training changes after round 3

- `train.py` saves the model as it is at the end of training instead of the checkpoint with the best KLUE-NLI dev accuracy. That score moved against novel-prose recall in rounds 1–3, so it shouldn't pick the model. `mixed` is unaffected: its best checkpoint was the final one (epoch 1.00: 0.855).
- An `--output` that already has checkpoints is refused unless `--resume` is given. Before, a re-run silently continued the old run, even with different `--data` or `--init`.
