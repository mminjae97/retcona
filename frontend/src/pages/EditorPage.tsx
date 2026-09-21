// Manuscript editor (design doc 2.2)
// Autosave (debounced, doesn't call the AI pipeline) + explicit save, both hit the same
// PATCH endpoint — the only difference is what triggers them. "Run validation" (2.2, 8.2)
// stays disabled: it depends on QueueClient (infra/queue_client.py), which isn't implemented yet.
// Editing a submitted episode flips its status back to draft (2.2).
// Typing is also mirrored to a local draft (utils/draft.ts, debounced, and flushed when the page is hidden or
// the editor unmounts) until a save confirms it, so text survives an expired session, a network failure or a
// closed tab and is offered back on the next open.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { describeError } from "../api/client";
import { getEpisode, saveEpisode } from "../api/episodes";
import type { EpisodePublic } from "../api/episodes";
import {
  TAB_ID,
  addConflictDraft,
  clearDraft,
  loadConflictDrafts,
  loadDraft,
  removeConflictDraft,
  saveDraft,
} from "../utils/draft";
import type { Draft } from "../utils/draft";
import { claimEpisode } from "../utils/editorLock";
import "./EditorPage.css";

const AUTOSAVE_DELAY_MS = 2000;
// Much shorter than the autosave delay so the local draft is on disk before the
// server save fires, but coalescing keystrokes: stringifying and storing a long
// manuscript on every key press would make typing lag.
const DRAFT_DEBOUNCE_MS = 300;

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
  // Local drafts that can't be restored automatically because the episode
  // changed on the server after they were written — the author decides.
  const [conflictDrafts, setConflictDrafts] = useState<Draft[]>([]);
  // Another tab already has this episode open (and owns its local draft).
  const [otherTabOpen, setOtherTabOpen] = useState(false);
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
  const draftTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const draftPendingRef = useRef<{ episodeId: string; content: string } | null>(null);
  // Episodes another tab owns the draft of: this tab leaves their local draft
  // alone entirely (no restoring, writing, rebasing or clearing it).
  const foreignEpisodesRef = useRef(new Set<string>());

  const flushDraft = useCallback(() => {
    if (draftTimerRef.current) {
      clearTimeout(draftTimerRef.current);
      draftTimerRef.current = null;
    }
    const pending = draftPendingRef.current;
    if (!pending) return;
    draftPendingRef.current = null;
    if (foreignEpisodesRef.current.has(pending.episodeId)) return;
    const written = saveDraft(pending.episodeId, {
      content: pending.content,
      baseUpdatedAt: serverUpdatedAtRef.current,
    });
    // If the write failed, the copy already in storage is older than what the
    // author has typed. Leaving it would let a later save "rebase" it onto
    // the new server version and restore it over their newer text — no draft
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
    window.addEventListener("pagehide", flushDraft);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", flushDraft);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [flushDraft]);

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
          if (targetEpisodeId === currentEpisodeIdRef.current) {
            serverUpdatedAtRef.current = updated.updated_at;
          }
          const draft = foreignEpisodesRef.current.has(targetEpisodeId) ? null : loadDraft(targetEpisodeId);
          if (draft) {
            if (draft.content === updated.content) {
              clearDraft(targetEpisodeId);
            } else if (draft.writer === TAB_ID) {
              // Newer text was typed here while this save was in flight: keep
              // it, now based on the version this save produced. (If this
              // write fails the draft keeps its old base, so a later restore
              // is treated as a conflict rather than overwriting anything.)
              // A draft another tab wrote is left alone: this save says
              // nothing about what version *its* text was based on.
              saveDraft(targetEpisodeId, { ...draft, baseUpdatedAt: updated.updated_at });
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
    setConflictDrafts([]);
    setOtherTabOpen(false);
    let releaseClaim = () => {};
    currentEpisodeIdRef.current = episodeId;
    serverUpdatedAtRef.current = "";
    // Chained after saveChainRef instead of fired directly: a quick
    // A -> B -> A navigation queues a flush save for A (below, on this
    // effect's cleanup) that may still be in flight when this same episode
    // is loaded again. Without waiting for it, this GET could race that
    // PATCH and win, loading pre-edit content over what was just flushed —
    // the user would then keep editing from a stale baseline and the next
    // save would silently drop the flushed edit.
    saveChainRef.current
      .catch(() => {})
      .then(() => claimEpisode(episodeId))
      .then((claim) => {
        if (cancelled) {
          claim.release(); // the cleanup below already ran, so it can't release this one
          return null;
        }
        releaseClaim = claim.release;
        if (!claim.owned) foreignEpisodesRef.current.add(episodeId);
        return getEpisode(novelId, episodeId);
      })
      .then((ep) => {
        if (cancelled || ep === null) return;
        serverUpdatedAtRef.current = ep.updated_at;
        setEpisode(ep);
        setContent(ep.content);

        // Another tab has this episode open and owns its local draft: don't
        // touch it, and don't back this tab's typing up over it.
        const foreign = foreignEpisodesRef.current.has(episodeId);
        setOtherTabOpen(foreign);
        if (foreign) return;

        let held: Draft[] = [];
        const draft = loadDraft(episodeId);
        if (draft && draft.content !== ep.content) {
          if (draft.baseUpdatedAt === ep.updated_at) {
            // Written on top of exactly this version, so nothing newer exists
            // to overwrite: put it back and save it.
            setNotice("저장되지 않았던 초안을 복구했습니다.");
            handleContentChange(draft.content);
          } else if (addConflictDraft(episodeId, draft)) {
            // The server's copy moved on after this draft was written. Parked
            // beside any earlier ones rather than replacing them.
            clearDraft(episodeId);
          } else {
            // Couldn't park it (storage full, or the list is at its cap). The
            // regular copy is the same size, so freeing it may be what makes
            // room; if it still doesn't fit, put it back untouched and hold
            // it in memory so this page load can still offer it — the next
            // keystroke rewrites the regular slot, which must not be the only
            // place it lives.
            clearDraft(episodeId);
            if (!addConflictDraft(episodeId, draft)) {
              saveDraft(episodeId, draft);
              held = [draft];
            }
          }
        } else if (draft) {
          clearDraft(episodeId); // already saved
        }
        setConflictDrafts([...loadConflictDrafts(episodeId), ...held]);
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
      releaseClaim();
      foreignEpisodesRef.current.delete(episodeId);
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

  function restoreConflictDraft(draft: Draft) {
    if (!episodeId) return;
    // What's on screen is about to be replaced: park it too, so restoring is
    // never a one-way trip (it shows up in the list and can be swapped back).
    // The draft being restored is removed first, which frees the slot the
    // parked text needs if the list was full.
    removeConflictDraft(episodeId, draft);
    const replaced: Draft | null =
      content && content !== draft.content
        ? { content, baseUpdatedAt: serverUpdatedAtRef.current, savedAt: Date.now() }
        : null;
    // Already listed (an identical draft is parked): nothing to add, and
    // adding it to the state again would show one text as two rows.
    const alreadyListed = replaced !== null && conflictDrafts.some((d) => d.content === replaced.content);
    const parked = replaced === null || alreadyListed || addConflictDraft(episodeId, replaced);
    if (
      !parked &&
      !window.confirm("지금 화면의 내용을 보관할 공간이 없어, 초안으로 복구하면 화면의 내용이 사라집니다. 계속할까요?")
    ) {
      addConflictDraft(episodeId, draft); // undo the removal above
      return;
    }
    setConflictDrafts((prev) => {
      const rest = prev.filter((d) => d !== draft);
      return replaced && parked && !alreadyListed ? [...rest, replaced] : rest;
    });
    handleContentChange(draft.content);
  }

  function discardConflictDraft(draft: Draft) {
    if (!episodeId) return;
    removeConflictDraft(episodeId, draft);
    // A draft held only in memory (see the load path) may also still sit in
    // the regular slot; discarding it must remove that copy as well.
    if (loadDraft(episodeId)?.content === draft.content) clearDraft(episodeId);
    setConflictDrafts((prev) => prev.filter((d) => d !== draft));
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
      {otherTabOpen && (
        <p className="editor-notice editor-notice-warning">
          이 화가 다른 탭에서도 열려 있습니다. 이 탭에서는 작성 중인 글의 자동 백업(초안)이 꺼져 있고, 저장은 마지막에
          저장한 내용이 남습니다. 한 탭에서만 편집하는 것을 권장합니다.
        </p>
      )}
      {conflictDrafts.length > 0 && (
        <div className="editor-notice editor-notice-warning">
          <p>
            이 기기에 자동으로 복구하지 않은 초안이 {conflictDrafts.length}개 있습니다. 저장된 뒤 이 화가 다른 곳에서
            수정되어, 덮어쓰지 않도록 남겨 두었습니다. 초안으로 복구하면 지금 화면의 내용은 이 목록으로 옮겨져 다시
            되돌릴 수 있습니다.
          </p>
          <ul className="editor-draft-list">
            {conflictDrafts.map((draft) => (
              <li key={`${draft.savedAt}-${draft.content.length}`}>
                <span className="editor-draft-preview">
                  {new Date(draft.savedAt).toLocaleString()} · {previewDraft(draft.content)}
                </span>
                <span className="editor-actions">
                  <button type="button" onClick={() => restoreConflictDraft(draft)}>
                    초안으로 복구
                  </button>
                  <button type="button" onClick={() => discardConflictDraft(draft)}>
                    초안 버리기
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
