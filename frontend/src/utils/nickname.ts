import type { ChangeEvent, CompositionEvent } from "react";

// Pen name rules (design doc 3.6), mirroring the backend's `_strip_nickname`.
export const NICKNAME_MIN_LENGTH = 2;
export const NICKNAME_MAX_LENGTH = 20;

// Python's `str.strip()` whitespace set (str.isspace). JS's `trim()` differs
// from it: it also strips U+FEFF but not U+001C-U+001F or U+0085, so trimming
// with `trim()` could pass a value the backend then shortens below the minimum.
const PY_WHITESPACE = "\t-\r\x1c-\x20\x85\xa0  -     　";
const PY_STRIP = new RegExp(`^[${PY_WHITESPACE}]+|[${PY_WHITESPACE}]+$`, "g");

export function stripNickname(value: string): string {
  return value.replace(PY_STRIP, "");
}

// What a pen name may contain: letters, combining marks, numbers, punctuation,
// spaces and math/currency/modifier symbols, from the Basic Multilingual Plane
// only. That leaves out emoji and other pictographs (category "other symbol",
// or outside the BMP), format and control characters (zero-width joiner,
// zero-width space, NUL) and rare astral characters. The backend applies the
// same rule by Unicode category. (Checked against it over every code point:
// the only differences are characters so new that the server's Python doesn't
// know them yet and rejects them, where this accepts them.)
//
// Every allowed character is a single UTF-16 unit, so `String.length` here is
// the same count as the backend's `len()` and the input's native `maxLength`
// is exact — no code-point bookkeeping needed.
const DISALLOWED_SOURCE = String.raw`[^\p{L}\p{Mn}\p{Mc}\p{N}\p{P}\p{Zs}\p{Sm}\p{Sc}\p{Sk}]|[\u{10000}-\u{10FFFF}]`;
const DISALLOWED_ALL = new RegExp(DISALLOWED_SOURCE, "gu");
const DISALLOWED_ANY = new RegExp(DISALLOWED_SOURCE, "u");

export function sanitizeNickname(value: string): string {
  return value.replace(DISALLOWED_ALL, "");
}

// The message to show for a nickname that can't be submitted, or null if it's fine.
export function getNicknameError(value: string): string | null {
  const stripped = stripNickname(value);
  if (DISALLOWED_ANY.test(stripped)) return "필명에는 이모지나 특수 기호를 쓸 수 없습니다.";
  if (stripped.length < NICKNAME_MIN_LENGTH || stripped.length > NICKNAME_MAX_LENGTH) {
    return "필명은 공백을 제외하고 2~20자로 입력해주세요.";
  }
  return null;
}

// Props for a controlled nickname <input>: characters that aren't allowed
// (typed with an emoji keyboard, or pasted) are dropped as they arrive. While
// an IME is composing, the input's value holds an uncommitted syllable and
// rewriting it can drop or duplicate jamo in some browsers, so it's cleaned
// when composition ends instead. Length is left to the input's own `maxLength`.
export function nicknameInputProps(setValue: (value: string) => void) {
  return {
    maxLength: NICKNAME_MAX_LENGTH,
    onChange: (e: ChangeEvent<HTMLInputElement>) => {
      const composing = (e.nativeEvent as InputEvent).isComposing;
      setValue(composing ? e.target.value : sanitizeNickname(e.target.value));
    },
    onCompositionEnd: (e: CompositionEvent<HTMLInputElement>) => setValue(sanitizeNickname(e.currentTarget.value)),
  };
}
