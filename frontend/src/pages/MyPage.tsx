// My Page (design doc 2.6)
// Account info (change nickname), my novels list (open/relationship graph·timeline/delete), danger zone (delete account)
import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getMe, requestAccountDeletion, updateNickname } from "../api/auth";
import type { UserPublic } from "../api/auth";
import { ApiError, describeError } from "../api/client";
import { isValidNickname } from "../utils/nickname";
import { createNovel, deleteNovel, listNovels, renameNovel } from "../api/novels";
import type { NovelPublic } from "../api/novels";
import "./MyPage.css";

const DELETION_ERROR_MESSAGES_BY_STATUS: Record<number, string> = {
  403: "비밀번호가 올바르지 않습니다.",
  501: "소셜 로그인 계정의 탈퇴는 아직 지원되지 않습니다.",
};

export default function MyPage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<UserPublic | null>(null);
  const [userError, setUserError] = useState<string | null>(null);
  const [novels, setNovels] = useState<NovelPublic[] | null>(null);
  const [novelsError, setNovelsError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [editingNickname, setEditingNickname] = useState(false);
  const [nicknameValue, setNicknameValue] = useState("");
  const [savingNickname, setSavingNickname] = useState(false);
  const [nicknameError, setNicknameError] = useState<string | null>(null);
  const [confirmingDeletion, setConfirmingDeletion] = useState(false);
  const [deletionPassword, setDeletionPassword] = useState("");
  const [deleting, setDeleting] = useState(false);
  const [deletionError, setDeletionError] = useState<string | null>(null);
  // Ref, not state: needs to block a second call synchronously (e.g. a fast
  // double-click on "다시 시도"), before a state update could re-render and
  // disable the button.
  const novelsLoadingRef = useRef(false);

  function loadNovels() {
    if (novelsLoadingRef.current) return;
    novelsLoadingRef.current = true;
    setNovelsError(null);
    listNovels()
      .then(setNovels)
      .catch((err) => setNovelsError(describeError(err)))
      .finally(() => {
        novelsLoadingRef.current = false;
      });
  }

  useEffect(() => {
    // Fetched independently, not via Promise.all, so one failing (e.g. an
    // expired token) doesn't also strand the other section on "불러오는 중".
    getMe()
      .then(setUser)
      .catch((err) => setUserError(describeError(err)));
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
    // would make it look like the account's other novels had vanished.
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
    setRenamingId(novel.id);
    setRenameValue(novel.title);
  }

  async function handleRename(e: FormEvent, id: string) {
    e.preventDefault();
    if (renaming || !renameValue.trim()) return;
    setError(null);
    setRenaming(true);
    try {
      const updated = await renameNovel(id, renameValue);
      setNovels((prev) => prev?.map((n) => (n.id === id ? updated : n)) ?? null);
      setRenamingId(null);
    } catch (err) {
      setError(describeError(err));
    } finally {
      setRenaming(false);
    }
  }

  function startEditNickname() {
    if (!user) return;
    setNicknameValue(user.nickname);
    setNicknameError(null);
    setEditingNickname(true);
  }

  async function handleSaveNickname(e: FormEvent) {
    e.preventDefault();
    if (savingNickname) return;
    // Validate the trimmed value in code points, matching the backend's
    // strip-then-check rule (3.6).
    const trimmed = nicknameValue.trim();
    if (!isValidNickname(trimmed)) {
      setNicknameError("필명은 공백을 제외하고 2~20자로 입력해주세요.");
      return;
    }
    setNicknameError(null);
    setSavingNickname(true);
    try {
      setUser(await updateNickname(trimmed));
      setEditingNickname(false);
    } catch (err) {
      setNicknameError(describeError(err));
    } finally {
      setSavingNickname(false);
    }
  }

  function cancelEditNickname() {
    setEditingNickname(false);
    setNicknameError(null);
  }

  function cancelDeletion() {
    setConfirmingDeletion(false);
    setDeletionPassword("");
    setDeletionError(null);
  }

  async function handleRequestDeletion(e: FormEvent) {
    e.preventDefault();
    if (deleting || !deletionPassword) return;
    if (
      !window.confirm(
        "정말 회원 탈퇴를 접수하시겠습니까?\n30일의 유예기간이 지나면 계정과 모든 작품 데이터가 영구 삭제되며 복구할 수 없습니다.",
      )
    ) {
      return;
    }
    setDeletionError(null);
    setDeleting(true);
    try {
      const result = await requestAccountDeletion(deletionPassword);
      const purgeDate = new Date(result.purge_after).toLocaleDateString("ko-KR");
      window.alert(`탈퇴가 접수되었습니다. ${purgeDate}에 모든 데이터가 영구 삭제됩니다.\n그 전에 다시 로그인하면 탈퇴가 취소됩니다.`);
      navigate("/login");
    } catch (err) {
      setDeletionError(
        (err instanceof ApiError && DELETION_ERROR_MESSAGES_BY_STATUS[err.status]) || describeError(err),
      );
      setDeleting(false);
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
              {editingNickname ? (
                <form className="rename-form" onSubmit={handleSaveNickname}>
                  <input
                    type="text"
                    value={nicknameValue}
                    onChange={(e) => setNicknameValue(e.target.value)}
                    // 20 code points can take up to 40 UTF-16 units, which is what
                    // maxLength counts — the exact 2~20 check is isValidNickname's.
                    maxLength={40}
                    autoFocus
                  />
                  <button type="submit" disabled={savingNickname}>
                    저장
                  </button>
                  <button type="button" onClick={cancelEditNickname} disabled={savingNickname}>
                    취소
                  </button>
                </form>
              ) : (
                <>
                  {user.nickname}{" "}
                  <button type="button" onClick={startEditNickname}>
                    변경
                  </button>
                </>
              )}
              {nicknameError && <p className="mypage-error">{nicknameError}</p>}
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
          <button type="submit" disabled={creating || novels === null || !newTitle.trim()}>
            + 새 작품
          </button>
        </form>

        {novels === null ? (
          novelsError ? (
            <p className="mypage-error">
              {novelsError} <button type="button" onClick={loadNovels}>다시 시도</button>
            </p>
          ) : (
            <p>불러오는 중...</p>
          )
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
                    <button type="submit" disabled={renaming}>
                      저장
                    </button>
                    <button type="button" onClick={() => setRenamingId(null)}>
                      취소
                    </button>
                  </form>
                ) : (
                  <>
                    <span className="novel-title">{novel.title}</span>
                    <div className="novel-actions">
                      <Link className="link-button" to={`/novels/${novel.id}/episodes`}>
                        열기
                      </Link>
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
        {confirmingDeletion ? (
          <form className="deletion-form" onSubmit={handleRequestDeletion}>
            <p>
              본인 확인을 위해 비밀번호를 입력해주세요. 탈퇴 접수 후 30일이 지나면 계정과 모든 작품 데이터가 영구
              삭제되며, 그 전에 다시 로그인하면 탈퇴가 취소됩니다.
            </p>
            <input
              type="password"
              placeholder="비밀번호"
              value={deletionPassword}
              onChange={(e) => setDeletionPassword(e.target.value)}
              autoComplete="current-password"
              autoFocus
            />
            <button type="submit" disabled={deleting || !deletionPassword}>
              탈퇴 접수
            </button>
            <button type="button" onClick={cancelDeletion} disabled={deleting}>
              취소
            </button>
            {deletionError && <p className="mypage-error">{deletionError}</p>}
          </form>
        ) : (
          <button type="button" onClick={() => setConfirmingDeletion(true)}>
            회원 탈퇴
          </button>
        )}
      </section>
    </div>
  );
}
