// Manuscript editor (design doc 2.2)
// Typing is saved automatically to a local draft (utils/draft.ts, debounced, and flushed when the page is
// hidden or the editor unmounts); the server only gets the text when the author presses Save (PATCH, doesn't
// call the AI pipeline). "Run validation" (2.2) saves unsaved text first, then asks the server to validate
// what's saved; a worker does it in the background while the author keeps writing, and the page polls the run
// (utils/validationRun.ts) and shows what it found — or that a later save has made it out of date.
// Editing a submitted episode flips its status back to draft (2.2).
// The draft is dropped once a save confirms it, so it survives an expired session, a network failure or a
// closed tab. Every tab (every page load) keeps its own draft and rewrites only that one; the drafts other tabs
// or earlier loads left are listed on the page and the author loads whichever one they want.
import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { Link, useBlocker, useParams } from "react-router-dom";
import { fetchCurrentUserId } from "../api/auth";
import { describeError } from "../api/client";
import { getEpisode, listFlags, saveEpisode } from "../api/episodes";
import type { EpisodePublic, ValidationRun } from "../api/episodes";
import {
  MAX_DRAFTS_PER_EPISODE,
  clearDraft,
  discardDraft,
  discardDraftIfContent,
  isDraftEventFor,
  isDraftsWipedEventFor,
  listOtherDrafts,
  loadDraft,
  releaseDraftCache,
  saveDraft,
  startDraftSlot,
} from "../utils/draft";
import type { StoredDraft } from "../utils/draft";
import { describeRunError, isRunOutdated, useValidationRun } from "../utils/validationRun";
import "./EditorPage.css";

// The local draft is written this long after typing pauses, not on every key
// press: stringifying and storing a long manuscript each time would make typing lag.
const DRAFT_DEBOUNCE_MS = 300;
// Another tab typing rewrites its draft every few hundred ms; the list only
// needs to catch up once that settles.
const OTHER_DRAFTS_REFRESH_DEBOUNCE_MS = 1000;
// How long the "draft loaded" notice stays up.
const NOTICE_DURATION_MS = 6000;
const LEAVE_UNSAVED_CONFIRM = "저장하지 않은 변경이 있고 이 브라우저에 임시저장되지 않았습니다. 나가면 내용이 사라집니다. 나갈까요?";

// First characters of a draft, counted in code points so an emoji isn't cut in half.
function previewDraft(content: string): string {
  if (content.length === 0) return "(빈 내용)";
  // Only the head is split into code points: this runs for every parked draft
  // on every render (each keystroke), and a chapter can be 100k characters.
  const shown = Array.from(content.slice(0, 82)).slice(0, 40).join("");
  return shown + (content.length > shown.length ? "…" : "");
}

type SaveState = "idle" | "saving" | "saved" | "error";

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
  // Whether the last local draft write went through. While it didn't, typed
  // text has no copy anywhere until the author saves, and the page says so.
  // Known gap: a non-throwing `localStorage.setItem` (storageSet) is treated
  // as durable here, but it isn't always — a private/incognito window in
  // current major browsers accepts writes all session and only wipes them on
  // close, and there's no reliable, cross-browser way to detect that from
  // script. The status line's wording (below) is hedged rather than naming
  // that case specifically, since it can't be told apart from the normal one.
  const [draftBackupOk, setDraftBackupOk] = useState(true);
  // Tracks in-flight/most-recent save to avoid an out-of-order save response
  // clobbering a newer one's result.
  const saveSeqRef = useRef(0);
  // Chains save requests so a later one (e.g. a save pressed for an episode
  // reopened while its previous save is still in flight) always waits for the
  // previous request to finish before sending — otherwise two in-flight PATCHes for the same episode
  // could commit out of order and the older one would silently overwrite
  // the newer content server-side, which seq alone (client-side response
  // ordering only) can't prevent.
  const saveChainRef = useRef<Promise<unknown>>(Promise.resolve());
  // True only while the component is actually mounted — separate from the
  // per-episode "cancelled" flag in the load effect below, since a save still
  // in flight when the editor is left is deliberately let finish (and still
  // updates `episode`/`saveState` if it turns out to be the current episode) but
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
  // ownDraftRef is a ref (mutating it alone doesn't schedule a render), but the
  // "drafts nearly full" warning below reads it directly at render time. Most
  // callers change it right before a state update that would re-render anyway
  // (e.g. setContent); the one that doesn't (the storage listener noticing
  // another tab reclaimed this session's own slot) calls this to force one.
  const [, forceRerender] = useReducer((c: number) => c + 1, 0);

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
    setDraftBackupOk(written);
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
      if (document.visibilityState !== "hidden") return;
      flushDraft();
    };
    // Another tab writing or removing a draft of this episode.
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    const onStorage = (e: StorageEvent) => {
      const id = currentEpisodeIdRef.current;
      if (!id) return;
      // Another tab just wiped this account's drafts (a deletion request went
      // through): this tab's own slot is gone too, so its backup is gone right
      // now, not just as of its next write.
      if (isDraftsWipedEventFor(id, e.key)) setDraftBackupOk(false);
      if (!isDraftEventFor(id, e.key)) return;
      // A removal under this episode's prefix can be another tab's makeRoom()
      // reclaiming *this* session's own stale slot (evicted for room, not by
      // anything this tab did) — ownDraftRef wouldn't otherwise learn its
      // slot is gone until its next write, overcounting the "drafts nearly
      // full" warning below in the meantime. loadDraft() re-checks storage
      // directly rather than assuming which key changed.
      if (e.newValue === null && ownDraftRef.current.has(id) && loadDraft(id) === null) {
        ownDraftRef.current.delete(id);
        // Mutating the ref alone doesn't schedule a render, and the other-
        // drafts list below is unaffected (it already excludes this tab's own
        // slot) — showOtherDrafts would just bail out on "nothing changed" and
        // the warning would stay stale until some unrelated render.
        forceRerender();
      }
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

  // Text the server doesn't have yet. Normally the local draft holds it, so
  // leaving is safe; without a draft, leaving loses it, so the browser asks first.
  const unsaved = episode !== null && content !== episode.content;
  const atRisk = unsaved && !draftBackupOk;
  useEffect(() => {
    if (!atRisk) return;
    const onBeforeUnload = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [atRisk]);
  // Same guard for a navigation within the app: the back-link, an App.tsx
  // route change, or AuthExpiryRedirect forcing everyone to /login when the
  // session ends — and, because this runs through the data router, browser
  // back/forward too, which a Link-only guard can't reach (the URL has
  // already changed by the time a popstate handler would see it).
  const blocker = useBlocker(atRisk);
  const validation = useValidationRun(novelId, episodeId);
  useEffect(() => {
    if (blocker.state !== "blocked") return;
    if (window.confirm(LEAVE_UNSAVED_CONFIRM)) blocker.proceed();
    else blocker.reset();
  }, [blocker]);

  // Resolves to whether the server took the text (for "run validation", which
  // validates only what's saved); never rejects.
  const save = useCallback(
    (targetNovelId: string, targetEpisodeId: string, nextContent: string): Promise<boolean> => {
      const seq = ++saveSeqRef.current;
      if (mountedRef.current) {
        setSaveState("saving");
        setSaveError(null);
      }
      const saved = saveChainRef.current
        .catch(() => {})
        .then(() => saveEpisode(targetNovelId, targetEpisodeId, nextContent))
        .then((updated) => {
          // Episode identity, not seq: saveChainRef fully serializes calls (a
          // second save's saveEpisode() doesn't even start until this whole
          // .then() has run), so responses can never arrive out of order —
          // seq would false-skip this block whenever a next save has already
          // been *called* (even if still queued behind this one), which is
          // the common case for back-to-back saves, not a rare race.
          // Whether the local backup is still needed depends only on what the
          // server now holds, even if this component has since moved on to
          // another episode.
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
              // Only what is still exactly that text in storage: the list in
              // memory can be a second behind, and its owner may have typed on.
              const removed = held.filter((d) => discardDraftIfContent(d.key, updated.content));
              showOtherDrafts(otherDraftsRef.current.filter((d) => !removed.includes(d)));
              if (removed.length < held.length) refreshOtherDrafts();
            }
          }
          if (!mountedRef.current || seq !== saveSeqRef.current) return true;
          setEpisode(updated);
          setSaveState("saved");
          return true;
        })
        .catch((err) => {
          if (!mountedRef.current || seq !== saveSeqRef.current) return false;
          setSaveError(describeError(err));
          setSaveState("error");
          // The text stays in the local draft and on screen; the author presses
          // Save again when ready. Nothing is sent on its own.
          return false;
        });
      saveChainRef.current = saved;
      return saved;
    },
    [showOtherDrafts, setServerVersion, refreshOtherDrafts]
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
    setDraftBackupOk(true);
    showOtherDrafts([]);
    currentEpisodeIdRef.current = episodeId;
    // Owner unknown until the account id arrives below: without this, ownerOf()
    // would fall back to the live getUserId() for storage events that land in
    // the gap, which can point at a different account by the time it resolves
    // (another tab signing in as someone else, or this account being deleted).
    startDraftSlot(episodeId, null);
    setServerVersion("", "");
    // Chained after saveChainRef instead of fired directly: a quick
    // A -> B -> A navigation can come back to A while the save the author
    // pressed there is still in flight. Without waiting for it, this GET could
    // race that PATCH and win, loading pre-edit content over what was just
    // saved — the user would then keep editing from a stale baseline and the
    // next save would silently drop the saved edit.
    saveChainRef.current
      .catch(() => {})
      // Together: the account (drafts are keyed by the one this token is for)
      // isn't needed until the episode has arrived.
      .then(() => (cancelled ? null : Promise.all([fetchCurrentUserId(), getEpisode(novelId, episodeId)])))
      .then((loaded) => {
        if (cancelled || loaded === null) return;
        const [userId, ep] = loaded;
        // This load writes to a slot of its own; drafts an earlier load left
        // stay in storage and show up in the list.
        startDraftSlot(episodeId, userId);
        ownDraftRef.current.delete(episodeId);
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
      // Nothing goes to the server on leaving: unsaved text stays in the local
      // draft, which this writes now — it is also what runs when an expired
      // session routes away from the editor.
      flushDraft();
      releaseDraftCache(episodeId);
    };
  }, [novelId, episodeId]);

  function handleContentChange(next: string) {
    setContent(next);
    if (!novelId || !episodeId) return;
    draftPendingRef.current = { episodeId, content: next };
    if (draftTimerRef.current) clearTimeout(draftTimerRef.current);
    draftTimerRef.current = setTimeout(flushDraft, DRAFT_DEBOUNCE_MS);
  }

  // Loading replaces what's on screen with the draft; it reaches the server when
  // the author saves. The draft itself stays listed until the server holds the
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
    flushDraft(); // the draft must be on disk before the save it backs up
    save(novelId, episodeId, content);
  }

  function handleValidate() {
    if (!novelId || !episodeId) return;
    const saveFirst = unsaved
      ? () => {
          flushDraft();
          return save(novelId, episodeId, content);
        }
      : undefined;
    validation.start(saveFirst);
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
          {/* otherDrafts excludes this tab's own slot, but the cap counts it:
              add 1 back only if this tab has actually written its own slot
              yet (ownDraftRef), since until then otherDrafts.length already
              *is* the full existing count and needs no adjustment. */}
          {otherDrafts.length + (episodeId && ownDraftRef.current.has(episodeId) ? 1 : 0) >=
            MAX_DRAFTS_PER_EPISODE && (
            <p>
              이 화의 초안이 가득 차(최대 {MAX_DRAFTS_PER_EPISODE}개) 최근에 쓰인 초안이 아닌 것이 없으면 새로 여는 탭은 임시저장이
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
          {saveState !== "saving" &&
            unsaved &&
            (draftBackupOk
              ? " · 저장하지 않은 변경이 있습니다 (이 브라우저에 임시저장됨 — 창을 닫으면 사라질 수도 있습니다)"
              : " · 저장하지 않은 변경이 있습니다. 이 브라우저에 임시저장할 수 없으니 저장 버튼을 눌러 주세요")}
        </span>
        <div className="editor-actions">
          <button type="button" onClick={handleSaveNow} disabled={saveState === "saving"}>
            저장
          </button>
          <button
            type="button"
            onClick={handleValidate}
            disabled={saveState === "saving" || validation.requesting || validation.active || content.trim() === ""}
            title={content.trim() === "" ? "원고를 입력한 뒤 검증할 수 있습니다" : undefined}
          >
            {validation.requesting ? "검증 요청 중..." : validation.active ? "검증 중..." : "검증 실행"}
          </button>
        </div>
      </div>

      <ValidationStatus
        novelId={novelId}
        episodeId={episodeId}
        run={validation.run}
        requestError={validation.requestError}
        episodeUpdatedAt={episode.updated_at}
        settingsPath={`/novels/${novelId}/settings`}
        resultPath={`/novels/${novelId}/episodes/${episodeId}/result`}
      />
    </div>
  );
}

// What the latest run found, or where it is: how many of the claims it
// extracted contradict the settings (appearance and location so far), with a
// link to the result screen (2.4), and the characters and locations it
// registered as new (7.4).
// How many flags the episode has now, and how many are still open: the
// result screen's accept/dismiss changes them after the run's summary was
// written. Fetched again whenever the latest run changes state. null until
// known (or if the request fails — the summary stands in).
function useFlagCounts(novelId: string | undefined, episodeId: string | undefined, run: ValidationRun | null) {
  const [counts, setCounts] = useState<{ total: number; open: number } | null>(null);
  const runKey = run ? `${run.id}:${run.status}` : "";
  useEffect(() => {
    setCounts(null);
    if (!novelId || !episodeId || !runKey) return;
    let cancelled = false;
    listFlags(novelId, episodeId)
      .then((flags) => {
        if (!cancelled) setCounts({ total: flags.length, open: flags.filter((flag) => flag.status === "open").length });
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [novelId, episodeId, runKey]);
  return counts;
}

function ValidationStatus({
  novelId,
  episodeId,
  run,
  requestError,
  episodeUpdatedAt,
  settingsPath,
  resultPath,
}: {
  novelId: string | undefined;
  episodeId: string | undefined;
  run: ValidationRun | null;
  requestError: string | null;
  episodeUpdatedAt: string;
  settingsPath: string;
  resultPath: string;
}) {
  const counts = useFlagCounts(novelId, episodeId, run);
  return (
    <>
      {/* A request that failed leaves the previous run's result in place below it. */}
      {requestError && (
        <p className="editor-validation editor-error" role="alert">
          {requestError}
        </p>
      )}
      {run && (
        <RunStatus
          run={run}
          counts={counts}
          episodeUpdatedAt={episodeUpdatedAt}
          settingsPath={settingsPath}
          resultPath={resultPath}
        />
      )}
    </>
  );
}

function RunStatus({
  run,
  counts,
  episodeUpdatedAt,
  settingsPath,
  resultPath,
}: {
  run: ValidationRun;
  counts: { total: number; open: number } | null;
  episodeUpdatedAt: string;
  settingsPath: string;
  resultPath: string;
}) {
  if (run.status === "queued" || run.status === "running") {
    return (
      <p className="editor-validation" role="status">
        {run.status === "queued" ? "검증을 기다리는 중입니다..." : "원고를 분석하는 중입니다..."} 계속 작성해도 됩니다.
      </p>
    );
  }
  if (run.status === "failed") {
    return (
      <p className="editor-validation editor-error" role="alert">
        {describeRunError(run.error)}
        {/* Only when an earlier run left something to show. */}
        {counts !== null && counts.total > 0 && (
          <>
            {" "}
            <Link to={resultPath}>이전 검증 결과 보기</Link>
          </>
        )}
      </p>
    );
  }
  // flags is missing on runs from before contradiction judgment: those only
  // extracted claims, and saying "nothing contradicts" would be a false all-clear.
  const { claims = 0, new_characters: characters = [], new_locations: locations = [] } = run.summary;
  // Open flags as they are now, once known; until then, as the run left them.
  const flags = run.summary.flags === undefined ? undefined : (counts?.open ?? run.summary.flags);
  const finishedAt = run.finished_at ? new Date(run.finished_at).toLocaleString() : "";
  return (
    <div className="editor-validation" role="status">
      <p>
        검증 완료{finishedAt && ` · ${finishedAt}`}: 설정과 대조할 서술 {claims}개를 찾았습니다.
        {flags !== undefined &&
          (flags > 0 ? ` 설정과 어긋나 보이는 곳이 ${flags}군데 있습니다.` : " 확인할 모순 후보는 없습니다.")}
        {/* Also when nothing is left to look at: dismissed flags are there to reopen. */}
        {flags !== undefined && (
          <>
            {" "}
            <Link to={resultPath}>검증 결과 보기</Link>
          </>
        )}
      </p>
      {characters.length > 0 && (
        <p>
          새로 등록된 인물: {characters.join(", ")} · <Link to={settingsPath}>설정에서 확인하기</Link>
        </p>
      )}
      {locations.length > 0 && <p>새로 등록된 장소: {locations.join(", ")}</p>}
      {characters.length === 0 && locations.length === 0 && <p>새로 등록된 인물·장소는 없습니다.</p>}
      {isRunOutdated(run, episodeUpdatedAt) && (
        <p className="editor-validation-outdated">
          이 결과 이후 원고가 수정되어 최신 상태가 아닙니다. 다시 검증하려면 검증 실행을 눌러 주세요.
        </p>
      )}
      <p className="editor-validation-note">지금은 인물의 외형과 장소의 특징만 설정과 대조합니다.</p>
    </div>
  );
}
