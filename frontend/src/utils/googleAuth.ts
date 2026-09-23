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

// What the round trip to Google is for: signing in, or confirming a Google
// account's deletion (3.5 — the re-authentication a password is for an email
// account). The callback page does the one this tab asked for.
export type GooglePurpose = "login" | "delete-account";

export interface PendingGoogleLogin extends LoginRedirectState {
  state: string;
  codeVerifier: string;
  purpose: GooglePurpose;
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

// Why a Google login couldn't start (the page stays where it is):
// - wrong-origin: this page isn't on the origin Google sends the browser back
//   to (the configured redirect URI's), so the callback page there couldn't
//   read what's saved here — sessionStorage is per origin. `origin` is where
//   to open the app instead.
// - insecure: the page isn't a secure context (plain http on anything but
//   localhost), where the browser offers no crypto.subtle for PKCE.
// - storage: sessionStorage is blocked.
// - config: the redirect URI the server gave isn't a URL the browser accepts.
export type GoogleLoginStartFailure =
  | { reason: "wrong-origin"; origin: string }
  | { reason: "insecure" }
  | { reason: "storage" }
  | { reason: "config" };

// Leaves the app for Google's sign-in page, or says why it can't. Never
// throws, and saves nothing unless it's actually leaving.
export async function startGoogleLogin(
  config: Extract<GoogleConfig, { enabled: true }>,
  context: LoginRedirectState,
  purpose: GooglePurpose = "login",
): Promise<GoogleLoginStartFailure | null> {
  let callbackOrigin: string;
  try {
    callbackOrigin = new URL(config.redirect_uri).origin;
  } catch {
    // The backend checks the setting too, but it can't catch every value
    // the browser's URL parser rejects (an out-of-range port, say).
    return { reason: "config" };
  }
  if (callbackOrigin !== window.location.origin) {
    return { reason: "wrong-origin", origin: callbackOrigin };
  }
  const pending: PendingGoogleLogin = {
    ...context,
    purpose,
    state: randomUrlSafe(32),
    codeVerifier: randomUrlSafe(48), // 64 characters, within PKCE's 43-128
  };
  let challenge: string;
  try {
    challenge = await codeChallenge(pending.codeVerifier);
  } catch {
    return { reason: "insecure" }; // crypto.subtle is undefined outside a secure context
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pending));
  } catch {
    return { reason: "storage" }; // the callback couldn't be verified
  }
  const params = new URLSearchParams({
    client_id: config.client_id,
    redirect_uri: config.redirect_uri,
    response_type: "code",
    scope: "openid email",
    state: pending.state,
    code_challenge: challenge,
    code_challenge_method: "S256",
    // Always ask which account, so a shared computer's last Google account
    // isn't signed in silently.
    prompt: "select_account",
  });
  window.location.assign(`${AUTHORIZE_URL}?${params}`);
  return null;
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

// What to tell the user when startGoogleLogin couldn't leave for Google.
export function describeGoogleStartFailure(failure: GoogleLoginStartFailure): string {
  switch (failure.reason) {
    case "wrong-origin":
      return `구글 로그인은 ${failure.origin} 주소에서 사용할 수 있습니다. 이 주소로 접속해 다시 시도해주세요.`;
    case "insecure":
      return "구글 로그인은 HTTPS 또는 localhost 주소에서만 사용할 수 있습니다.";
    case "storage":
      return "브라우저 저장소를 사용할 수 없어 구글 로그인을 시작할 수 없습니다.";
    default:
      return "구글 로그인 설정에 문제가 있어 시작할 수 없습니다. 관리자에게 문의해주세요.";
  }
}
