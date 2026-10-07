// The frame every page sits in: a top bar (the service name, and on the right a
// login button — or, with a session, the profile button) and a sidebar that
// takes the author to the places of the service. Inside a novel's pages the
// sidebar also lists that novel's screens.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useMatch, useNavigate } from "react-router-dom";
import { getMe } from "../api/auth";
import type { UserPublic } from "../api/auth";
import { signOut } from "../api/client";
import { listNovels } from "../api/novels";
import { useSignedIn } from "../utils/useSignedIn";
import "./AppShell.css";

// Below this width the sidebar is a drawer the menu button opens, not a column.
const WIDE_QUERY = "(min-width: 861px)";

function ProfileMenu({ user }: { user: UserPublic | null }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => setOpen(false), [location.key]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !menuRef.current?.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  function handleLogout() {
    // The session lives in the token alone: forgetting it ends the session here.
    signOut();
    setOpen(false);
    navigate("/", { replace: true });
  }

  const name = user?.nickname ?? "프로필";
  return (
    <div className="profile-menu" ref={menuRef}>
      <button
        type="button"
        className="profile-button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="profile-avatar" aria-hidden="true">
          {name.slice(0, 1)}
        </span>
        <span className="profile-name">{name}</span>
      </button>
      {open && (
        <div className="profile-dropdown" role="menu">
          {user && (
            <div className="profile-summary">
              <strong>{user.nickname}</strong>
              <span>{user.email}</span>
            </div>
          )}
          <Link role="menuitem" to="/mypage">
            마이페이지
          </Link>
          <button type="button" role="menuitem" onClick={handleLogout}>
            로그아웃
          </button>
        </div>
      )}
    </div>
  );
}

function SidebarLink({ to, end, children }: { to: string; end?: boolean; children: ReactNode }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => (isActive ? "sidebar-link active" : "sidebar-link")}>
      {children}
    </NavLink>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const signedIn = useSignedIn();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [novelTitle, setNovelTitle] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.matchMedia(WIDE_QUERY).matches);
  const novelMatch = useMatch("/novels/:novelId/*");
  const novelId = signedIn ? (novelMatch?.params.novelId ?? null) : null;

  useEffect(() => {
    if (!signedIn) {
      setUser(null);
      return;
    }
    let ignore = false;
    getMe()
      .then((me) => !ignore && setUser(me))
      .catch(() => !ignore && setUser(null));
    return () => {
      ignore = true;
    };
  }, [signedIn]);

  // The novel's name, for the sidebar's heading.
  useEffect(() => {
    setNovelTitle(null);
    if (!novelId) return;
    let ignore = false;
    listNovels()
      .then((novels) => !ignore && setNovelTitle(novels.find((novel) => novel.id === novelId)?.title ?? null))
      .catch(() => undefined);
    return () => {
      ignore = true;
    };
  }, [novelId]);

  // The drawer closes behind a navigation.
  useEffect(() => {
    if (!window.matchMedia(WIDE_QUERY).matches) setSidebarOpen(false);
  }, [location.key]);

  return (
    <div className="app-shell">
      <header className="app-topbar">
        <button
          type="button"
          className="sidebar-toggle"
          aria-label="메뉴 열기·닫기"
          aria-expanded={sidebarOpen}
          onClick={() => setSidebarOpen((prev) => !prev)}
        >
          ☰
        </button>
        <Link className="app-brand" to="/">
          Retcona
        </Link>
        <div className="app-topbar-end">
          {signedIn ? (
            <ProfileMenu user={user} />
          ) : (
            location.pathname !== "/login" && (
              <Link className="login-button" to="/login">
                로그인
              </Link>
            )
          )}
        </div>
      </header>
      <div className="app-body">
        {sidebarOpen && <div className="sidebar-backdrop" onClick={() => setSidebarOpen(false)} />}
        <nav className={`app-sidebar${sidebarOpen ? " open" : ""}`} aria-label="주요 메뉴">
          <SidebarLink to="/" end>
            서비스 소개
          </SidebarLink>
          {signedIn ? (
            <>
              <SidebarLink to="/dashboard">대시보드</SidebarLink>
              <SidebarLink to="/mypage">마이페이지</SidebarLink>
            </>
          ) : (
            <SidebarLink to="/login">로그인 · 회원가입</SidebarLink>
          )}
          {novelId && (
            <div className="sidebar-section">
              <span className="sidebar-heading">{novelTitle ?? "현재 작품"}</span>
              <SidebarLink to={`/novels/${novelId}/episodes`}>화 목록 · 원고</SidebarLink>
              <SidebarLink to={`/novels/${novelId}/settings`}>설정 관리</SidebarLink>
              <SidebarLink to={`/novels/${novelId}/graph`}>관계 그래프 · 타임라인</SidebarLink>
            </div>
          )}
        </nav>
        <main className="app-main">{children}</main>
      </div>
    </div>
  );
}
