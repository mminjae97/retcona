// Login screen (design doc 3.1, 3.2)
// Email+password login, Google/Kakao/Naver social login buttons
// First-time social login signup goes to the nickname setup screen (3.2, 3.6)
import { useState } from "react";
import type { FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { login, signup } from "../api/auth";
import { ApiError, describeError as describeApiError } from "../api/client";
import "./LoginPage.css";

type Mode = "login" | "signup";

// Keyed by HTTP status rather than the backend's exact message text, so a
// wording change in the API's error detail can't silently break this mapping.
const ERROR_MESSAGES_BY_STATUS: Record<number, string> = {
  401: "이메일 또는 비밀번호가 올바르지 않습니다.",
  409: "이미 가입된 이메일입니다.",
  422: "입력값을 다시 확인해주세요.",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    return ERROR_MESSAGES_BY_STATUS[err.status] ?? err.message;
  }
  return describeApiError(err);
}

export default function LoginPage() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      if (mode === "signup") {
        await signup(email, password, nickname);
      } else {
        await login(email, password);
      }
      navigate("/");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={handleSubmit}>
        <h1>Retcona</h1>

        <div className="login-tabs">
          <button type="button" className={mode === "login" ? "active" : ""} onClick={() => switchMode("login")}>
            로그인
          </button>
          <button type="button" className={mode === "signup" ? "active" : ""} onClick={() => switchMode("signup")}>
            회원가입
          </button>
        </div>

        <label>
          이메일
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        </label>

        <label>
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete={mode === "signup" ? "new-password" : "current-password"}
          />
        </label>

        {mode === "signup" && (
          <label>
            필명(닉네임)
            <input
              type="text"
              value={nickname}
              onChange={(e) => setNickname(e.target.value)}
              required
              minLength={2}
              maxLength={20}
            />
          </label>
        )}

        {error && <p className="login-error">{error}</p>}

        <button type="submit" disabled={submitting}>
          {submitting ? "처리 중..." : mode === "signup" ? "가입하기" : "로그인"}
        </button>

        <div className="login-divider">또는</div>

        <div className="social-login-buttons">
          <button type="button" disabled title="소셜 로그인은 준비 중입니다">
            Google로 계속하기
          </button>
          <button type="button" disabled title="소셜 로그인은 준비 중입니다">
            Kakao로 계속하기
          </button>
          <button type="button" disabled title="소셜 로그인은 준비 중입니다">
            Naver로 계속하기
          </button>
        </div>
      </form>
    </div>
  );
}
