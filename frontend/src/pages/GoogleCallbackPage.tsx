// Where Google sends the browser back to after sign-in (design doc 3.2).
// Checks the returned state against the login this tab started, hands the code
// to the backend, then either signs in (an existing account) or asks for a
// nickname first (a new one: the account is created with it, 3.6).
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { deletionAcceptedMessage, googleLogin, googleSignup, requestGoogleAccountDeletion } from "../api/auth";
import { ApiError, describeError } from "../api/client";
import { takePendingGoogleLogin } from "../utils/googleAuth";
import type { PendingGoogleLogin } from "../utils/googleAuth";
import { destinationAfterLogin } from "../utils/loginRedirect";
import { getNicknameError, nicknameInputProps, stripNickname } from "../utils/nickname";
import "./LoginPage.css";

type Step =
  | { kind: "working" }
  | { kind: "failed"; message: string; backTo?: "mypage" }
  | { kind: "nickname"; signupToken: string; email: string; pending: PendingGoogleLogin };

const LOGIN_ERRORS: Record<number, string> = {
  401: "구글 로그인에 실패했습니다. 다시 시도해주세요.",
  403: "이메일 인증이 완료된 구글 계정만 사용할 수 있습니다.",
  409: "이 이메일은 이미 이메일·비밀번호로 가입되어 있습니다. 이메일과 비밀번호로 로그인해주세요.",
  410: "탈퇴 유예기간이 지나 삭제 예정인 계정입니다. 복구할 수 없습니다.",
  502: "구글에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.",
  503: "구글 로그인이 설정되지 않았습니다.",
};

const DELETION_ERRORS: Record<number, string> = {
  // 401 isn't here: on this authenticated call it means the session ended,
  // which the app handles by itself (a sign-in again; the backend answers 400
  // when it's Google that turned the code down).
  400: "구글 본인 확인에 실패했습니다. 마이페이지에서 다시 시도해주세요.",
  403: "이 계정에 연결된 구글 계정이 아닙니다. 연결된 구글 계정을 선택해 다시 시도해주세요.",
  409: "이 계정은 비밀번호로 탈퇴를 확인합니다. 마이페이지에서 다시 시도해주세요.",
  502: "구글에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.",
  503: "구글 로그인이 설정되지 않았습니다.",
};

const SIGNUP_ERRORS: Record<number, string> = {
  401: "가입 시간이 지났습니다. 구글 로그인을 처음부터 다시 해주세요.",
  409: "이미 가입된 이메일입니다. 로그인 화면에서 다시 로그인해주세요.",
  422: "필명을 다시 확인해주세요.",
};

function messageFor(err: unknown, byStatus: Record<number, string>): string {
  if (err instanceof ApiError && byStatus[err.status]) return byStatus[err.status];
  return describeError(err);
}

export default function GoogleCallbackPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [step, setStep] = useState<Step>({ kind: "working" });
  const [nickname, setNickname] = useState("");
  const [nicknameError, setNicknameError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // The code can be exchanged only once, and the pending login is consumed
  // reading it: StrictMode's second effect run must not try again.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const pending = takePendingGoogleLogin(params.get("state"));
    const code = params.get("code");
    if (params.get("error")) {
      // Declined on Google's screen (access_denied), or the like.
      setStep({ kind: "failed", message: "구글 로그인이 취소되었습니다." });
      return;
    }
    if (pending === null || code === null) {
      setStep({ kind: "failed", message: "로그인 요청을 확인하지 못했습니다. 로그인 화면에서 다시 시도해주세요." });
      return;
    }
    if (pending.purpose === "delete-account") {
      // Back from confirming a Google account's deletion (MyPage).
      requestGoogleAccountDeletion(code, pending.codeVerifier)
        .then((result) => {
          window.alert(deletionAcceptedMessage(result));
          navigate("/login", { replace: true });
        })
        .catch((err) => setStep({ kind: "failed", message: messageFor(err, DELETION_ERRORS), backTo: "mypage" }));
      return;
    }
    googleLogin(code, pending.codeVerifier)
      .then((result) => {
        if (result.status === "signup_required") {
          setStep({ kind: "nickname", signupToken: result.signupToken, email: result.email, pending });
          return;
        }
        if (result.deletionCancelled) {
          window.alert("진행 중이던 회원 탈퇴가 취소되었습니다. 계정이 원래대로 복구되었어요.");
        }
        navigate(destinationAfterLogin(pending, result.user.id), { replace: true });
      })
      .catch((err) => setStep({ kind: "failed", message: messageFor(err, LOGIN_ERRORS) }));
  }, [params, navigate]);

  async function handleSignup(e: FormEvent) {
    e.preventDefault();
    if (step.kind !== "nickname" || submitting) return;
    const invalid = getNicknameError(nickname);
    if (invalid) {
      setNicknameError(invalid);
      return;
    }
    setSubmitting(true);
    setNicknameError(null);
    try {
      const user = await googleSignup(step.signupToken, stripNickname(nickname));
      navigate(destinationAfterLogin(step.pending, user.id), { replace: true });
    } catch (err) {
      const message = messageFor(err, SIGNUP_ERRORS);
      if (err instanceof ApiError && (err.status === 401 || err.status === 409)) {
        // Nothing left to do on this screen: start over from the login page.
        setStep({ kind: "failed", message });
      } else {
        setNicknameError(message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-page">
      {step.kind === "nickname" ? (
        <form className="login-card" onSubmit={handleSignup}>
          <h1>필명 설정</h1>
          <p className="login-notice">
            {step.email} 구글 계정으로 가입합니다. 활동할 필명을 정해주세요. 필명은 마이페이지에서 언제든 바꿀 수
            있습니다.
          </p>
          <label>
            필명(닉네임)
            <input type="text" value={nickname} {...nicknameInputProps(setNickname)} required autoFocus />
          </label>
          {nicknameError && <p className="login-error">{nicknameError}</p>}
          <button type="submit" disabled={submitting}>
            {submitting ? "처리 중..." : "가입하기"}
          </button>
        </form>
      ) : (
        <div className="login-card">
          <h1>Retcona</h1>
          {step.kind === "working" ? (
            <p>구글 계정을 확인하는 중...</p>
          ) : step.backTo === "mypage" ? (
            <>
              <p className="login-error">{step.message}</p>
              <Link to="/mypage">마이페이지로</Link>
            </>
          ) : (
            <>
              <p className="login-error">{step.message}</p>
              <Link to="/login">로그인 화면으로</Link>
            </>
          )}
        </div>
      )}
    </div>
  );
}
