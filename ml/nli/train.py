"""Fine-tunes a Korean encoder for NLI (design doc chapter 5).

Two stages, since KLUE-NLI (25k pairs) would be lost among KorNLI's 943k if
the two were simply mixed:

    python train.py --data kornli --init klue/roberta-base --output runs/stage1
    python train.py --data klue --init runs/stage1 --output runs/stage2

Each stage evaluates on KLUE-NLI dev as it goes and saves the final model to
--output, loadable by the backend (NLI_MODEL=<that directory>).
"""

import argparse
import random
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
    args = parser.parse_args()

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
        save_total_limit=2,
        load_best_model_at_end=True,
        metric_for_best_model="accuracy",
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
    # Resumes from the latest checkpoint in --output if a run was interrupted.
    resume = any(Path(args.output).glob("checkpoint-*"))
    trainer.train(resume_from_checkpoint=resume or None)
    print("KLUE-NLI dev:", trainer.evaluate())
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)


if __name__ == "__main__":
    main()
