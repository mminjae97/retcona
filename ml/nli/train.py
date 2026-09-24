"""Fine-tunes a Korean encoder for NLI (design doc chapter 5).

The backend's model ("mixed" in RESULTS.md) is KorNLI and KLUE-NLI shuffled
into one training set:

    python train.py --data kornli klue --init klue/roberta-base --output runs/mixed

--init also takes an earlier run's --output, to continue from it (e.g.
--data klue on top of a KorNLI run — which RESULTS.md found to miss far more
contradictions in novel prose). The run evaluates on KLUE-NLI dev as it goes,
for the record, and saves the model as it is at the end of training to
--output, loadable by the backend (NLI_MODEL=<that directory, absolute>).
Its checkpoints are kept only until then. An --output that still has
checkpoints (an interrupted run) is refused, unless --resume continues that
run (with the same arguments).
"""

import argparse
import random
import shutil
from pathlib import Path

import numpy as np
import torch
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

from data import LABEL_IDS, LABELS, Example, load


class PairDataset(torch.utils.data.Dataset):
    """Tokenizes each pair when it's read, so the 943k pairs aren't all
    tokenized up front."""

    def __init__(self, examples: list[Example], tokenizer, max_length: int) -> None:
        self.examples = examples
        self.tokenizer = tokenizer
        self.max_length = max_length

    def __len__(self) -> int:
        return len(self.examples)

    def __getitem__(self, index: int) -> dict:
        example = self.examples[index]
        encoded = self.tokenizer(
            example.premise,
            example.hypothesis,
            truncation=True,
            max_length=self.max_length,
            # RoBERTa has one token type; the second-sentence ids a BERT-style
            # tokenizer adds are out of its embedding's range.
            return_token_type_ids=False,
        )
        encoded["labels"] = example.label
        return encoded


def _accuracy(prediction) -> dict:
    predicted = prediction.predictions.argmax(axis=-1)
    return {"accuracy": float((predicted == prediction.label_ids).mean())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", nargs="+", required=True, choices=["kornli", "klue"], help="training sets")
    parser.add_argument("--init", required=True, help="base model: a Hugging Face id or an earlier stage's --output")
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-length", type=int, default=128)
    parser.add_argument("--eval-steps", type=int, default=2000)
    parser.add_argument("--limit", type=int, help="use only this many training pairs (a quick check)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true", help="continue an interrupted run in --output")
    args = parser.parse_args()

    has_checkpoints = any(Path(args.output).glob("checkpoint-*"))
    if has_checkpoints and not args.resume:
        parser.error(f"{args.output} already has checkpoints: pass --resume to continue that run, or pick another --output")
    if args.resume and not has_checkpoints:
        parser.error(f"--resume: {args.output} has no checkpoint to continue from")

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    train = [example for name in args.data for example in load(name)]
    random.shuffle(train)
    if args.limit:
        train = train[: args.limit]
    dev = load("klue-dev")
    print(f"Training on {len(train):,} pairs ({', '.join(args.data)}), evaluating on {len(dev):,} (KLUE-NLI dev)")

    tokenizer = AutoTokenizer.from_pretrained(args.init)
    model = AutoModelForSequenceClassification.from_pretrained(
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
        # Only for resuming. The model saved at the end is the final one, not
        # the checkpoint best on KLUE-NLI dev: that score doesn't track how
        # well the model finds contradictions in novel prose (RESULTS.md).
        save_total_limit=1,
        logging_steps=200,
        report_to=[],
        seed=args.seed,
        # Windows: worker processes would each re-import the whole dataset.
        dataloader_num_workers=0,
    )
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=PairDataset(train, tokenizer, args.max_length),
        eval_dataset=PairDataset(dev, tokenizer, args.max_length),
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=_accuracy,
    )
    trainer.train(resume_from_checkpoint=args.resume or None)
    print("KLUE-NLI dev:", trainer.evaluate())
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)
    # The checkpoints (with optimizer state, over 1 GB each) were only for
    # resuming; --output is what the backend loads and what gets hosted.
    for checkpoint in Path(args.output).glob("checkpoint-*"):
        shutil.rmtree(checkpoint)


if __name__ == "__main__":
    main()
