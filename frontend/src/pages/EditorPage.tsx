// Manuscript editor (design doc 2.2)
// Autosave (debounced, doesn't call the AI pipeline) + explicit save, both hit the same
// PATCH endpoint — the only difference is what triggers them. "Run validation" (2.2, 8.2)
// stays disabled: it depends on QueueClient (infra/queue_client.py), which isn't implemented yet.
// Editing a submitted episode flips its status back to draft (2.2).
// Typing is also mirrored to a local draft (utils/draft.ts, debounced, and flushed when the page is hidden or
// the editor unmounts) until a save confirms it, so text survives an expired session, a network failure or a
// closed tab. Every tab (every page load) keeps its own draft and rewrites only that one; the drafts other tabs
// or earlier loads left are listed on the page and the author loads whichever one they want.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { fetchCurrentUserId } from "../api/auth";
import { describeError } from "../api/client";
import { getEpisode, saveEpisode } from "../api/episodes";
import type { EpisodePublic } from "../api/episodes";
import {
  MAX_DRAFTS_PER_EPISODE,
  clearDraft,
  discardDraft,
  isDraftEventFor,
  listOtherDrafts,
  saveDraft,
  startDraftSlot,
} from "../utils/draft";
import type { StoredDraft } from "../utils/draft";
import "./EditorPage.css";

const AUTOSAVE_DELAY_MS = 2000;
// Much shorter than the autosave delay so the local draft is on disk before the
// server save fires, but coalescing keystrokes: stringifying and storing a long
// manuscript on every key press would make typing lag.
const DRAFT_DEBOUNCE_MS = 300;
// Another tab typing rewrites its draft every few hundred ms; the list only
// needs to catch up once that settles.
const OTHER_DRAFTS_REFRESH_DEBOUNCE_MS = 1000;
// How long the "draft loaded" notice stays up.
const NOTICE_DURATION_MS = 6000;

// First characters of a draft, counted in code points so an emoji isn't cut in half.
function previewDraft(content: string): string {
  if (content.length === 0) return "(빈 내용)";
  // Only the head is split into code points: this runs for every parked draft
  // on every render (each keystroke), and a chapter can be 100k characters.
  const shown = Array.from(content.slice(0, 82)).slice(0, 40).join("");
  return shown + (content.length > shown.length ? "…" : "");
}

type SaveState = "idle" | "saving" | "saved" | "error";

interface PendingSave {
  novelId: string;
  episodeId: string;
  content: string;
}

export default function EditorPage() {
  const { novelId, episodeId } = useParams<{ novelId: string; episodeId: string }>();
  const [episode, setEpisode] = useState<EpisodePublic | null>(null);
  const [content, setContent] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // Unsaved drafts of this episode left by other tabs or earlier page loads;
  // the author loads or discards them.
  const [otherDrafts, setOtherDrafts] = useState<StoredDraft[]>([]);
  // The same list, for code that must look at the current one without waiting for a render.
  const otherDraftsRef = useRef<StoredDraft[]>([]);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Content not yet sent to the API. Flushed directly (bypassing component
  // state) when the user navigates to a different episode or away from the
  // editor before the debounce fires — otherwise the leftover timer would
  // still be live, and its eventual save() response would overwrite this
  // component's now-unrelated state for whichever episode is on screen next.
  const pendingRef = useRef<PendingSave | null>(null);
  // Tracks in-flight/most-recent save to avoid an out-of-order autosave
  // response clobbering a newer explicit save's result.
  const saveSeqRef = useRef(0);
  // Chains save requests so a later one (e.g. an explicit save fired right
  // after an autosave) always waits for the previous request to finish
  // before sending — otherwise two in-flight PATCHes for the same episode
  // could commit out of order and the older one would silently overwrite
  // the newer content server-side, which seq alone (client-side response
  // ordering only) can't prevent.
  const saveChainRef = useRef<Promise<void>>(Promise.resolve());
  // True only while the component is actually mounted — separate from the
  // per-episode "cancelled" flag in the load effect below, since the
  // unmount-flush save is deliberately still sent (and still updates
  // `episode`/`saveState` if it turns out to be the current episode) but
  // must never touch state once React has torn the component down.
  const mountedRef = useRef(true);
  useEffect(() => {
    // Set true here too, not just in the useRef initializer: React 18
    // StrictMode dev-mode double-invokes this effect (mount -> cleanup ->
    // mount again) on the very first real mount, so without this the
    // cleanup below would leave mountedRef permanently false and silently
    // disable every save-status UI update for the component's whole life.
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Draft write-behind. The episode's server `updated_at` is tracked in a ref
  // (not read from state) because the debounced write fires after renders
  // have moved on, and must record the base as of *now*.
  const currentEpisodeIdRef = useRef<string | undefined>(undefined);
  const serverUpdatedAtRef = useRef("");
  // The same version as state, for what is drawn from it: kept in step with the
  // ref (which the debounced writes need), so the list and the load
  // confirmation always agree.
  const [serverUpdatedAt, setServerUpdatedAt] = useState("");
  const serverContentRef = useRef("");
  const draftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const draftPendingRef = useRef<{ episodeId: string; content: string } | null>(null);
  // What this session's own draft of each episode holds, so a confirmed save can
  // be compared against it without reading the whole manuscript back out of storage.
  const ownDraftRef = useRef(new Map<string, string>());

  // The server's version of the current episode, kept in one place: the refs
  // are what the debounced writes read, the state is what the page draws from.
  const setServerVersion = useCallback((updatedAt: string, content: string) => {
    serverUpdatedAtRef.current = updatedAt;
    serverContentRef.current = content;
    setServerUpdatedAt(updatedAt);
  }, []);

  // Re-reads the other sessions' drafts. What the server already holds is
  // nothing left to offer, so it is dropped rather than listed.
  const showOtherDrafts = useCallback((next: StoredDraft[]) => {
    const prev = otherDraftsRef.current;
    // Same drafts as before: keep the old array so nothing re-renders (the
    // textarea holds a whole chapter).
    if (prev.length === next.length && prev.every((d, i) => d.key === next[i].key && d.savedAt === next[i].savedAt)) return;
    otherDraftsRef.current = next;
    setOtherDrafts(next);
  }, []);

  // `serverIsCurrent`: the server's content was just read or written by this tab.
  // Only then is a draft equal to it deleted; otherwise it is merely left out of
  // the list, because this tab's copy of the server's content may be stale
  // (another tab has saved since) and the draft may be unsaved work.
  const refreshOtherDrafts = useCallback(
    (serverIsCurrent = false) => {
      const id = currentEpisodeIdRef.current;
      if (!id) return;
      const unsaved = listOtherDrafts(id).filter((d) => {
        if (d.content !== serverContentRef.current) return true;
        if (serverIsCurrent) discardDraft(d.key);
        return false;
      });
      showOtherDrafts(unsaved);
    },
    [showOtherDrafts],
  );

  const flushDraft = useCallback(() => {
    if (draftTimerRef.current) {
      clearTimeout(draftTimerRef.current);
      draftTimerRef.current = null;
    }
    const pending = draftPendingRef.current;
    if (!pending) return;
    draftPendingRef.current = null;
    const written = saveDraft(pending.episodeId, {
      content: pending.content,
      baseUpdatedAt: serverUpdatedAtRef.current,
    });
    if (written) ownDraftRef.current.set(pending.episodeId, pending.content);
    else ownDraftRef.current.delete(pending.episodeId);
    // If the write failed, the copy already in storage is older than what the
    // author has typed. Leaving it would let a later save "rebase" it onto
    // the new server version and offer it as if it were current — no draft
    // is safer than a stale one.
    if (!written) clearDraft(pending.episodeId);
  }, []);

  useEffect(() => {
    // Last chances to get a pending debounced write onto disk. On mobile,
    // switching apps or the OS reclaiming the tab often fires no pagehide at
    // all, only visibilitychange — so both are needed.
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushDraft();
    };
    // Another tab writing or removing a draft of this episode.
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    const onStorage = (e: StorageEvent) => {
      const id = currentEpisodeIdRef.current;
      if (!id || !isDraftEventFor(id, e.key)) return;
      if (refreshTimer) clearTimeout(refreshTimer);
      refreshTimer = setTimeout(() => refreshOtherDrafts(), OTHER_DRAFTS_REFRESH_DEBOUNCE_MS);
    };
    window.addEventListener("pagehide", flushDraft);
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener("pagehide", flushDraft);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("storage", onStorage);
      if (refreshTimer) clearTimeout(refreshTimer);
    };
  }, [flushDraft, refreshOtherDrafts]);

  useEffect(() => {
    if (!notice) return;
    const timer = setTimeout(() => setNotice(null), NOTICE_DURATION_MS);
    return () => clearTimeout(timer);
  }, [notice]);

  const save = useCallback(
    (targetNovelId: string, targetEpisodeId: string, nextContent: string) => {
      const seq = ++saveSeqRef.current;
      if (mountedRef.current) {
        setSaveState("saving");
        setSaveError(null);
      }
      saveChainRef.current = saveChainRef.current
        .catch(() => {})
        .then(() => saveEpisode(targetNovelId, targetEpisodeId, nextContent))
        .then((updated) => {
          // Before the mounted/seq checks below: whether the local backup is
          // still needed depends only on what the server now holds, even if
          // this component has since moved on to another episode.
          if (targetEpisodeId === currentEpisodeIdRef.current) setServerVersion(updated.updated_at, updated.content);
          // Only this session's own draft is touched: another tab's says
          // nothing about which version *its* text was based on.
          const ownContent = ownDraftRef.current.get(targetEpisodeId);
          if (ownContent !== undefined) {
            if (ownContent === updated.content) {
              clearDraft(targetEpisodeId);
              ownDraftRef.current.delete(targetEpisodeId);
            } else {
              // Newer text was typed here while this save was in flight: keep
              // it, now based on the version this save produced. (If this
              // write fails the draft keeps its old base, so loading it later
              // is flagged as older than the server's copy.)
              saveDraft(targetEpisodeId, { content: ownContent, baseUpdatedAt: updated.updated_at });
            }
          }
          if (targetEpisodeId === currentEpisodeIdRef.current) {
            // Listed drafts the server now holds are nothing left to offer.
            // Judged from the list in memory: rescanning storage on every save
            // would read every parked manuscript back.
            const held = otherDraftsRef.current.filter((d) => d.content === updated.content);
            if (held.length > 0) {
              held.forEach((d) => discardDraft(d.key));
              showOtherDrafts(otherDraftsRef.current.filter((d) => d.content !== updated.content));
            }
          }
          if (!mountedRef.current || seq !== saveSeqRef.current) return;
          setEpisode(updated);
          setSaveState("saved");
        })
        .catch((err) => {
          if (!mountedRef.current || seq !== saveSeqRef.current) return;
          setSaveError(describeError(err));
          setSaveState("error");
        });
    },
    [showOtherDrafts, setServerVersion]
  );

  useEffect(() => {
    if (!novelId || !episodeId) return;
    // Guards against this effect's own fetch resolving after novelId/episodeId
    // has already changed again (component stays mounted across param
    // changes on this route) — without it, a slow load for the episode we've
    // navigated away from could land after, and clobber, the next episode's
    // state. Also reset load/save state up front so a stale error or status
    // from the previous episode doesn't linger over the new one.
    let cancelled = false;
    // Also invalidates any in-flight save() from the previous episode — its
    // seq can no longer match once bumped here, so its response is ignored
    // instead of landing setEpisode/setSaveState calls for this new episode.
    saveSeqRef.current++;
    setEpisode(null);
    setContent("");
    setLoadError(null);
    setSaveState("idle");
    setSaveError(null);
    setNotice(null);
    showOtherDrafts([]);
    currentEpisodeIdRef.current = episodeId;
    setServerVersion("", "");
    // Chained after saveChainRef instead of fired directly: a quick
    // A -> B -> A navigation queues a flush save for A (below, on this
    // effect's cleanup) that may still be in flight when this same episode
    // is loaded again. Without waiting for it, this GET could race that
    // PATCH and win, loading pre-edit content over what was just flushed —
    // the user would then keep editing from a stale baseline and the next
    // save would silently drop the flushed edit.
    saveChainRef.current
      .catch(() => {})
      .then(() => fetchCurrentUserId()) // drafts are keyed by the account this token is for
      .then((userId) => {
        if (cancelled) return null;
        // This load writes to a slot of its own; drafts an earlier load left
        // stay in storage and show up in the list.
        startDraftSlot(episodeId, userId);
        ownDraftRef.current.delete(episodeId);
        return getEpisode(novelId, episodeId);
      })
      .then((ep) => {
        if (cancelled || ep === null) return;
        setServerVersion(ep.updated_at, ep.content);
        setEpisode(ep);
        setContent(ep.content);
        refreshOtherDrafts(true);
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(describeError(err));
      });

    return () => {
      cancelled = true;
      // Before anything else: this is also what runs when an expired session
      // routes away from the editor, so the text has to reach storage now.
      flushDraft();
      if (autosaveTimerRef.current) {
        clearTimeout(autosaveTimerRef.current);
        autosaveTimerRef.current = null;
      }
      const pending = pendingRef.current;
      if (pending) {
        pendingRef.current = null;
        // Goes through save() (and so through saveChainRef) rather than a
        // standalone saveEpisode() call, so this flush still serializes with
        // any save already in flight for the same episode instead of racing
        // it — the whole reason saveChainRef exists. Its state update is a
        // no-op once the seq bump below (or unmount) makes it stale.
        save(pending.novelId, pending.episodeId, pending.content);
      }
    };
  }, [novelId, episodeId]);

  function handleContentChange(next: string) {
    setContent(next);
    if (!novelId || !episodeId) return;
    draftPendingRef.current = { episodeId, content: next };
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    draftTimerRef.current = setTimeout(flushDraft, DRAFT_DEBOUNCE_MS);
    pendingRef.current = { novelId, episodeId, content: next };
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => {
      pendingRef.current = null;
      flushDraft(); // the draft must be on disk before the save it backs up
      save(novelId, episodeId, next);
    }, AUTOSAVE_DELAY_MS);
  }

  // Loading replaces what's on screen with the draft (and, through the usual
  // paths, saves it). The draft itself stays listed until the server holds the
  // same text, so it can be loaded again or discarded later.
  function loadOtherDraft(draft: StoredDraft) {
    const changedSince = draft.baseUpdatedAt !== serverUpdatedAt;
    const replacesText = content !== "" && content !== draft.content;
    if (
      (replacesText || changedSince) &&
      !window.confirm(
        [
          replacesText && "지금 화면의 내용이 이 초안으로 바뀝니다.",
          changedSince && "이 초안을 작성한 뒤 이 화가 다른 곳에서 수정되었습니다. 불러오면 그 수정 내용은 덮어쓰입니다.",
          "계속할까요?",
        ]
          .filter(Boolean)
          .join("\n")
      )
    ) {
      return;
    }
    handleContentChange(draft.content);
    setNotice("초안을 불러왔습니다.");
  }

  function discardOtherDraft(draft: StoredDraft) {
    discardDraft(draft.key);
    showOtherDrafts(otherDraftsRef.current.filter((d) => d.key !== draft.key));
  }

  function handleSaveNow() {
    if (!novelId || !episodeId) return;
    pendingRef.current = null;
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    flushDraft();
    save(novelId, episodeId, content);
  }

  if (loadError) {
    return (
      <div className="editor-page">
        <p className="editor-error">{loadError}</p>
      </div>
    );
  }

  if (!episode) {
    return (
      <div className="editor-page">
        <p>불러오는 중...</p>
      </div>
    );
  }

  return (
    <div className="editor-page">
      <div className="editor-header">
        <Link className="back-link" to={`/novels/${novelId}/episodes`}>
          ← 화 목록
        </Link>
        <h1>{episode.episode_index}화 작성</h1>
      </div>

      {notice && <p className="editor-notice">{notice}</p>}
      {otherDrafts.length > 0 && (
        <div className="editor-notice">
          <p>
            저장되지 않은 다른 초안이 {otherDrafts.length}개 있습니다. 다른 탭에서 작성 중이거나, 이전에 닫힌 탭·페이지에서
            남은 초안입니다. 각 탭은 자기 초안만 다시 저장하므로 서로 덮어쓰지 않습니다. 불러오기를 누르면 지금 화면의
            내용이 그 초안으로 바뀝니다.
          </p>
          {otherDrafts.length >= MAX_DRAFTS_PER_EPISODE && (
            <p>
              이 화의 초안이 가득 차(최대 {MAX_DRAFTS_PER_EPISODE}개) 최근에 쓰인 초안이 아닌 것이 없으면 새로 여는 탭은 자동 백업이
              꺼집니다. 필요 없는 초안은 버려 주세요.
            </p>
          )}
          <ul className="editor-draft-list">
            {otherDrafts.map((draft) => (
              <li key={draft.key}>
                <span className="editor-draft-preview">
                  {new Date(draft.savedAt).toLocaleString()} · {previewDraft(draft.content)}
                  {draft.baseUpdatedAt !== serverUpdatedAt && " · 이후 이 화가 수정됨"}
                </span>
                <span className="editor-actions">
                  <button type="button" onClick={() => loadOtherDraft(draft)}>
                    불러오기
                  </button>
                  <button type="button" onClick={() => discardOtherDraft(draft)}>
                    버리기
                  </button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <textarea
        className="editor-textarea"
        value={content}
        onChange={(e) => handleContentChange(e.target.value)}
        placeholder="원고를 입력하세요..."
      />

      <div className="editor-toolbar">
        <span className="editor-save-status">
          {saveState === "saving" && "저장 중..."}
          {saveState === "error" && saveError}
          {(saveState === "idle" || saveState === "saved") &&
            `마지막 저장: ${new Date(episode.updated_at).toLocaleTimeString()}`}
        </span>
        <div className="editor-actions">
          <button type="button" onClick={handleSaveNow} disabled={saveState === "saving"}>
            저장
          </button>
          <button type="button" disabled title="검증 실행은 준비 중입니다">
            검증 실행
          </button>
        </div>
      </div>
    </div>
  );
}
