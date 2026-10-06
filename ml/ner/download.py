"""Downloads KLUE-NER from its official repository into ml/ner/data/.

Each file is fetched from a pinned commit, so a later run gets exactly the
same data, and its SHA-256 is checked against the one recorded here.

- KLUE-NER train/dev (KLUE-benchmark/KLUE, CC BY-SA 4.0): Korean news
  (WIKITREE) and movie reviews (NSMC), tagged per character (PS person, LC
  location, OG organization, DT date, TI time, QT quantity). KLUE doesn't
  publish its test set; dev is the evaluation set.

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

_KLUE = "https://raw.githubusercontent.com/KLUE-benchmark/KLUE/3efd98708a40ff49251fddde35453f8fbb11f536/klue_benchmark/klue-ner-v1.1"

# local file name -> (url, sha256)
FILES = {
    "klue-ner-v1.1_train.tsv": (
        f"{_KLUE}/klue-ner-v1.1_train.tsv",
        "34b9d3d9f9ce9e064abc6ba4c27af43b4b70f2d6cde62c076a28e8aaa17cc544",
    ),
    "klue-ner-v1.1_dev.tsv": (
        f"{_KLUE}/klue-ner-v1.1_dev.tsv",
        "0f4d5e818f7b82d299c3a87856fc40a706f5943207580ddb252397e387050a54",
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
