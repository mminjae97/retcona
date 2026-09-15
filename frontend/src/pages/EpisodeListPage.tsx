// Episode (화) list for one novel (design doc 2.6 "열기": episode list -> editor)
// Selecting an existing episode opens it in the editor; "새 화 작성" starts a new one from here.
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { describeError } from "../api/client";
import { createEpisode, listEpisodes } from "../api/episodes";
import type { EpisodeSummary } from "../api/episodes";
import "./EpisodeListPage.css";

const STATUS_LABEL: Record<EpisodeSummary["status"], string> = {
  draft: "임시저장",
  submitted: "검증 완료",
};

export default function EpisodeListPage() {
  const { novelId } = useParams<{ novelId: string }>();
  const navigate = useNavigate();
  const [episodes, setEpisodes] = useState<EpisodeSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  // Holds the novelId currently being fetched (or null when idle) — guards
  // against a duplicate in-flight request for the SAME novel, without a
  // stale request for a PREVIOUS novel's resolution clearing the flag out
  // from under a newer, still-in-flight request for the current one (which
  // a plain boolean reset on every novelId change would allow).
  const loadingForRef = useRef<string | null>(null);
  // Lets an in-flight request from a previous novel (route param changed
  // without unmounting this page) recognize it's stale once it resolves,
  // instead of applying its result over the new novel's episode list.
  const currentNovelIdRef = useRef(novelId);

  function load() {
    if (!novelId || loadingForRef.current === novelId) return;
    loadingForRef.current = novelId;
    const requestNovelId = novelId;
    setError(null);
    listEpisodes(requestNovelId)
      .then((eps) => {
        if (currentNovelIdRef.current !== requestNovelId) return;
        setEpisodes(eps);
      })
      .catch((err) => {
        if (currentNovelIdRef.current !== requestNovelId) return;
        setError(describeError(err));
      })
      .finally(() => {
        if (loadingForRef.current === requestNovelId) {
          loadingForRef.current = null;
        }
      });
  }

  useEffect(() => {
    currentNovelIdRef.current = novelId;
    setEpisodes(null);
    setError(null);
    load();
  }, [novelId]);

  async function handleCreate() {
    if (!novelId || creating) return;
    setCreating(true);
    setError(null);
    try {
      const episode = await createEpisode(novelId);
      navigate(`/novels/${novelId}/episodes/${episode.id}`);
    } catch (err) {
      setError(describeError(err));
      setCreating(false);
    }
  }

  return (
    <div className="episode-list-page">
      <Link className="back-link" to="/mypage">
        ← 마이페이지
      </Link>
      <div className="section-header">
        <h1>화 목록</h1>
        <button type="button" onClick={handleCreate} disabled={creating}>
          {creating ? "생성 중..." : "+ 새 화 작성"}
        </button>
      </div>

      {error && (
        <p className="episode-list-error">
          {error} <button type="button" onClick={load}>다시 시도</button>
        </p>
      )}

      {episodes === null ? (
        !error && <p>불러오는 중...</p>
      ) : episodes.length === 0 ? (
        <p className="empty-state">아직 작성한 화가 없습니다.</p>
      ) : (
        <ul className="episode-list">
          {episodes.map((ep) => (
            <li key={ep.id} className="episode-row">
              <Link to={`/novels/${novelId}/episodes/${ep.id}`}>
                <span className="episode-index">{ep.episode_index}화</span>
                <span className={`episode-status status-${ep.status}`}>{STATUS_LABEL[ep.status]}</span>
                <span className="episode-updated">{new Date(ep.updated_at).toLocaleString()}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
