# Extractive QA model fine-tuning

The claim extractor (design doc 7.1.1) takes the value of a setting-card attribute out of a sentence by asking a question about it ("레온의 눈 색깔은?" → "푸른색"), and needs to hear "no answer" from most sentences, which don't state the attribute. This directory trains that model: `klue/roberta-base` fine-tuned on KLUE-MRC, and checked on novel prose. What was tried is in [RESULTS.md](RESULTS.md).

## Data

Only officially distributed datasets, fetched from a pinned commit and checked by SHA-256 (`download.py`):

| Dataset | Source | Questions | Used for | License |
|---|---|---|---|---|
| KLUE-MRC train (Wikipedia, news) | [KLUE-benchmark/KLUE](https://github.com/KLUE-benchmark/KLUE) | 17,554 (5,517 unanswerable) | training | CC BY-SA 4.0 |
| KLUE-MRC dev | same | 5,841 (1,833 unanswerable) | evaluation | CC BY-SA 4.0 |
| Novel set (`eval/novel.jsonl`, ours) | this repository | 40 (8 unanswerable) | evaluation | — |

KorQuAD 1.0 isn't used: its license (CC BY-ND 2.0 KR) doesn't allow derivatives. KLUE doesn't publish its test set. CC BY-SA 4.0 asks for attribution: a model trained here is credited to KLUE (Park et al., 2021) wherever the service lists its sources.

The novel set asks what the backend will ask — one attribute of one character or location, from a sentence or two of novel prose — including sentences that name the subject but don't state the attribute, and ones that state it through a pronoun after the name.

## Setup

The same conda environment as `ml/nli` (see its README): CUDA PyTorch, then `pip install -r requirements.txt`.

## Steps

Run from this directory:

```bash
python download.py                                              # data/ (~66 MB)
python train.py --init klue/roberta-base --output runs/klue     # ~20 min on an RTX 3060
python evaluate.py --model runs/klue --errors --latency
```

An answer is the best span (start + end logits, at most 30 tokens) unless "no answer" scores higher by more than `--null-margin`; raising it answers less often (a negative margin, more often). `data/` and `runs/` aren't committed.
