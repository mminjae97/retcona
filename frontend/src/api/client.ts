// Thin client for talking to backend/api (FastAPI).
// The auth token (JWE, 3.3) is sent via the Authorization header.

const BASE_URL = "/api";
const TOKEN_STORAGE_KEY = "retcona_token";

// Storage can be blocked (site data disabled, some private modes) and then
// throws on access. Reading treats that as "no token"; this runs while the
// module loads, where a throw would take the whole app down with it.
export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  sessionSeen = true;
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // nothing stored to clear
  }
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Generic fallback for turning a caught error into user-facing Korean text.
// Callers that want per-status messages (e.g. login's 401/409) should check
// `err instanceof ApiError` themselves first and fall back to this.
//
// Deliberately doesn't surface `err.message` for an ApiError: that's the
// backend's HTTPException detail (or a pydantic validation message), always
// in English, and would leak untranslated text into this all-Korean UI.
export function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.";
  }
  return "네트워크 오류가 발생했습니다. 잠시 후 다시 시도해주세요.";
}

// FastAPI sends `detail` as a plain string for HTTPException, but as an array
// of {msg, ...} objects for its automatic request-validation (422) errors.
function extractDetail(body: unknown): string | undefined {
  if (typeof body !== "object" || body === null || !("detail" in body)) {
    return undefined;
  }
  const detail = (body as { detail: unknown }).detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "object" && item !== null && "msg" in item ? String(item.msg) : String(item)))
      .join(" ");
  }
  return undefined;
}

// Login and signup answer 401 for a wrong password, which their own screens
// handle — every other 401 on an authenticated call means the session is over.
const AUTH_ENTRY_PATHS = ["/auth/login", "/auth/signup"];

const AUTH_EXPIRED_EVENT = "retcona:auth-expired";

export interface AuthExpiredInfo {
  // True if this page load had a session that has now ended; false for a
  // visitor who never signed in (who should still be sent to log in, but not
  // told a session "ended").
  sessionEnded: boolean;
}

// Whether this page load has ever held a token — set by setToken and by any
// request that carried one.
let sessionSeen = getToken() !== null;

// Fired when an authenticated call comes back 401: the token expired, was
// revoked (e.g. by an account-deletion request from another device, 3.5), or
// is gone altogether (another tab's session ended, or the page was reached
// again via Back after signing out).
// The API layer only announces it; the app decides how to leave the page
// (App.tsx routes to /login), so pages holding unsaved work aren't torn down
// by a hard reload behind their back.
export function onAuthExpired(listener: (info: AuthExpiredInfo) => void): () => void {
  const handler = (e: Event) => listener((e as CustomEvent<AuthExpiredInfo>).detail);
  window.addEventListener(AUTH_EXPIRED_EVENT, handler);
  return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handler);
}

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  if (token) sessionSeen = true;
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
  // Only if the stored token is still the one this request was sent with (or
  // still absent): in the meantime another tab may have logged in again, and
  // its fresh token must not be wiped — or its session bounced to /login — by
  // a stale response.
  if (res.status === 401 && token === getToken() && !AUTH_ENTRY_PATHS.includes(path)) {
    clearToken();
    window.dispatchEvent(new CustomEvent<AuthExpiredInfo>(AUTH_EXPIRED_EVENT, { detail: { sessionEnded: sessionSeen } }));
  }
  if (!res.ok) {
    const detail = await res
      .json()
      .then(extractDetail)
      .catch(() => undefined);
    throw new ApiError(res.status, detail ?? `API error: ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json();
}
