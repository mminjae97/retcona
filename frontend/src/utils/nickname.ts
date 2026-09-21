import { useRef } from "react";
import type { ChangeEvent, CompositionEvent } from "react";

// Pen name rules (design doc 3.6), mirroring the backend's `_strip_nickname`.
export const NICKNAME_MIN_LENGTH = 2;
export const NICKNAME_MAX_LENGTH = 20;

// Python's `str.strip()` whitespace set (str.isspace). JS's `trim()` differs
// from it: it also strips U+FEFF but not U+001C-U+001F or U+0085, so trimming
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

// Code points of the value that count against the cap: leading whitespace is
// stripped before the length check, so it isn't counted.
function countedLength(value: string): number {
  return Array.from(value.replace(PY_LEADING_WHITESPACE, "")).length;
}

// The text that was inserted when `prev` became `next`, located by trimming
// the common prefix and suffix, plus what surrounds it.
function splitInsertion(prev: string, next: string) {
  let head = 0;
  while (head < prev.length && head < next.length && prev[head] === next[head]) head++;
  let tail = 0;
  while (tail < prev.length - head && tail < next.length - head && prev[prev.length - 1 - tail] === next[next.length - 1 - tail]) {
    tail++;
  }
  return { before: next.slice(0, head), inserted: next.slice(head, next.length - tail), after: next.slice(next.length - tail) };
}

// Applies an edit under the length cap the way a native `maxLength` would:
// only as much of what was typed or pasted as still fits is taken, wherever in
// the value it landed — the existing text is never chopped. (`maxLength`
// itself counts UTF-16 units, which would cut emoji-heavy names short, so it
// can't be used.) Edits that don't add text always go through.
export function applyNicknameEdit(prev: string, next: string): string {
  if (countedLength(next) <= NICKNAME_MAX_LENGTH || next.length <= prev.length) return next;
  const { before, inserted, after } = splitInsertion(prev, next);
  const room = Math.max(0, NICKNAME_MAX_LENGTH - countedLength(before + after));
  return before + Array.from(inserted).slice(0, room).join("") + after;
}

// Props for a controlled nickname <input>. While an IME is composing, the
// input's value holds an uncommitted syllable, and rewriting it mid-composition
// can drop or duplicate jamo in some browsers — so the cap is applied once
// composition ends, against the value from before it started.
export function useNicknameInput(value: string, setValue: (value: string) => void) {
  const beforeComposition = useRef(value);
  return {
    onCompositionStart: () => {
      beforeComposition.current = value;
    },
    onChange: (e: ChangeEvent<HTMLInputElement>) => {
      const composing = (e.nativeEvent as InputEvent).isComposing;
      setValue(composing ? e.target.value : applyNicknameEdit(value, e.target.value));
    },
    onCompositionEnd: (e: CompositionEvent<HTMLInputElement>) =>
      setValue(applyNicknameEdit(beforeComposition.current, e.currentTarget.value)),
  };
}
