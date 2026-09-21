// Manuscript editor (design doc 2.2)
// Autosave (debounced, doesn't call the AI pipeline) + explicit save, both hit the same
// PATCH endpoint — the only difference is what triggers them. "Run validation" (2.2, 8.2)
// stays disabled: it depends on QueueClient (infra/queue_client.py), which isn't implemented yet.
// Editing a submitted episode flips its status back to draft (2.2).
// Every keystroke is also mirrored to a local draft (utils/draft.ts) until a save confirms it, so text
// survives an expired session, a network failure or a closed tab and is offered back on the next open.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { describeError } from "../api/client";
import { getEpisode, saveEpisode } from "../api/episodes";
import type { EpisodePublic } from "../api/episodes";
import {
  clearConflictDraft,
  clearDraft,
  loadConflictDraft,
  loadDraft,
  saveConflictDraft,
  saveDraft,
} from "../utils/draft";
import type { Draft } from "../utils/draft";
import "./EditorPage.css";

const AUTOSAVE_DELAY_MS = 2000;

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
  // A local draft that can't be restored automatically because the episode
  // changed on the server after it was written — the author decides.
  const [conflictDraft, setConflictDraft] = useState<Draft | null>(null);
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
          const draft = loadDraft(targetEpisodeId);
          if (draft) {
            if (draft.content === updated.content) {
              clearDraft(targetEpisodeId);
            } else {
              // Newer text was typed while this save was in flight: keep it,
              // now based on the version this save produced.
              saveDraft(targetEpisodeId, { content: draft.content, baseUpdatedAt: updated.updated_at });
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
    []
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
    setConflictDraft(null);
    // Chained after saveChainRef instead of fired directly: a quick
    // A -> B -> A navigation queues a flush save for A (below, on this
    // effect's cleanup) that may still be in flight when this same episode
    // is loaded again. Without waiting for it, this GET could race that
    // PATCH and win, loading pre-edit content over what was just flushed —
    // the user would then keep editing from a stale baseline and the next
    // save would silently drop the flushed edit.
    saveChainRef.current
      .catch(() => {})
      .then(() => getEpisode(novelId, episodeId))
      .then((ep) => {
        if (cancelled) return;
        setEpisode(ep);
        setContent(ep.content);

        const draft = loadDraft(episodeId);
        if (draft && draft.content !== ep.content) {
          if (draft.baseUpdatedAt === ep.updated_at) {
            // Written on top of exactly this version, so nothing newer exists
            // to overwrite: put it back and save it.
            setNotice("저장되지 않았던 초안을 복구했습니다.");
            handleContentChange(draft.content, ep.updated_at);
          } else {
            // The server's copy moved on after this draft was written.
            saveConflictDraft(episodeId, draft);
            clearDraft(episodeId);
          }
        } else if (draft) {
          clearDraft(episodeId); // already saved
        }
        setConflictDraft(loadConflictDraft(episodeId));
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadError(describeError(err));
      });

    return () => {
      cancelled = true;
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

  function handleContentChange(next: string, baseUpdatedAt = episode?.updated_at ?? "") {
    setContent(next);
    if (!novelId || !episodeId) return;
    saveDraft(episodeId, { content: next, baseUpdatedAt });
    pendingRef.current = { novelId, episodeId, content: next };
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => {
      pendingRef.current = null;
      save(novelId, episodeId, next);
    }, AUTOSAVE_DELAY_MS);
  }

  function restoreConflictDraft() {
    if (!conflictDraft || !episodeId) return;
    handleContentChange(conflictDraft.content);
    clearConflictDraft(episodeId);
    setConflictDraft(null);
  }

  function discardConflictDraft() {
    if (!episodeId) return;
    clearConflictDraft(episodeId);
    setConflictDraft(null);
  }

  function handleSaveNow() {
    if (!novelId || !episodeId) return;
    pendingRef.current = null;
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
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
      {conflictDraft && (
        <div className="editor-notice editor-notice-warning">
          <p>
            이 기기에 저장되지 않은 초안이 있지만, 그 사이 이 화가 다른 곳에서 수정되어 자동으로 복구하지 않았습니다.
            초안으로 복구하면 지금 화면의 내용이 초안으로 바뀝니다.
          </p>
          <div className="editor-actions">
            <button type="button" onClick={restoreConflictDraft}>
              초안으로 복구
            </button>
            <button type="button" onClick={discardConflictDraft}>
              초안 버리기
            </button>
          </div>
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
