# NLI model fine-tuning

The appearance/location judgment (`backend/pipeline/judges.py`, design doc 7.2) asks an NLI model whether a manuscript sentence contradicts a setting. This directory trains that model: `klue/roberta-base` fine-tuned on KorNLI and KLUE-NLI together (design doc chapter 5). It also compares that model with other checkpoints on novel prose. What was tried and why this recipe was chosen is in [RESULTS.md](RESULTS.md).

## Data

Only officially distributed datasets, fetched from pinned commits of their repositories and checked by SHA-256 (`download.py`):

| Dataset | Source | Pairs | Used for | License |
|---|---|---|---|---|
| KorNLI train (SNLI + MNLI, machine-translated) | [kakaobrain/kor-nlu-datasets](https://github.com/kakaobrain/kor-nlu-datasets) | 942,854 | training | CC BY-SA 4.0 |
| KLUE-NLI train (written in Korean) | [KLUE-benchmark/KLUE](https://github.com/KLUE-benchmark/KLUE) | 24,998 | training | CC BY-SA 4.0 |
| KLUE-NLI dev | same | 3,000 | evaluation | CC BY-SA 4.0 |
| Novel set (`eval/novel.jsonl`, ours) | this repository | 150 | evaluation | — |

KorNLI's dev/test sets aren't used: they're translated from XNLI, which is CC BY-NC 4.0 (non-commercial). KLUE doesn't publish its test set.

CC BY-SA 4.0 asks for attribution: a model trained here is credited to KorNLI (Ham et al., 2020) and KLUE (Park et al., 2021) wherever the service lists its sources.

The novel set pairs a setting written the way the backend writes a premise (`레온의 눈 색깔은 푸른색이다.`) with a sentence of novel prose. Labels are strict NLI: a sentence that fits the setting but adds something (`레온의 하늘빛 눈동자가 흔들렸다`) is neutral, not entailment. What the backend acts on is contradiction or not, which `evaluate.py` reports as flag precision/recall.

## Setup

A separate conda environment with CUDA PyTorch (the backend's is CPU-only). Pick the PyTorch index for the CUDA version `nvidia-smi` shows:

```bash
conda create -n retcona-ml python=3.12
conda activate retcona-ml
pip install torch --index-url https://download.pytorch.org/whl/cu126
pip install -r requirements.txt
```

## Steps

Run from this directory:

```bash
python download.py                                                             # data/ (~175 MB)
python train.py --data kornli klue --init klue/roberta-base --output runs/mixed  # ~70 min on an RTX 3060
python evaluate.py --model runs/mixed Huffon/klue-roberta-base-nli --errors --latency
```

KorNLI and KLUE-NLI are shuffled into one training set (1 epoch). Training on KLUE-NLI after KorNLI instead (`--data kornli`, then `--data klue --init <that run>`) scores higher on KLUE-NLI dev but misses far more contradictions in novel prose (RESULTS.md, rounds 1–3). `train.py` evaluates on KLUE-NLI dev every 2,000 steps for the record and saves the model as it is at the end of training (not the checkpoint best on KLUE-NLI dev, which doesn't track novel-prose results). An interrupted run continues with the same command plus `--resume`. `data/` and `runs/` aren't committed.

The backend uses `runs/mixed` by default (`backend/infra/inference_client.py`); `NLI_MODEL` points it at another directory, given as an absolute path (the worker runs from `backend/`). The model stays on the machine that trained it for now. Hosting it for deployment is on the pre-launch checklist (`docs/pre-launch-checklist.md`).
