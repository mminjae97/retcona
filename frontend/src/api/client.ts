// Thin client for talking to backend/api (FastAPI), the local backend.

const BASE_URL = "/api";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

// Generic fallback for turning a caught error into user-facing Korean text.
// Callers that want per-status messages should check `err instanceof
// ApiError` themselves first and fall back to this.
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

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
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
  return await res.json();
}
