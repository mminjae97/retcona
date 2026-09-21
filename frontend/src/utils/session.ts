// Which account this browser last signed in as. Local drafts are stored per
// account (utils/draft.ts), and the token itself is opaque to the client, so the
// id is remembered next to it at login.
//
// Deliberately NOT cleared when the session ends: an editor still open flushes
// its pending text as it unmounts after the 401, and that text belongs to the
// account that was signed in, not to whoever signs in next. The next login
// overwrites it.

import { persistedValue } from "./safeStorage";

const userId = persistedValue("retcona_user_id");

export const getUserId = (): string | null => userId.get();

export const setUserId = (id: string): void => userId.set(id);
