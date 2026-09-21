// Login screen (design doc 3.1, 3.2)
// Email+password login, Google/Kakao/Naver social login buttons
// First-time social login signup goes to the nickname setup screen (3.2, 3.6)
import { useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { login, signup } from "../api/auth";
import type { UserPublic } from "../api/auth";
import { ApiError, describeError as describeApiError } from "../api/client";
import { getNicknameError, nicknameInputProps, stripNickname } from "../utils/nickname";
import "./LoginPage.css";

type Mode = "login" | "signup";

const SOCIAL_PROVIDERS = ["Google", "Kakao", "Naver"] as const;

// Keyed by HTTP status rather than the backend's exact message text, so a
// wording change in the API's error detail can't silently break this mapping.
const ERROR_MESSAGES_BY_STATUS: Record<number, string> = {
  401: "이메일 또는 비밀번호가 올바르지 않습니다.",
  409: "이미 가입된 이메일입니다.",
  410: "탈퇴 유예기간이 지나 삭제 예정인 계정입니다. 복구할 수 없습니다.",
  422: "입력값을 다시 확인해주세요.",
};

function describeError(err: unknown): string {
  if (err instanceof ApiError) {
    // Don't fall back to err.message here — for a status this map doesn't
    // cover (e.g. an unhandled 500), that's the raw client.ts fallback
    // string ("API error: 500"), which would leak English into this
    // all-Korean UI.
    return ERROR_MESSAGES_BY_STATUS[err.status] ?? "요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.";
  }
  return describeApiError(err);
}

// Where the user was headed when they got sent here, and whether they had a
// session that ended (both set by AuthExpiryRedirect). Only an in-app absolute
// path is honored, never anything that could leave the app.
function getRedirectState(state: unknown): { returnTo: string | null; sessionEnded: boolean; expiredUserId: string | null } {
  const { returnTo, sessionEnded, userId } = (state ?? {}) as {
    returnTo?: unknown;
    sessionEnded?: unknown;
    userId?: unknown;
  };
  const safe =
    typeof returnTo === "string" && returnTo.startsWith("/") && !returnTo.startsWith("//") && !returnTo.startsWith("/login");
  return {
    returnTo: safe ? returnTo : null,
    sessionEnded: sessionEnded === true,
    expiredUserId: typeof userId === "string" ? userId : null,
  };
}

export default function LoginPage() {
  const navigate = useNavigate();
  const { returnTo, sessionEnded, expiredUserId } = getRedirectState(useLocation().state);
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
    let signedInUser: UserPublic | null = null;
    try {
      if (mode === "signup") {
        // Validate the trimmed value, matching the backend's strip-then-check
        // rule (3.6) — the native minLength attribute checks the raw,
        // untrimmed value and would let e.g. "a " through.
        const nicknameError = getNicknameError(nickname);
        if (nicknameError) {
          setError(nicknameError);
          return;
        }
        const trimmedNickname = stripNickname(nickname);
        // Matches the backend's 72-UTF-8-byte cap (bcrypt only hashes that
        // much) — minLength={8} on the input is a floor, not a ceiling, so a
        // long multi-byte password would otherwise pass client-side checks
        // and only fail server-side with an unhelpful generic 422.
        if (new TextEncoder().encode(password).length > 72) {
          setError("비밀번호가 너무 깁니다. 72바이트 이내로 입력해주세요.");
          return;
        }
        signedInUser = await signup(email, password, trimmedNickname);
      } else {
        const { user, deletionCancelled } = await login(email, password);
        signedInUser = user;
        if (deletionCancelled) {
          window.alert("진행 중이던 회원 탈퇴가 취소되었습니다. 계정이 원래대로 복구되었어요.");
        }
      }
      // Back to the page the ended session was on, but only for that same
      // account: someone else signing in there would land on a page that isn't theirs.
      // If a session had ended but whose is unknown (it began before the id was
      // remembered), it isn't taken back either.
      const sameAccount = !sessionEnded || (expiredUserId !== null && signedInUser?.id === expiredUserId);
      navigate(sameAccount ? (returnTo ?? "/") : "/");
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
              {...nicknameInputProps(setNickname)}
              required
            />
          </label>
        )}

        {sessionEnded && (
          <p className="login-notice">
            로그인 세션이 종료되었습니다.{returnTo !== null && " 같은 계정으로 다시 로그인하면 하던 작업으로 돌아갑니다."}
          </p>
        )}

        {error && <p className="login-error">{error}</p>}

        <button type="submit" disabled={submitting}>
          {submitting ? "처리 중..." : mode === "signup" ? "가입하기" : "로그인"}
        </button>

        <div className="login-divider">또는</div>

        <div className="social-login-buttons">
          {SOCIAL_PROVIDERS.map((provider) => (
            <button key={provider} type="button" disabled title="소셜 로그인은 준비 중입니다">
              {provider}로 계속하기
            </button>
          ))}
        </div>
      </form>
    </div>
  );
}
