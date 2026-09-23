// Auth API calls (design doc 3.1, 3.2, 3.5, 3.6) — email/password signup and
// login, Google login, nickname change, account deletion request.

import { announceAccountDeleted, setUserId } from "../utils/session";
import { apiFetch, clearToken, getToken, setToken } from "./client";

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

export type GoogleConfig = { enabled: true; client_id: string; redirect_uri: string } | { enabled: false };

export function getGoogleConfig(): Promise<GoogleConfig> {
  return apiFetch<GoogleConfig>("/auth/google/config");
}

interface GoogleLoginResponse {
  status: "logged_in" | "signup_required";
  access_token: string | null;
  user: UserPublic | null;
  deletion_cancelled: boolean;
  signup_token: string | null;
  email: string | null;
}

export type GoogleLoginResult =
  | ({ status: "logged_in" } & LoginResult)
  // A Google account with no account here yet: it gets one once a nickname
  // is chosen (googleSignup), never taken from the Google profile (3.6).
  | { status: "signup_required"; signupToken: string; email: string };

export async function googleLogin(code: string, codeVerifier: string): Promise<GoogleLoginResult> {
  const res = await apiFetch<GoogleLoginResponse>("/auth/google/login", {
    method: "POST",
    body: JSON.stringify({ code, code_verifier: codeVerifier }),
  });
  if (res.status === "signup_required") {
    return { status: "signup_required", signupToken: res.signup_token!, email: res.email! };
  }
  setToken(res.access_token!, res.user!.id);
  return { status: "logged_in", user: res.user!, deletionCancelled: res.deletion_cancelled };
}

export async function googleSignup(signupToken: string, nickname: string): Promise<UserPublic> {
  const res = await apiFetch<TokenResponse>("/auth/google/signup", {
    method: "POST",
    body: JSON.stringify({ signup_token: signupToken, nickname }),
  });
  setToken(res.access_token, res.user.id);
  return res.user;
}

export function getMe(): Promise<UserPublic> {
  return apiFetch<UserPublic>("/auth/me");
}

// The id of the account the current token belongs to, for keying local drafts.
// Asked of the server rather than read from what this browser remembers: that
// is shared by every tab and may name whoever signed in last, not the account
// this tab's token is for. Also refreshes the remembered id — on every call,
// cached or not: that write is what keeps the shared "last signed in" storage
// pointing at this tab's actual account when another tab signs in as someone
// else in between (a cache hit that skipped it would leave the shared value
// wrong for as long as this tab's token stays the same).
//
// Cached by the exact token value, not just "already fetched once": the token
// is the actual credential, so unlike the remembered id above, reusing this
// cache is safe as long as the live token hasn't changed — a login elsewhere
// (this tab's own, or another tab's via shared storage) always changes it,
// which invalidates the cache instead of serving a stale account.
let cached: { token: string; userId: string } | null = null;

export async function fetchCurrentUserId(): Promise<string | null> {
  const token = getToken();
  if (token !== null && cached !== null && cached.token === token) {
    setUserId(cached.userId);
    return cached.userId;
  }
  try {
    const me = await getMe();
    setUserId(me.id);
    if (token !== null) cached = { token, userId: me.id };
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
  user_id: string;
  deletion_requested_at: string;
  purge_after: string;
}

// The backend rejects the old token as soon as the request goes through (a
// pending-deletion account is only reachable by logging in again, 3.5), so
// the stored token is dropped here rather than left to fail on the next call.
// The user was just told their data is being deleted, so unsaved manuscript
// drafts must not linger in this browser (shared machines) either: the
// response names the account the request was made for, which is the one whose
// local data goes (not whichever account happens to be remembered locally).
// Announced, not done here: clearing it is up to whoever holds it (utils/draft.ts).
export async function requestAccountDeletion(password: string): Promise<DeletionResult> {
  const result = await apiFetch<DeletionResult>("/auth/me/deletion", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  announceAccountDeleted(result.user_id);
  clearToken();
  return result;
}
