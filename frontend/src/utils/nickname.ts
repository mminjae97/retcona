// Pen name rules (design doc 3.6), mirroring the backend's `_strip_nickname`.
export const NICKNAME_MIN_LENGTH = 2;
export const NICKNAME_MAX_LENGTH = 20;

// Python's `str.strip()` whitespace set (str.isspace). JS's `trim()` differs
// from it — it also strips U+FEFF but not - or  — so trimming
// with `trim()` could pass a value the backend then shortens below the minimum.
const PY_WHITESPACE = "\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000";
const PY_STRIP = new RegExp(`^[${PY_WHITESPACE}]+|[${PY_WHITESPACE}]+$`, "g");

export function stripNickname(value: string): string {
  return value.replace(PY_STRIP, "");
}

// Counts Unicode code points (what the backend's `len()` counts), not the
// UTF-16 units of `String.length` — an emoji or a rare hanja like 𠮷 is one
// character to the author and to the backend, but length 2 in JS.
export function nicknameLength(value: string): number {
  return Array.from(stripNickname(value)).length;
}

export function isValidNickname(value: string): boolean {
  const length = nicknameLength(value);
  return length >= NICKNAME_MIN_LENGTH && length <= NICKNAME_MAX_LENGTH;
}

// Hard cap for the input field, in code points (an `<input maxLength>` counts
// UTF-16 units instead, which would cut emoji-heavy names short).
export function clampNickname(value: string): string {
  return Array.from(value).slice(0, NICKNAME_MAX_LENGTH).join("");
}
