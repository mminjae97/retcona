"""Fine-tunes a Korean encoder for named-entity recognition (design doc 7.1.1).

The claim extractor uses it to find character (PS) and location (LC) names a
novel hasn't registered yet; it's trained on all six KLUE-NER types, which
the data is annotated with anyway:

    python train.py --init klue/roberta-base --output runs/klue

Tokens are labelled from the characters they cover (KLUE-NER tags
characters): a token's label is the entity its first character is in — B-
when that's where the entity starts, I- after. The run evaluates on KLUE-NER
dev as it goes, for the record, and saves the model as it is at the end of
training to --output. --output must be new or empty; --resume continues an
interrupted run left there (with the same arguments).
"""

import argparse
import random
import shutil
from pathlib import Path

import numpy as np
import torch
from transformers import (
    AutoModelForTokenClassification,
    AutoTokenizer,
    DataCollatorForTokenClassification,
    Trainer,
    TrainingArguments,
)

from data import LABEL_IDS, LABELS, Sentence, load

IGNORE = -100  # tokens the loss skips (special tokens)


def token_labels(sentence: Sentence, offsets: list[tuple[int, int]]) -> list[int]:
    by_char: dict[int, tuple[int, str]] = {}
    for entity in sentence.entities:
        for index in range(entity.start, entity.end):
            by_char[index] = (entity.start, entity.kind)
    labels = []
    seen: set[int] = set()  # entities already begun
    for start, end in offsets:
        if start == end:
            labels.append(IGNORE)
            continue
        # The token's first non-space character decides.
        first = next((index for index in range(start, end) if not sentence.text[index].isspace()), start)
        entity = by_char.get(first)
        if entity is None:
            labels.append(LABEL_IDS["O"])
            continue
        entity_start, kind = entity
        prefix = "I" if entity_start in seen else "B"
        seen.add(entity_start)
        labels.append(LABEL_IDS[f"{prefix}-{kind}"])
    return labels


class SentenceDataset(torch.utils.data.Dataset):
    def __init__(self, sentences: list[Sentence], tokenizer, max_length: int) -> None:
        self.sentences = sentences
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.sentences)

    def __getitem__(self, index: int) -> dict:
        sentence = self.sentences[index]
        encoded = self.tokenizer(
            sentence.text,
            truncation=True,
            max_length=self.max_length,
            return_offsets_mapping=True,
            return_token_type_ids=False,
        )
        encoded["labels"] = token_labels(sentence, encoded.pop("offset_mapping"))
        return encoded


def _token_accuracy(prediction) -> dict:
    predicted = prediction.predictions.argmax(axis=-1)
    mask = prediction.label_ids != IGNORE
    return {"token_accuracy": float((predicted[mask] == prediction.label_ids[mask]).mean())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--init", required=True, help="base model: a Hugging Face id or an earlier --output")
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=float, default=3.0)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--eval-steps", type=int, default=500)
    parser.add_argument("--limit", type=int, help="use only this many training sentences (a quick check)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true", help="continue an interrupted run in --output")
    args = parser.parse_args()

    output = Path(args.output)
    if args.resume:
        if not any(output.glob("checkpoint-*")):
            parser.error(f"--resume: {args.output} has no checkpoint to continue from")
    elif output.exists() and any(output.iterdir()):
        parser.error(f"{args.output} isn't empty: pick another --output, or pass --resume to continue an interrupted run")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    train = load("klue")
    random.shuffle(train)
    if args.limit:
        train = train[: args.limit]
    dev = load("klue-dev")
    print(f"Training on {len(train):,} sentences, evaluating on {len(dev):,} (KLUE-NER dev)")

    tokenizer = AutoTokenizer.from_pretrained(args.init)
    model = AutoModelForTokenClassification.from_pretrained(
        args.init,
        num_labels=len(LABELS),
        id2label=dict(enumerate(LABELS)),
        label2id=LABEL_IDS,
    )
    training_args = TrainingArguments(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size * 2,
        warmup_steps=0.06,  # a fraction below 1 is a share of the total steps
        weight_decay=0.01,
        fp16=torch.cuda.is_available(),
        eval_strategy="steps",
        eval_steps=args.eval_steps,
        save_strategy="steps",
        save_steps=args.eval_steps,
        save_total_limit=1,  # only for resuming; the final model is what's saved
        logging_steps=100,
        report_to=[],
        seed=args.seed,
        dataloader_num_workers=0,  # Windows: worker processes would each re-import the data
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=SentenceDataset(train, tokenizer, args.max_length),
        eval_dataset=SentenceDataset(dev, tokenizer, args.max_length),
        data_collator=DataCollatorForTokenClassification(tokenizer),
        compute_metrics=_token_accuracy,
    )
    trainer.train(resume_from_checkpoint=args.resume or None)
    print("KLUE-NER dev:", trainer.evaluate())
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)
    for checkpoint in Path(args.output).glob("checkpoint-*"):
        shutil.rmtree(checkpoint)


if __name__ == "__main__":
    main()
