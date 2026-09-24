"""Downloads the NLI datasets from their official repositories into ml/nli/data/.

Each file is fetched from a pinned commit, so a later run gets exactly the
same data, and its SHA-256 is checked against the one recorded here.

- KorNLI train (kakaobrain/kor-nlu-datasets, CC BY-SA 4.0): SNLI and MNLI,
  machine-translated into Korean. Its dev/test sets aren't used: they're
  translated from XNLI, which is CC BY-NC 4.0 (non-commercial).
- KLUE-NLI train/dev (KLUE-benchmark/KLUE, CC BY-SA 4.0): written in Korean.
  KLUE doesn't publish its test set; dev is the evaluation set.

Usage: python download.py
"""

import hashlib
import shutil
import sys
import urllib.request
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
# Seconds without data before a download gives up.
TIMEOUT = 60

_KORNLI = "https://raw.githubusercontent.com/kakaobrain/kor-nlu-datasets/0df0fe7d496eb61b092e022e238c2230b29f1cbc/KorNLI"
_KLUE = "https://raw.githubusercontent.com/KLUE-benchmark/KLUE/3efd98708a40ff49251fddde35453f8fbb11f536/klue_benchmark/klue-nli-v1.1"

# local file name -> (url, sha256)
FILES = {
    "snli_1.0_train.ko.tsv": (
        f"{_KORNLI}/snli_1.0_train.ko.tsv",
        "aaf12d8955fcda2b14319e5cabb9b31824c6f504aede460c975b518911f484c0",
    ),
    "multinli.train.ko.tsv": (
        f"{_KORNLI}/multinli.train.ko.tsv",
        "dca5bf65597af45b139a5fbc8aa3587b612b391446475617b8faa09e5dfcd349",
    ),
    "klue-nli-v1.1_train.json": (
        f"{_KLUE}/klue-nli-v1.1_train.json",
        "8d32e7e4ff97804a23f277fee8740f1341ac82e1c0c7b34f1be21952e4813996",
    ),
    "klue-nli-v1.1_dev.json": (
        f"{_KLUE}/klue-nli-v1.1_dev.json",
        "0699db82be17766b26e199864e6260443e17ec6e91d1870e876419e388f245b1",
    ),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    DATA_DIR.mkdir(exist_ok=True)
    failed = False
    for name, (url, expected) in FILES.items():
        path = DATA_DIR / name
        if not path.exists():
            print(f"Downloading {name}")
            partial = path.with_suffix(path.suffix + ".part")
            with urllib.request.urlopen(url, timeout=TIMEOUT) as response, partial.open("wb") as file:
                shutil.copyfileobj(response, file)
            partial.replace(path)
        actual = _sha256(path)
        if actual != expected:
            # Removed, so running this again downloads it afresh.
            path.unlink()
            print(f"{name}: SHA-256 mismatch (expected {expected}, got {actual}); removed it, run again", file=sys.stderr)
            failed = True
        else:
            print(f"{name}: {actual}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
