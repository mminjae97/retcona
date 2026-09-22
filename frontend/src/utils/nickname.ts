import type { ChangeEvent, CompositionEvent } from "react";
import nicknameRules from "../../../shared/nickname-rules.json";

// Pen name rules (design doc 3.6), mirroring the backend's `_strip_nickname`.
// The numbers themselves come from ../../../shared/nickname-rules.json, read
// by both sides, so they can't drift apart independently — the character-class
// check below still can't be shared this way (a regex here vs. Python's
// unicodedata.category() there are different engines) and stays hand-kept in
// sync, cross-checked over every code point.
export const NICKNAME_MIN_LENGTH = nicknameRules.minLength;
export const NICKNAME_MAX_LENGTH = nicknameRules.maxLength;
// What the input itself accepts, before NFC and strip: the backend's raw cap.
// The 20 limit applies to the normalized text, which can be a third of the raw
// length (decomposed Hangul), so cutting the raw text at 20 would truncate a
// pasted name without any message.
const NICKNAME_MAX_RAW_LENGTH = nicknameRules.maxRawLength;

// Python's `str.strip()` whitespace set (str.isspace). JS's `trim()` differs
// from it: it also strips U+FEFF but not U+001C-U+001F or U+0085, so trimming
// with `trim()` could pass a value the backend then shortens below the minimum.
const PY_WHITESPACE = "\t-\r\x1c-\x20\x85\xa0  -     　";
const PY_STRIP = new RegExp(`^[${PY_WHITESPACE}]+|[${PY_WHITESPACE}]+$`, "g");

// NFC first, like the backend: the same visible name can arrive decomposed
// (Hangul as separate jamo, letters with combining accents) depending on the
// IME or where it was pasted from, and length is counted on the composed form.
export function stripNickname(value: string): string {
  return value.normalize("NFC").replace(PY_STRIP, "");
}

// What a pen name may contain: letters, numbers, combining marks and the
// ordinary space, from the Basic Multilingual Plane only. Everything else is
// out: emoji and other pictographs, punctuation and symbols, other kinds of
// space, format and control characters (zero-width joiner, NUL, ...) and rare
// astral characters — plus a few letters/marks that render as nothing
// (fillers, joiners, variation selectors). The backend applies the same rule
// by Unicode category. (Checked against it over every code point: the only
// differences are characters so new that the server's Python doesn't know
// them yet and rejects them, where this accepts them.)
//
// Every allowed character is a single UTF-16 unit, so `String.length` here is
// the same count as the backend's `len()` — no code-point bookkeeping needed.
const DISALLOWED_SOURCE = String.raw`[^\p{L}\p{N}\p{Mn}\p{Mc} ]|[\u{10000}-\u{10FFFF}]|[\u034F\u115F\u1160\u17B4\u17B5\u180B-\u180D\u180F\u3164\uFFA0\uFE00-\uFE0F]`;
const DISALLOWED_ALL = new RegExp(DISALLOWED_SOURCE, "gu");
const DISALLOWED_ANY = new RegExp(DISALLOWED_SOURCE, "u");
const HAS_LETTER_OR_NUMBER = /[\p{L}\p{N}]/u;
// A run of more than MAX_MARKS combining marks (zalgo-style stacking), or a
// mark with nothing to attach to (at the start, or right after a space).
const MAX_MARKS = nicknameRules.maxMarks;
const BAD_MARKS = new RegExp(`[\\p{Mn}\\p{Mc}]{${MAX_MARKS + 1},}|(?:^| )[\\p{Mn}\\p{Mc}]`, "u");

export const NICKNAME_HINT = "글자·숫자·공백만, 2~20자";

export function sanitizeNickname(value: string): string {
  return value.replace(DISALLOWED_ALL, "");
}

// The message to show for a nickname that can't be submitted, or null if it's fine.
export function getNicknameError(value: string): string | null {
  const stripped = stripNickname(value);
  const lengthMessage = "필명은 공백을 제외하고 2~20자로 입력해주세요.";
  // Nothing typed (or only spaces): a length problem, not a character problem.
  if (stripped.length === 0) return lengthMessage;
  if (DISALLOWED_ANY.test(stripped) || !HAS_LETTER_OR_NUMBER.test(stripped) || BAD_MARKS.test(stripped)) {
    return "필명에는 글자·숫자·공백만 쓸 수 있습니다. 이모지와 특수 기호는 사용할 수 없습니다.";
  }
  if (stripped.length < NICKNAME_MIN_LENGTH || stripped.length > NICKNAME_MAX_LENGTH) return lengthMessage;
  return null;
}

// Writes the cleaned value back. When something was dropped from the middle of
// the text, React's rewrite of the input's value would send the caret to the
// end, so it is put back where it was (minus what was dropped before it).
function cleanInput(input: HTMLInputElement, setValue: (value: string) => void): void {
  const raw = input.value;
  const clean = sanitizeNickname(raw);
  setValue(clean);
  if (clean === raw) return;
  const caret = sanitizeNickname(raw.slice(0, input.selectionStart ?? raw.length)).length;
  // After React has rendered the new value.
  requestAnimationFrame(() => {
    if (input.isConnected && document.activeElement === input) input.setSelectionRange(caret, caret);
  });
}

// Props for a controlled nickname <input>: characters that aren't allowed
// (symbols, or emoji from an emoji keyboard or a paste) are dropped as they arrive. While
// an IME is composing, the input's value holds an uncommitted syllable and
// rewriting it can drop or duplicate jamo in some browsers, so it's cleaned
// when composition ends instead. Length is left to `getNicknameError` (the input's
// `maxLength` is only the raw cap).
export function nicknameInputProps(setValue: (value: string) => void) {
  return {
    maxLength: NICKNAME_MAX_RAW_LENGTH,
    placeholder: NICKNAME_HINT,
    onChange: (e: ChangeEvent<HTMLInputElement>) => {
      const composing = (e.nativeEvent as InputEvent).isComposing;
      if (composing) setValue(e.target.value);
      else cleanInput(e.target, setValue);
    },
    onCompositionEnd: (e: CompositionEvent<HTMLInputElement>) => cleanInput(e.currentTarget, setValue),
  };
}
