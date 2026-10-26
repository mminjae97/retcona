// The frame every page sits in: a header with the app's logo and the link to
// the novel list (both lead there). Inside a novel's pages a second row of the
// header lists that novel's screens.
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, NavLink, useMatch } from "react-router-dom";
import { getNovel } from "../api/novels";
import logoUrl from "../assets/favicon.png";
import "./AppShell.css";

function HeaderLink({ to, end, children }: { to: string; end?: boolean; children: ReactNode }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => (isActive ? "header-link active" : "header-link")}>
      {children}
    </NavLink>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const [novelTitle, setNovelTitle] = useState<string | null>(null);
  const novelMatch = useMatch("/novels/:novelId/*");
  const novelId = novelMatch?.params.novelId ?? null;

  // The novel's name, for the second row.
  useEffect(() => {
    setNovelTitle(null);
    if (!novelId) return;
    let ignore = false;
    getNovel(novelId)
      .then((novel) => !ignore && setNovelTitle(novel.title))
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
              내 작품
            </HeaderLink>
          </nav>
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
