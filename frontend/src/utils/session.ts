// Which account this browser last signed in as. Local drafts are stored per
// account (utils/draft.ts), and the token itself is opaque to the client, so the
// id is remembered next to it at login.
//
// Deliberately NOT cleared when the session ends: an editor still open flushes
// its pending text as it unmounts after the 401, and that text belongs to the
// account that was signed in, not to whoever signs in next. The next login
// overwrites it.

const USER_ID_STORAGE_KEY = "retcona_user_id";

// Only holds the id when storage refused the write; see getToken() in api/client.ts.
let memoryUserId: string | null = null;

export function getUserId(): string | null {
  if (memoryUserId !== null) return memoryUserId;
  try {
    return localStorage.getItem(USER_ID_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setUserId(userId: string): void {
  try {
    localStorage.setItem(USER_ID_STORAGE_KEY, userId);
    memoryUserId = null;
  } catch {
    memoryUserId = userId;
  }
}
