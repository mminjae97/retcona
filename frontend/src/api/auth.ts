// Auth API calls (design doc 3.1, 3.5, 3.6) — email/password signup and login,
// nickname change, account deletion request.

import { apiFetch, clearToken, setToken } from "./client";

export interface UserPublic {
  id: string;
  email: string;
  nickname: string;
}

interface TokenResponse {
  access_token: string;
  token_type: string;
  user: UserPublic;
}

export async function signup(email: string, password: string, nickname: string): Promise<UserPublic> {
  const res = await apiFetch<TokenResponse>("/auth/signup", {
    method: "POST",
    body: JSON.stringify({ email, password, nickname }),
  });
  setToken(res.access_token);
  return res.user;
}

export async function login(email: string, password: string): Promise<UserPublic> {
  const res = await apiFetch<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(res.access_token);
  return res.user;
}

export function getMe(): Promise<UserPublic> {
  return apiFetch<UserPublic>("/auth/me");
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
export async function requestAccountDeletion(password: string): Promise<DeletionResult> {
  const result = await apiFetch<DeletionResult>("/auth/me/deletion", {
    method: "POST",
    body: JSON.stringify({ password }),
  });
  clearToken();
  return result;
}
