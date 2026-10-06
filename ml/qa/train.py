"""Fine-tunes a Korean encoder for extractive question answering (design doc 7.1.1).

The claim extractor asks it for the value of a setting-card attribute in a
sentence ("레온의 눈 색깔은?" -> "푸른색"), or learns that the sentence
doesn't say (the [CLS] token as the answer, as for KLUE-MRC's unanswerable
questions):

    python train.py --init klue/roberta-base --output runs/klue

A long passage is split into overlapping windows (--max-length, --stride);
a window that doesn't hold the answer is trained to answer "none". The run
evaluates loss on KLUE-MRC dev as it goes, for the record (evaluate.py scores
the answers), and saves the model as it is at the end of training to
--output. --output must be new or empty; --resume continues an interrupted
run left there (with the same arguments).
"""

import argparse
import random
import shutil
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForQuestionAnswering, AutoTokenizer, DataCollatorWithPadding, Trainer, TrainingArguments

from data import Example, load


def features(examples: list[Example], tokenizer, max_length: int, stride: int) -> list[dict]:
    """Each example's windows, with the answer's token positions (0, 0: no answer in the window)."""
    encoded = tokenizer(
        [example.question for example in examples],
        [example.context for example in examples],
        truncation="only_second",
        max_length=max_length,
        stride=stride,
        return_overflowing_tokens=True,
        return_offsets_mapping=True,
        return_token_type_ids=False,
    )
    windows = []
    for index, offsets in enumerate(encoded["offset_mapping"]):
        example = examples[encoded["overflow_to_sample_mapping"][index]]
        sequence_ids = encoded.sequence_ids(index)
        start_position = end_position = 0
        if example.answers:
            answer = example.answers[0]
            answer_start, answer_end = answer.start, answer.start + len(answer.text)
            context = [i for i, sequence in enumerate(sequence_ids) if sequence == 1]
            if offsets[context[0]][0] <= answer_start and offsets[context[-1]][1] >= answer_end:
                start_position = next(i for i in context if offsets[i][1] > answer_start)
                end_position = next(i for i in reversed(context) if offsets[i][0] < answer_end)
        windows.append(
            {
                "input_ids": encoded["input_ids"][index],
                "attention_mask": encoded["attention_mask"][index],
                "start_positions": start_position,
                "end_positions": end_position,
            }
        )
    return windows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--init", required=True, help="base model: a Hugging Face id or an earlier --output")
    parser.add_argument("--output", required=True)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=384)
    parser.add_argument("--stride", type=int, default=128)
    parser.add_argument("--eval-steps", type=int, default=1000)
    parser.add_argument("--limit", type=int, help="use only this many training questions (a quick check)")
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
    tokenizer = AutoTokenizer.from_pretrained(args.init)
    train_windows = features(train, tokenizer, args.max_length, args.stride)
    dev_windows = features(dev, tokenizer, args.max_length, args.stride)
    print(f"Training on {len(train):,} questions ({len(train_windows):,} windows), dev loss on {len(dev_windows):,} windows")

    model = AutoModelForQuestionAnswering.from_pretrained(args.init)
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
        train_dataset=train_windows,
        eval_dataset=dev_windows,
        data_collator=DataCollatorWithPadding(tokenizer),
    )
    trainer.train(resume_from_checkpoint=args.resume or None)
    print("KLUE-MRC dev:", trainer.evaluate())
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)
    for checkpoint in Path(args.output).glob("checkpoint-*"):
        shutil.rmtree(checkpoint)


if __name__ == "__main__":
    main()
