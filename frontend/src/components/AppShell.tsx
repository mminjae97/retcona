// The frame every page sits in: a header with the service logo, the places of the
// service to go to and, on the right, a login button — or, with a session, the
// profile button (My Page and logout are there). Inside a novel's pages a second
// row of the header lists that novel's screens.
import { useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useMatch, useNavigate } from "react-router-dom";
import { getMe } from "../api/auth";
import type { UserPublic } from "../api/auth";
import { signOut } from "../api/client";
import { listNovels } from "../api/novels";
import { useSignedIn } from "../utils/useSignedIn";
import logoUrl from "../assets/favicon.png";
import "./AppShell.css";

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

function HeaderLink({ to, end, children }: { to: string; end?: boolean; children: ReactNode }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => (isActive ? "header-link active" : "header-link")}>
      {children}
    </NavLink>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const location = useLocation();
  const signedIn = useSignedIn();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [novelTitle, setNovelTitle] = useState<string | null>(null);
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

  // The novel's name, for the second row.
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

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-topbar">
          <Link className="app-logo" to="/" aria-label="Retcona 홈">
            <img src={logoUrl} alt="Retcona" />
          </Link>
          <nav className="app-nav" aria-label="주요 메뉴">
            <HeaderLink to="/" end>
              서비스 소개
            </HeaderLink>
            {signedIn && <HeaderLink to="/dashboard">대시보드</HeaderLink>}
          </nav>
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
        </div>
        {novelId && (
          <nav className="app-subnav" aria-label="작품 메뉴">
            <span className="subnav-title">{novelTitle ?? "현재 작품"}</span>
            <HeaderLink to={`/novels/${novelId}/episodes`}>화 목록 · 원고</HeaderLink>
            <HeaderLink to={`/novels/${novelId}/settings`}>설정 관리</HeaderLink>
            <HeaderLink to={`/novels/${novelId}/graph`}>관계 그래프 · 타임라인</HeaderLink>
          </nav>
        )}
      </header>
      <main className="app-main">{children}</main>
    </div>
  );
}
