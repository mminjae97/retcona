"""Loads the shared pen-name rule constants (3.6) from shared/nickname-rules.json
at the repo root, hand-edited and read by both this backend (this file's
NICKNAME_RULES, used by models/user.py's column length and auth/schemas.py's
validation) and the frontend (utils/nickname.ts), so the numbers can't drift
apart independently.

Falls back to _DEFAULT (kept in sync with shared/nickname-rules.json by hand)
instead of failing to import, and validates the loaded values before trusting
them: that file sits outside what pyproject.toml's
[tool.setuptools.packages.find] packages, so it exists in a repo checkout
(how this app runs today) but not necessarily in a non-editable install (a
built wheel, or an image copying only site-packages) — and it's hand-edited,
so a typo, a missing key, or an inverted min/max shouldn't silently break
every nickname in the app or crash the API at import time.
"""

import json
from pathlib import Path

_DEFAULT = {"minLength": 2, "maxLength": 20, "maxRawLength": 200, "maxMarks": 3}


def _validated(rules: dict) -> dict | None:
    try:
        return (
            rules
            if (
                all(isinstance(rules.get(key), int) for key in _DEFAULT)
                and 0 < rules["minLength"] <= rules["maxLength"] <= rules["maxRawLength"]
                and rules["maxMarks"] >= 0
            )
            else None
        )
    except TypeError:
        return None


def _load() -> dict:
    try:
        raw = json.loads((Path(__file__).resolve().parents[2] / "shared" / "nickname-rules.json").read_text())
    except (OSError, ValueError):
        return _DEFAULT
    merged = {**_DEFAULT, **raw} if isinstance(raw, dict) else _DEFAULT
    return _validated(merged) or _DEFAULT


NICKNAME_RULES = _load()
