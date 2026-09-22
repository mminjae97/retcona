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

// What happens to local data when the account changes is not the API layer's
// business: it announces these events, and whoever holds such data (the draft
// storage, utils/draft.ts) subscribes.
type AccountListener = (userId: string) => void;
const signedInListeners = new Set<AccountListener>();
const deletedListeners = new Set<AccountListener>();

function subscribe(listeners: Set<AccountListener>, listener: AccountListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export const onSignedIn = (listener: AccountListener): (() => void) => subscribe(signedInListeners, listener);

// A deletion request for this account has gone through.
export const onAccountDeleted = (listener: AccountListener): (() => void) => subscribe(deletedListeners, listener);

// A login or signup has succeeded: remembers the account and tells subscribers.
export function announceSignedIn(id: string): void {
  setUserId(id);
  signedInListeners.forEach((listener) => listener(id));
}

export function announceAccountDeleted(id: string): void {
  deletedListeners.forEach((listener) => listener(id));
}
