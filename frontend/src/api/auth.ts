// Auth API calls (design doc 3.1) — email/password signup and login.

import { apiFetch, setToken } from "./client";

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
