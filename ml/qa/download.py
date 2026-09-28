"""Downloads KLUE-MRC from its official repository into ml/qa/data/.

Each file is fetched from a pinned commit, so a later run gets exactly the
same data, and its SHA-256 is checked against the one recorded here.

- KLUE-MRC train/dev (KLUE-benchmark/KLUE, CC BY-SA 4.0): questions on
  Korean Wikipedia and news articles, answered by a span of the passage — or
  by none (about a third of dev), which the extractor needs as much: most
  sentences don't state the attribute asked about. KLUE doesn't publish its
  test set; dev is the evaluation set.

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

_KLUE = "https://raw.githubusercontent.com/KLUE-benchmark/KLUE/3efd98708a40ff49251fddde35453f8fbb11f536/klue_benchmark/klue-mrc-v1.1"

# local file name -> (url, sha256)
FILES = {
    "klue-mrc-v1.1_train.json": (
        f"{_KLUE}/klue-mrc-v1.1_train.json",
        "c52c7b82a6015c09ea8be1fea49c912e73012d8b44d3653256d91c65d519c3df",
    ),
    "klue-mrc-v1.1_dev.json": (
        f"{_KLUE}/klue-mrc-v1.1_dev.json",
        "b31bb073e47cdeb19f2f1bae03d916ecabf945140334c75842d6994f700d4f47",
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
