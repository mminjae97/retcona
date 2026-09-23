// Starting a Google login and checking what comes back (design doc 3.2).
//
// The browser goes to Google and returns to /auth/google/callback with a code.
// Two values made here guard that round trip, kept in sessionStorage (this tab
// only, gone when it closes) until the callback page takes them:
// - state: a random value Google hands back unchanged. A callback whose state
//   isn't the one this tab sent didn't come from a login it started (CSRF).
// - the PKCE code verifier: Google only gets its hash now; the backend sends
//   the verifier with the code, so a code intercepted on the way back is
//   useless on its own.
// Where to go afterwards rides along, so the callback page can send the user
// back where they were (the same rules as the email login, LoginPage).

import type { GoogleConfig } from "../api/auth";
import type { LoginRedirectState } from "./loginRedirect";

const STORAGE_KEY = "retcona_google_login";
const AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth";

export interface PendingGoogleLogin extends LoginRedirectState {
  state: string;
  codeVerifier: string;
}

function randomUrlSafe(bytes: number): string {
  const buffer = crypto.getRandomValues(new Uint8Array(bytes));
  return base64Url(buffer);
}

function base64Url(bytes: Uint8Array): string {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function codeChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64Url(new Uint8Array(digest));
}

// Leaves the app for Google's sign-in page. Returns false (and stays) if the
// pending login can't be remembered for the callback page to check.
export async function startGoogleLogin(
  config: Extract<GoogleConfig, { enabled: true }>,
  context: LoginRedirectState,
): Promise<boolean> {
  const pending: PendingGoogleLogin = {
    ...context,
    state: randomUrlSafe(32),
    codeVerifier: randomUrlSafe(48), // 64 characters, within PKCE's 43-128
  };
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending));
  } catch {
    return false; // storage blocked: the callback couldn't be verified
  }
  const params = new URLSearchParams({
    client_id: config.client_id,
    redirect_uri: config.redirect_uri,
    response_type: "code",
    scope: "openid email",
    state: pending.state,
    code_challenge: await codeChallenge(pending.codeVerifier),
    code_challenge_method: "S256",
    // Always ask which account, so a shared computer's last Google account
    // isn't signed in silently.
    prompt: "select_account",
  });
  window.location.assign(`${AUTHORIZE_URL}?${params}`);
  return true;
}

// The login this tab started, if the callback's state matches it. Removed
// either way: a code can only be exchanged once, and a reload of the callback
// page mustn't reuse it.
export function takePendingGoogleLogin(state: string | null): PendingGoogleLogin | null {
  let stored: string | null = null;
  try {
    stored = sessionStorage.getItem(STORAGE_KEY);
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    return null;
  }
  if (stored === null || state === null) return null;
  try {
    const pending = JSON.parse(stored) as PendingGoogleLogin;
    return pending.state === state ? pending : null;
  } catch {
    return null;
  }
}
