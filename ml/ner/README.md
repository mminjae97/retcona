# NER model fine-tuning

The claim extractor (design doc 7.1.1) finds the characters and locations a sentence is about by the names and aliases a novel has registered, and by a named-entity recognizer for names it hasn't registered yet. This directory trains that recognizer: `klue/roberta-base` fine-tuned on KLUE-NER, and checked on novel prose. What was tried is in [RESULTS.md](RESULTS.md).

## Data

Only officially distributed datasets, fetched from a pinned commit and checked by SHA-256 (`download.py`):

| Dataset | Source | Sentences | Used for | License |
|---|---|---|---|---|
| KLUE-NER train (news, movie reviews) | [KLUE-benchmark/KLUE](https://github.com/KLUE-benchmark/KLUE) | 21,008 | training | CC BY-SA 4.0 |
| KLUE-NER dev | same | 5,000 | evaluation | CC BY-SA 4.0 |
| Novel set (`eval/novel.jsonl`, ours) | this repository | 40 | evaluation | — |

KLUE-NER tags six types per character (PS person, LC location, OG organization, DT date, TI time, QT quantity); the model learns all six, and the extractor uses PS and LC. KLUE doesn't publish its test set. CC BY-SA 4.0 asks for attribution: a model trained here is credited to KLUE (Park et al., 2021) wherever the service lists its sources.

The novel set is sentences of novel prose (fantasy and contemporary) with the person and location names in each, pronouns and common nouns ("사내", "소녀") left out, as the extractor needs them. It's compared per sentence as a set of (name, type).

Later, the NIKL 모두의 말뭉치 named-entity corpus may be added, once its application and terms of use are settled.

## Setup

The same conda environment as `ml/nli` (see its README): CUDA PyTorch, then `pip install -r requirements.txt`.

## Steps

Run from this directory:

```bash
python download.py                                              # data/ (~13 MB)
python train.py --init klue/roberta-base --output runs/klue     # a few minutes on an RTX 3060
python evaluate.py --model runs/klue --errors --latency
```

Tokens are labelled from the characters they cover (a token's label is that of its first character). A token that runs a name and a particle together (`스타뎀의`) can only be labelled as a whole, so the name comes back with its particle; about 5% of KLUE-NER dev sentences have such a token. `data/` and `runs/` aren't committed.
