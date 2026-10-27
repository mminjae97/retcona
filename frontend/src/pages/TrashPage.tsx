// Trash (design doc 2.6): the novels the author deleted, each restorable until
// it's deleted for good 30 days later (the backend's empty_trash job).
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, describeError } from "../api/client";
import { listTrash, restoreNovel } from "../api/novels";
import type { TrashedNovel } from "../api/novels";
import "./TrashPage.css";

const DAY_MS = 24 * 60 * 60 * 1000;

// What the row says about when it goes for good. Past the date it's still
// here (the app was closed): the next pass, which runs when the app starts and
// daily, deletes it.
function describePurge(purgeAfter: string, now: number): string {
  const days = Math.ceil((new Date(purgeAfter).getTime() - now) / DAY_MS);
  return days > 0 ? `${days}일 뒤 영구 삭제` : "곧 영구 삭제";
}

export default function TrashPage() {
  const [trash, setTrash] = useState<TrashedNovel[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The novel being restored: one at a time, and a second click sends nothing
  // (the ref blocks it synchronously, before a re-render disables the buttons).
  const [restoring, setRestoring] = useState<string | null>(null);
  const restoringRef = useRef(false);
  // Ref, as on the novel list: blocks a second load synchronously.
  const loadingRef = useRef(false);

  function load() {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoadError(null);
    listTrash()
      .then(setTrash)
      .catch((err) => setLoadError(describeError(err)))
      .finally(() => {
        loadingRef.current = false;
      });
  }

  useEffect(() => {
    load();
  }, []);

  function drop(id: string) {
    setTrash((prev) => prev?.filter((n) => n.id !== id) ?? null);
  }

  async function handleRestore(novel: TrashedNovel) {
    if (restoringRef.current) return;
    restoringRef.current = true;
    setError(null);
    setNotice(null);
    setRestoring(novel.id);
    try {
      await restoreNovel(novel.id);
      drop(novel.id);
      setNotice(`"${novel.title}"을(를) 되살렸습니다. 내 작품에서 다시 볼 수 있습니다.`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        // Restored in another tab, or deleted for good meanwhile.
        drop(novel.id);
        setError(`"${novel.title}"은(는) 이미 휴지통에 없습니다.`);
      } else {
        setError(describeError(err));
      }
    } finally {
      restoringRef.current = false;
      setRestoring(null);
    }
  }

  const now = Date.now();

  return (
    <div className="trash-page">
      <Link className="back-link" to="/">
        ← 내 작품
      </Link>
      <h1>휴지통</h1>
      <p className="trash-help">삭제한 작품은 30일 동안 여기에 남고, 그 뒤에는 화·설정·검증 결과까지 모두 영구 삭제됩니다.</p>

      {notice && <p className="trash-notice">{notice}</p>}
      {error && <p className="trash-error">{error}</p>}

      <section className="trash-section">
        {trash === null ? (
          loadError ? (
            <p className="trash-error">
              {loadError} <button type="button" onClick={load}>다시 시도</button>
            </p>
          ) : (
            <p>불러오는 중...</p>
          )
        ) : trash.length === 0 ? (
          <p className="empty-state">휴지통이 비어 있습니다.</p>
        ) : (
          <ul className="trash-list">
            {trash.map((novel) => (
              <li key={novel.id} className="trash-row">
                <div className="trash-info">
                  <span className="trash-title">{novel.title}</span>
                  <span className="trash-meta">
                    {new Date(novel.deleted_at).toLocaleDateString()} 삭제 · {describePurge(novel.purge_after, now)}
                  </span>
                </div>
                <button type="button" onClick={() => handleRestore(novel)} disabled={restoring !== null}>
                  {restoring === novel.id ? "되살리는 중..." : "되살리기"}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
