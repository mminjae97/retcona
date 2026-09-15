// Thin client for talking to backend/api (FastAPI).
// The auth token (JWE, 3.3) is sent via the Authorization header.

const BASE_URL = "/api";
const TOKEN_STORAGE_KEY = "retcona_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
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

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });
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
