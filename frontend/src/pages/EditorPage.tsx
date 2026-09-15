// Manuscript editor (design doc 2.2)
// Autosave (debounced, doesn't call the AI pipeline) + explicit save, both hit the same
// PATCH endpoint — the only difference is what triggers them. "Run validation" (2.2, 8.2)
// stays disabled: it depends on QueueClient (infra/queue_client.py), which isn't implemented yet.
// Editing a submitted episode flips its status back to draft and shows a "not up to date" banner.
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { describeError } from "../api/client";
import { getEpisode, saveEpisode } from "../api/episodes";
import type { EpisodePublic } from "../api/episodes";
import "./EditorPage.css";

const AUTOSAVE_DELAY_MS = 2000;

type SaveState = "idle" | "saving" | "saved" | "error";

export default function EditorPage() {
  const { novelId, episodeId } = useParams<{ novelId: string; episodeId: string }>();
  const [episode, setEpisode] = useState<EpisodePublic | null>(null);
  const [content, setContent] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  // Whether this episode had validation results (status "submitted") when the
  // editor opened it — drives the "results are stale" banner once an edit
  // flips it back to draft, without needing to fetch flags here.
  const hadResultsAtLoadRef = useRef(false);
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tracks in-flight/most-recent save to avoid an out-of-order autosave
  // response clobbering a newer explicit save's result.
  const saveSeqRef = useRef(0);

  useEffect(() => {
    if (!novelId || !episodeId) return;
    getEpisode(novelId, episodeId)
      .then((ep) => {
        setEpisode(ep);
        setContent(ep.content);
        hadResultsAtLoadRef.current = ep.status === "submitted";
      })
      .catch((err) => setLoadError(describeError(err)));
  }, [novelId, episodeId]);

  useEffect(() => {
    return () => {
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    };
  }, []);

  const save = useCallback(
    async (nextContent: string) => {
      if (!novelId || !episodeId) return;
      const seq = ++saveSeqRef.current;
      setSaveState("saving");
      setSaveError(null);
      try {
        const updated = await saveEpisode(novelId, episodeId, nextContent);
        if (seq !== saveSeqRef.current) return;
        setEpisode(updated);
        setSaveState("saved");
      } catch (err) {
        if (seq !== saveSeqRef.current) return;
        setSaveError(describeError(err));
        setSaveState("error");
      }
    },
    [novelId, episodeId]
  );

  function handleContentChange(next: string) {
    setContent(next);
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => save(next), AUTOSAVE_DELAY_MS);
  }

  function handleSaveNow() {
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    save(content);
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

  const showStaleBanner = hadResultsAtLoadRef.current && episode.status === "draft";

  return (
    <div className="editor-page">
      <div className="editor-header">
        <Link className="back-link" to={`/novels/${novelId}/episodes`}>
          ← 화 목록
        </Link>
        <h1>{episode.episode_index}화 작성</h1>
      </div>

      {showStaleBanner && (
        <p className="editor-banner">원고가 수정되어 검증 결과가 최신 상태가 아닙니다.</p>
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
          {saveState === "saved" && `마지막 저장: ${new Date(episode.updated_at).toLocaleTimeString()}`}
          {saveState === "error" && saveError}
          {saveState === "idle" && `마지막 저장: ${new Date(episode.updated_at).toLocaleTimeString()}`}
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
