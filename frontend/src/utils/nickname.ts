// Pen name rules (design doc 3.6), mirroring the backend's `_strip_nickname`.
export const NICKNAME_MIN_LENGTH = 2;
export const NICKNAME_MAX_LENGTH = 20;

// Counts Unicode code points (what the backend's `len()` counts), not the
// UTF-16 units of `String.length` — an emoji or a rare hanja like 𠮷 is one
// character to the author and to the backend, but length 2 in JS.
export function nicknameLength(value: string): number {
  return Array.from(value.trim()).length;
}

export function isValidNickname(value: string): boolean {
  const length = nicknameLength(value);
  return length >= NICKNAME_MIN_LENGTH && length <= NICKNAME_MAX_LENGTH;
}
