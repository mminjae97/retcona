// Novel list (design doc 2.6): the screen the app opens on. There are no
// accounts: create, rename, open (episodes · settings · relationship graph ·
// timeline) and delete the author's novels — to the trash, linked at the
// bottom with how many it holds.
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, describeError } from "../api/client";
import { createNovel, deleteNovel, listNovels, listTrash, renameNovel } from "../api/novels";
import type { NovelPublic } from "../api/novels";
import "./NovelListPage.css";

export default function NovelListPage() {
  const [novels, setNovels] = useState<NovelPublic[] | null>(null);
  const [novelsError, setNovelsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  // The novel being deleted: a second click (or a double-click past the
  // confirm) doesn't send a second DELETE, which would 404 on a novel already gone.
  const [deleting, setDeleting] = useState<string | null>(null);
  // The novel being renamed (one row at a time), and its form's state.
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  // While a rename is saving, its form stays open (취소 and the other rows'
  // 제목 변경 wait): one rename at a time, and its result — the new title, or
  // the error — always lands in the form that sent it.
  const [renameSaving, setRenameSaving] = useState(false);
  // Ref, not state: needs to block a second call synchronously (e.g. a fast
  // double-click on "다시 시도"), before a state update could re-render and
  // disable the button.
  const novelsLoadingRef = useRef(false);
  // How many novels the trash holds; null until known (the link then shows no count).
  const [trashCount, setTrashCount] = useState<number | null>(null);
  // Numbers the trash-count requests: only the latest one's answer is shown,
  // so a slow earlier one can't overwrite the count after a delete.
  const trashCountRequestRef = useRef(0);

  function dropNovel(id: string) {
    setNovels((prev) => prev?.filter((n) => n.id !== id) ?? null);
  }

  // The trash count comes along, so "다시 시도" retries it too.
  function loadNovels() {
    if (novelsLoadingRef.current) return;
    novelsLoadingRef.current = true;
    setNovelsError(null);
    loadTrashCount();
    listNovels()
      .then(setNovels)
      .catch((err) => setNovelsError(describeError(err)))
      .finally(() => {
        novelsLoadingRef.current = false;
      });
  }

  function loadTrashCount() {
    const request = ++trashCountRequestRef.current;
    listTrash()
      .then((trash) => {
        if (request === trashCountRequestRef.current) setTrashCount(trash.length);
      })
      .catch(() => {
        if (request === trashCountRequestRef.current) setTrashCount(null);
      });
  }

  useEffect(() => {
    loadNovels();
  }, []);

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    // Guard on `novels` having loaded (not just `creating`): creating before
    // the initial GET resolves would race an optimistic
    // [novel, ...(prev ?? [])] update against that GET's list, and whichever
    // resolves second would silently wipe out the other's result. If the
    // load instead failed, `novels` also stays null here — that's
    // deliberate too, since creating against an unknown/incomplete list
    // would make it look like the other novels had vanished.
    // The "다시 시도" button (shown on load failure) is the way out, not
    // loosening this guard.
    if (creating || novels === null || !newTitle.trim()) return;
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
    if (renameSaving) return;
    setRenaming(novel.id);
    setRenameValue(novel.title);
    setRenameError(null);
  }

  function cancelRename() {
    if (renameSaving) return;
    setRenaming(null);
    setRenameError(null);
  }

  async function handleRename(e: FormEvent, id: string) {
    e.preventDefault();
    if (renameSaving || !renameValue.trim()) return;
    setRenameError(null);
    setRenameSaving(true);
    try {
      const updated = await renameNovel(id, renameValue);
      setNovels((prev) => prev?.map((n) => (n.id === id ? updated : n)) ?? null);
      setRenaming(null);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // Deleted meanwhile (in another tab): no title to keep.
        dropNovel(id);
        setRenaming(null);
      } else {
        setRenameError(describeError(err));
      }
    } finally {
      setRenameSaving(false);
    }
  }

  async function handleDelete(novel: NovelPublic) {
    if (deleting !== null) return;
    if (!window.confirm(`"${novel.title}"을(를) 휴지통으로 옮길까요? 30일 안에는 휴지통에서 되살릴 수 있습니다.`)) return;
    setError(null);
    setDeleting(novel.id);
    try {
      await deleteNovel(novel.id);
      dropNovel(novel.id);
    } catch (err) {
      // 404: already deleted (in another tab), which is what was asked.
      if (err instanceof ApiError && err.status === 404) dropNovel(novel.id);
      else setError(describeError(err));
    } finally {
      setDeleting(null);
      loadTrashCount();
    }
  }

  return (
    <div className="novel-list-page">
      <h1>내 작품</h1>

      {error && <p className="novel-list-error">{error}</p>}

      <section className="novel-list-section">
        <form className="new-novel-form" onSubmit={handleCreate}>
          <input
            type="text"
            placeholder="새 작품 제목"
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            maxLength={200}
          />
          <button type="submit" disabled={creating || novels === null || !newTitle.trim()}>
            + 새 작품
          </button>
        </form>

        {novels === null ? (
          novelsError ? (
            <p className="novel-list-error">
              {novelsError} <button type="button" onClick={loadNovels}>다시 시도</button>
            </p>
          ) : (
            <p>불러오는 중...</p>
          )
        ) : novels.length === 0 ? (
          <p className="empty-state">아직 등록한 작품이 없습니다. 위에서 새 작품을 만들어 보세요.</p>
        ) : (
          <ul className="novel-list">
            {novels.map((novel) => (
              <li key={novel.id} className="novel-row">
                {renaming === novel.id ? (
                  <form className="rename-form" onSubmit={(e) => handleRename(e, novel.id)}>
                    <input
                      type="text"
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      maxLength={200}
                      autoFocus
                    />
                    <button type="submit" disabled={renameSaving}>
                      {renameSaving ? "저장 중..." : "저장"}
                    </button>
                    <button type="button" onClick={cancelRename} disabled={renameSaving}>
                      취소
                    </button>
                    {renameError && <p className="novel-list-error">{renameError}</p>}
                  </form>
                ) : (
                  <>
                    <span className="novel-title">{novel.title}</span>
                    <div className="novel-actions">
                      <Link className="link-button" to={`/novels/${novel.id}/episodes`}>
                        열기
                      </Link>
                      <Link className="link-button" to={`/novels/${novel.id}/settings`}>
                        설정
                      </Link>
                      <Link className="link-button" to={`/novels/${novel.id}/graph`}>
                        관계도·타임라인
                      </Link>
                      <button type="button" onClick={() => startRename(novel)} disabled={renameSaving}>
                        제목 변경
                      </button>
                      <button type="button" onClick={() => handleDelete(novel)} disabled={deleting !== null}>
                        {deleting === novel.id ? "삭제 중..." : "삭제"}
                      </button>
                    </div>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <Link className="trash-link" to="/trash">
        휴지통{trashCount !== null && ` (${trashCount})`}
      </Link>
    </div>
  );
}
