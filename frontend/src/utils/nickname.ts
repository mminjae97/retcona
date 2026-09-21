import type { ChangeEvent, CompositionEvent } from "react";

// Pen name rules (design doc 3.6), mirroring the backend's `_strip_nickname`.
export const NICKNAME_MIN_LENGTH = 2;
export const NICKNAME_MAX_LENGTH = 20;

// Python's `str.strip()` whitespace set (str.isspace). JS's `trim()` differs
// from it — it also strips U+FEFF but not - or  — so trimming
// with `trim()` could pass a value the backend then shortens below the minimum.
const PY_WHITESPACE = "\t-\r\x1c-\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000";
const PY_STRIP = new RegExp(`^[${PY_WHITESPACE}]+|[${PY_WHITESPACE}]+$`, "g");
const PY_LEADING_WHITESPACE = new RegExp(`^[${PY_WHITESPACE}]+`);

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
// UTF-16 units instead, which would cut emoji-heavy names short). Leading
// whitespace doesn't count against it, since it's stripped before the
// length check — pasting "   name" must not lose the end of "name".
export function clampNickname(value: string): string {
  const leading = PY_LEADING_WHITESPACE.exec(value)?.[0] ?? "";
  const rest = Array.from(value.slice(leading.length));
  return rest.length <= NICKNAME_MAX_LENGTH ? value : leading + rest.slice(0, NICKNAME_MAX_LENGTH).join("");
}

// Props for a controlled nickname <input>. While an IME is composing, the
// input's value holds an uncommitted syllable, and rewriting it mid-composition
// can drop or duplicate jamo in some browsers — so the cap is applied when
// composition ends instead.
export function nicknameInputHandlers(setValue: (value: string) => void) {
  return {
    onChange: (e: ChangeEvent<HTMLInputElement>) => {
      const composing = (e.nativeEvent as InputEvent).isComposing;
      setValue(composing ? e.target.value : clampNickname(e.target.value));
    },
    onCompositionEnd: (e: CompositionEvent<HTMLInputElement>) => setValue(clampNickname(e.currentTarget.value)),
  };
}
