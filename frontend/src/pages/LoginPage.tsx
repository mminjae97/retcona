// Login screen (design doc 3.1, 3.2)
// Email+password login, and the Google login button (the only social login)
// First-time Google signup goes to the nickname setup screen (3.2, 3.6), on the callback page
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { getGoogleConfig, login, requestSignupCode, signup, verifySignupCode } from "../api/auth";
import type { GoogleConfig, UserPublic } from "../api/auth";
import { ApiError, describeError as describeApiError } from "../api/client";
import { describeGoogleStartFailure, startGoogleLogin } from "../utils/googleAuth";
import type { GoogleLoginStartFailure } from "../utils/googleAuth";
import { destinationAfterLogin, getRedirectState } from "../utils/loginRedirect";
import { getNicknameError, nicknameInputProps, stripNickname } from "../utils/nickname";
import "./LoginPage.css";

type Mode = "login" | "signup";

// Keyed by HTTP status rather than the backend's exact message text, so a
// wording change in the API's error detail can't silently break this mapping.
const ERROR_MESSAGES_BY_STATUS: Record<number, string> = {
  401: "이메일 또는 비밀번호가 올바르지 않습니다.",
  409: "이미 가입된 이메일입니다.",
  410: "탈퇴 유예기간이 지나 삭제 예정인 계정입니다. 복구할 수 없습니다.",
  422: "입력값을 다시 확인해주세요.",
};

// Signup email verification (3.1).
const CODE_REQUEST_ERRORS: Record<number, string> = {
  409: "이미 가입된 이메일입니다.",
  422: "이메일 형식을 확인해주세요.",
  429: "인증번호를 너무 자주 요청했습니다. 잠시 후 다시 시도해주세요.",
  502: "인증 메일을 보내지 못했습니다. 잠시 후 다시 시도해주세요.",
};
const CODE_VERIFY_ERRORS: Record<number, string> = {
  400: "인증번호가 올바르지 않습니다.",
  410: "인증번호가 만료되었습니다. 인증번호를 다시 받아주세요.",
  422: "6자리 숫자를 입력해주세요.",
  429: "인증번호를 여러 번 틀렸습니다. 인증번호를 다시 받아주세요.",
};

function describeByStatus(err: unknown, byStatus: Record<number, string>): string {
  if (err instanceof ApiError && byStatus[err.status]) return byStatus[err.status];
  return describeApiError(err);
}

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

export default function LoginPage() {
  const navigate = useNavigate();
  const redirect = getRedirectState(useLocation().state);
  const { returnTo, sessionEnded, expiredUserId } = redirect;
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Signup email verification. Each record says which address it's for, and
  // only counts while that's still the address in the field: a code sent (and
  // when another may be) and a verification earned are for the address they
  // were requested for. So editing the email — here, in the login tab, or
  // while a request is still in flight — can't carry them over to another
  // address, and going back to the first address brings them back.
  const [codeSentTo, setCodeSentTo] = useState<string | null>(null);
  // How long a code stays valid, as the server says (CODE_TTL).
  const [codeValidMinutes, setCodeValidMinutes] = useState(5);
  const [resendWait, setResendWait] = useState<{ email: string; until: number } | null>(null);
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState<{ email: string; token: string } | null>(null);
  const [sendingCode, setSendingCode] = useState(false);
  const [verifying, setVerifying] = useState(false);
  const [emailStepError, setEmailStepError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  // As the backend normalizes it (auth/schemas.py lowercases emails).
  const currentEmail = email.trim().toLowerCase();
  const codeSent = codeSentTo === currentEmail;
  const verificationToken = verified?.email === currentEmail ? verified.token : null;
  const resendIn =
    resendWait?.email === currentEmail ? Math.max(0, Math.ceil((resendWait.until - now) / 1000)) : 0;

  useEffect(() => {
    if (resendIn === 0) return;
    const timer = window.setTimeout(() => setNow(Date.now()), 1000);
    return () => window.clearTimeout(timer);
  }, [resendIn, now]);

  // After the server turned the verification down (it ran out): start over.
  function resetVerification() {
    setCodeSentTo(null);
    setVerified(null);
    setCode("");
    setEmailStepError(null);
  }

  function handleEmailChange(value: string) {
    setEmail(value);
    // The code typed and any message were about the previous address.
    setCode("");
    setEmailStepError(null);
  }

  async function handleRequestCode() {
    if (sendingCode || resendIn > 0) return;
    const target = currentEmail;
    if (!target) {
      setEmailStepError("이메일을 입력해주세요.");
      return;
    }
    setSendingCode(true);
    setEmailStepError(null);
    try {
      const sent = await requestSignupCode(target);
      setCodeSentTo(target);
      setCodeValidMinutes(Math.max(1, Math.round(sent.expires_in / 60)));
      setCode("");
      setResendWait({ email: target, until: Date.now() + sent.resend_after * 1000 });
      setNow(Date.now());
    } catch (err) {
      setEmailStepError(describeByStatus(err, CODE_REQUEST_ERRORS));
    } finally {
      setSendingCode(false);
    }
  }

  async function handleVerifyCode() {
    if (verifying) return;
    if (!/^[0-9]{6}$/.test(code)) {
      setEmailStepError("6자리 숫자를 입력해주세요.");
      return;
    }
    const target = currentEmail;
    setVerifying(true);
    setEmailStepError(null);
    try {
      const token = await verifySignupCode(target, code);
      setVerified({ email: target, token });
    } catch (err) {
      setEmailStepError(describeByStatus(err, CODE_VERIFY_ERRORS));
    } finally {
      setVerifying(false);
    }
  }
  // null until known; the button stays disabled if it can't be loaded or
  // Google login isn't configured on the server.
  const [googleConfig, setGoogleConfig] = useState<GoogleConfig | null>(null);
  const [leavingForGoogle, setLeavingForGoogle] = useState(false);

  useEffect(() => {
    let active = true;
    getGoogleConfig()
      .then((config) => active && setGoogleConfig(config))
      .catch(() => active && setGoogleConfig({ enabled: false }));
    return () => {
      active = false;
    };
  }, []);

  async function handleGoogle() {
    if (!googleConfig?.enabled || leavingForGoogle) return;
    setError(null);
    setLeavingForGoogle(true);
    let failure: GoogleLoginStartFailure | null;
    try {
      failure = await startGoogleLogin(googleConfig, redirect);
    } catch {
      // It isn't meant to throw; whatever did, the button mustn't stay stuck.
      failure = { reason: "config" };
    }
    if (failure === null) return; // on its way to Google
    setLeavingForGoogle(false);
    setError(describeGoogleStartFailure(failure));
  }

  function switchMode(next: Mode) {
    setMode(next);
    setError(null);
    setEmailStepError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    let signedInUser: UserPublic | null = null;
    try {
      if (mode === "signup") {
        if (verificationToken === null) {
          setError("이메일 인증을 먼저 완료해주세요.");
          return;
        }
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
        try {
          signedInUser = await signup(email, password, trimmedNickname, verificationToken);
        } catch (err) {
          if (err instanceof ApiError && err.status === 403) {
            // The verification ran out (30 minutes) before the form was sent.
            resetVerification();
            setError("이메일 인증 시간이 지났습니다. 인증번호를 다시 받아주세요.");
            return;
          }
          throw err;
        }
      } else {
        const { user, deletionCancelled } = await login(email, password);
        signedInUser = user;
        if (deletionCancelled) {
          window.alert("진행 중이던 회원 탈퇴가 취소되었습니다. 계정이 원래대로 복구되었어요.");
        }
      }
      navigate(destinationAfterLogin(redirect, signedInUser?.id ?? null));
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

        {/* A field with a button next to its input: the <label> is tied to the
            input with htmlFor rather than wrapping the row, or the button's
            text would become part of the input's accessible name. */}
        <div className="login-field">
          <label htmlFor="login-email">이메일</label>
          {mode === "signup" ? (
            <div className="email-row">
              <input
                id="login-email"
                type="email"
                value={email}
                onChange={(e) => handleEmailChange(e.target.value)}
                required
                autoComplete="email"
              />
              {verificationToken === null ? (
                <button type="button" onClick={handleRequestCode} disabled={sendingCode || resendIn > 0}>
                  {sendingCode ? "보내는 중..." : resendIn > 0 ? `재전송 (${resendIn}초)` : codeSent ? "재전송" : "인증번호 받기"}
                </button>
              ) : (
                <span className="verified-badge">인증 완료</span>
              )}
            </div>
          ) : (
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(e) => handleEmailChange(e.target.value)}
              required
              autoComplete="email"
            />
          )}
        </div>

        {mode === "signup" && codeSent && verificationToken === null && (
          <div className="login-field">
            <label htmlFor="signup-code">인증번호</label>
            <div className="email-row">
              <input
                id="signup-code"
                aria-describedby="signup-code-hint"
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, ""))}
                onKeyDown={(e) => {
                  // Enter checks the code instead of submitting the whole form.
                  if (e.key === "Enter") {
                    e.preventDefault();
                    handleVerifyCode();
                  }
                }}
                autoFocus
              />
              <button type="button" onClick={handleVerifyCode} disabled={verifying}>
                {verifying ? "확인 중..." : "확인"}
              </button>
            </div>
            <span className="field-hint" id="signup-code-hint">
              메일로 받은 6자리 인증번호를 {codeValidMinutes}분 안에 입력해주세요.
            </span>
          </div>
        )}

        {mode === "signup" && emailStepError && <p className="login-error">{emailStepError}</p>}

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
            로그인 세션이 종료되었습니다.{returnTo !== null && expiredUserId !== null && " 같은 계정으로 다시 로그인하면 하던 작업으로 돌아갑니다."}
          </p>
        )}

        {error && <p className="login-error">{error}</p>}

        <button type="submit" disabled={submitting || (mode === "signup" && verificationToken === null)}>
          {submitting ? "처리 중..." : mode === "signup" ? "가입하기" : "로그인"}
        </button>

        <div className="login-divider">또는</div>

        <div className="social-login-buttons">
          <button
            type="button"
            onClick={handleGoogle}
            disabled={!googleConfig?.enabled || leavingForGoogle}
            title={googleConfig && !googleConfig.enabled ? "구글 로그인이 설정되지 않았습니다" : undefined}
          >
            {leavingForGoogle ? "구글로 이동 중..." : "Google로 계속하기"}
          </button>
        </div>
      </form>
    </div>
  );
}
