// backend/api (FastAPI)와 통신하는 얇은 클라이언트.
// 인증 토큰(JWE, 3.3)은 Authorization 헤더로 전달한다.

const BASE_URL = "/api";

export async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    throw new Error(`API error: ${res.status}`);
  }
  return res.json();
}
