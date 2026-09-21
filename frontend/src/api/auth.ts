// Auth API calls (design doc 3.1, 3.5, 3.6) — email/password signup and login,
// nickname change, account deletion request.

import { discardDraftsForDeletion } from "../utils/draft";
import { getUserId, setUserId } from "../utils/session";
import { apiFetch, clearToken, setToken } from "./client";

export interface UserPublic {
  id: string;
  email: string;
  nickname: string;
  // False for social-login accounts, which can't confirm deletion with a password (3.5).
  has_password: boolean;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserPublic;
  deletion_cancelled: boolean;
}

export async function signup(email: string, password: string, nickname: string): Promise<UserPublic> {
  const res = await apiFetch<TokenResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, nickname }),
  });
  setToken(res.access_token, res.user.id);
  return res.user;
}

export interface LoginResult {
  user: UserPublic;
  // True when this login cancelled a pending account deletion (3.5) —
  // callers should tell the user, since it happens without them asking.
  deletionCancelled: boolean;
}

export async function login(email: string, password: string): Promise<LoginResult> {
  const res = await apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(res.access_token, res.user.id);
  return { user: res.user, deletionCancelled: res.deletion_cancelled };
}

export function getMe(): Promise<UserPublic> {
  return apiFetch<UserPublic>("/auth/me");
}

// The account's id for keying local drafts. Remembered at login; a session that
// predates that (signed in before the id was stored) fetches it once.
export async function ensureUserId(): Promise<string | null> {
  const stored = getUserId();
  if (stored !== null) return stored;
  try {
    const me = await getMe();
    setUserId(me.id);
    return me.id;
  } catch {
    return null; // drafts are simply off for this load
  }
}

export function updateNickname(nickname: string): Promise<UserPublic> {
  return apiFetch<UserPublic>("/auth/me", {
    method: "PATCH",
    body: JSON.stringify({ nickname }),
  });
}

export interface DeletionResult {
  deletion_requested_at: string;
  purge_after: string;
}

// The backend rejects the old token as soon as the request goes through (a
// pending-deletion account is only reachable by logging in again, 3.5), so
// the stored token is dropped here rather than left to fail on the next call.
// The user was just told their data is being deleted, so unsaved manuscript
// drafts must not linger in this browser (shared machines) either.
export async function requestAccountDeletion(password: string): Promise<DeletionResult> {
  // Needed to wipe this account's drafts afterwards, and only obtainable while
  // the token still works: a session from before the id was remembered has to
  // fetch it now rather than after the request revokes the token.
  const userId = await ensureUserId();
  // Without it the drafts can't be wiped, and the user is about to be told
  // their data is being deleted: don't start what can't be finished.
  if (userId === null) throw new Error("Could not determine the account id");
  const result = await apiFetch<DeletionResult>("/auth/me/deletion", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  discardDraftsForDeletion(userId);
  clearToken();
  return result;
}
