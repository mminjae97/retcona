// My Page (design doc 2.6)
// Account info (change nickname), my novels list (open/relationship graph·timeline/delete), danger zone (delete account)
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { getMe } from "../api/auth";
import type { UserPublic } from "../api/auth";
import { describeError } from "../api/client";
import { createNovel, deleteNovel, listNovels, renameNovel } from "../api/novels";
import type { NovelPublic } from "../api/novels";
import "./MyPage.css";

export default function MyPage() {
  const [user, setUser] = useState<UserPublic | null>(null);
  const [userError, setUserError] = useState<string | null>(null);
  const [novels, setNovels] = useState<NovelPublic[] | null>(null);
  const [novelsError, setNovelsError] = useState<string | null>(null);
  const [novelsLoaded, setNovelsLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");

  useEffect(() => {
    // Fetched independently, not via Promise.all, so one failing (e.g. an
    // expired token) doesn't also strand the other section on "불러오는 중".
    getMe()
      .then(setUser)
      .catch((err) => setUserError(describeError(err)));
    listNovels()
      .then(setNovels)
      .catch((err) => setNovelsError(describeError(err)))
      .finally(() => setNovelsLoaded(true));
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    // Guard on the initial GET having settled, not just on `creating`:
    // creating a novel before it resolves would race an optimistic
    // [novel, ...(prev ?? [])] update against that GET's list, and whichever
    // resolves second would silently wipe out the other's result. Gating on
    // `novelsLoaded` (settled either way) rather than `novels === null`
    // means a failed initial fetch doesn't permanently block creation.
    if (creating || !novelsLoaded || !newTitle.trim()) return;
    setError(null);
    setCreating(true);
    try {
      const novel = await createNovel(newTitle);
      setNovels((prev) => [novel, ...(prev ?? [])]);
      setNewTitle("");
    } catch (err) {
      setError(describeError(err));
    } finally {
      setCreating(false);
    }
  }

  function startRename(novel: NovelPublic) {
    setRenamingId(novel.id);
    setRenameValue(novel.title);
  }

  async function handleRename(e: FormEvent, id: string) {
    e.preventDefault();
    if (!renameValue.trim()) return;
    setError(null);
    try {
      const updated = await renameNovel(id, renameValue);
      setNovels((prev) => prev?.map((n) => (n.id === id ? updated : n)) ?? null);
      setRenamingId(null);
    } catch (err) {
      setError(describeError(err));
    }
  }

  async function handleDelete(novel: NovelPublic) {
    if (!window.confirm(`"${novel.title}"을(를) 삭제하시겠습니까? 30일 이내에는 복구할 수 있습니다.`)) return;
    setError(null);
    try {
      await deleteNovel(novel.id);
      setNovels((prev) => prev?.filter((n) => n.id !== novel.id) ?? null);
    } catch (err) {
      setError(describeError(err));
    }
  }

  return (
    <div className="mypage">
      <h1>마이페이지</h1>

      {error && <p className="mypage-error">{error}</p>}

      <section className="mypage-section">
        <h2>계정 정보</h2>
        {user ? (
          <dl className="account-info">
            <dt>필명</dt>
            <dd>
              {user.nickname}{" "}
              <button type="button" disabled title="필명 변경은 준비 중입니다">
                변경
              </button>
            </dd>
            <dt>이메일</dt>
            <dd>{user.email}</dd>
          </dl>
        ) : userError ? (
          <p className="mypage-error">{userError}</p>
        ) : (
          <p>불러오는 중...</p>
        )}
      </section>

      <section className="mypage-section">
        <div className="section-header">
          <h2>내 작품</h2>
        </div>

        <form className="new-novel-form" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="새 작품 제목"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            maxLength={200}
          />
          <button type="submit" disabled={creating || !novelsLoaded || !newTitle.trim()}>
            + 새 작품
          </button>
        </form>

        {novels === null ? (
          novelsError ? <p className="mypage-error">{novelsError}</p> : <p>불러오는 중...</p>
        ) : novels.length === 0 ? (
          <p className="empty-state">아직 등록한 작품이 없습니다.</p>
        ) : (
          <ul className="novel-list">
            {novels.map((novel) => (
              <li key={novel.id} className="novel-row">
                {renamingId === novel.id ? (
                  <form className="rename-form" onSubmit={(e) => handleRename(e, novel.id)}>
                    <input
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      maxLength={200}
                      autoFocus
                    />
                    <button type="submit">저장</button>
                    <button type="button" onClick={() => setRenamingId(null)}>
                      취소
                    </button>
                  </form>
                ) : (
                  <>
                    <span className="novel-title">{novel.title}</span>
                    <div className="novel-actions">
                      <button type="button" disabled title="원고 작성 에디터는 준비 중입니다">
                        열기
                      </button>
                      <Link className="link-button" to={`/novels/${novel.id}/graph`}>
                        관계도·타임라인
                      </Link>
                      <button type="button" onClick={() => startRename(novel)}>
                        제목 변경
                      </button>
                      <button type="button" onClick={() => handleDelete(novel)}>
                        삭제
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mypage-section danger-zone">
        <h2>⚠ 위험 영역</h2>
        <button type="button" disabled title="회원 탈퇴는 준비 중입니다">
          회원 탈퇴
        </button>
      </section>
    </div>
  );
}
