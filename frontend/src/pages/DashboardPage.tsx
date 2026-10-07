// Dashboard (design doc 2.1): where a signed-in author lands.
// Leads on to each novel's episodes (the manuscript editor), its settings and its
// relationship graph · timeline, and to My Page, where novels are created and
// managed. The "pre-writing brief / checklist" the flow lists is not built yet.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getMe } from "../api/auth";
import type { UserPublic } from "../api/auth";
import { describeError, signOut } from "../api/client";
import { listNovels } from "../api/novels";
import type { NovelPublic } from "../api/novels";
import "./DashboardPage.css";

export default function DashboardPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [novels, setNovels] = useState<NovelPublic[] | null>(null);
  const [novelsError, setNovelsError] = useState<string | null>(null);
  // Ref, not state: blocks a second call at once (a fast double-click on "다시 시도"),
  // before a re-render could disable the button.
  const loadingRef = useRef(false);

  function loadNovels() {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setNovelsError(null);
    listNovels()
      .then(setNovels)
      .catch((err) => setNovelsError(describeError(err)))
      .finally(() => {
        loadingRef.current = false;
      });
  }

  useEffect(() => {
    // Fetched independently: a failure of one doesn't strand the other.
    // (Without a session either call is answered 401, and the app sends the visitor to the login screen.)
    getMe()
      .then(setUser)
      .catch(() => setUser(null));
    loadNovels();
  }, []);

  function handleLogout() {
    // The session lives in the token alone: forgetting it ends the session here.
    signOut();
    navigate("/login", { replace: true });
  }

  return (
    <div className="dashboard-page">
      <header className="dashboard-header">
        <div>
          <h1>{user ? `${user.nickname}님, 안녕하세요` : "대시보드"}</h1>
          <p className="dashboard-lead">이어서 쓸 작품을 골라 주세요.</p>
        </div>
        <div className="dashboard-actions">
          <Link className="link-button" to="/mypage">
            마이페이지
          </Link>
          <button type="button" onClick={handleLogout}>
            로그아웃
          </button>
        </div>
      </header>

      <section>
        <h2>내 작품</h2>
        {novelsError && (
          <p className="dashboard-error">
            {novelsError} <button type="button" onClick={loadNovels}>다시 시도</button>
          </p>
        )}
        {novels === null ? (
          !novelsError && <p>불러오는 중...</p>
        ) : novels.length === 0 ? (
          <p className="empty-state">
            아직 작품이 없습니다. <Link to="/mypage">마이페이지</Link>에서 새 작품을 만들어 보세요.
          </p>
        ) : (
          <ul className="dashboard-novels">
            {novels.map((novel) => (
              <li key={novel.id}>
                <span className="dashboard-novel-title">{novel.title}</span>
                <span className="dashboard-novel-links">
                  <Link className="link-button" to={`/novels/${novel.id}/episodes`}>
                    원고 쓰기
                  </Link>
                  <Link className="link-button" to={`/novels/${novel.id}/settings`}>
                    설정 관리
                  </Link>
                  <Link className="link-button" to={`/novels/${novel.id}/graph`}>
                    관계 그래프 · 타임라인
                  </Link>
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
