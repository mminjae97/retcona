// Validation result screen (design doc 2.4, the core screen)
// Left: the manuscript, with the sentences flags point at highlighted. Right:
// the flags of the latest successful run, open ones first, most confident
// first (2.5). Clicking a flag's sentence scrolls the manuscript to it. Each
// open flag can be accepted (the manuscript is right: its value replaces the
// setting card's) or dismissed as a false positive; a dismissal can be undone.
// "Supplement settings and revalidate that flag" (7.5) comes with stage 3; for
// now a character flag links to the settings screen.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, describeError } from "../api/client";
import { actOnFlag, getEpisode, getLatestValidation, listFlags } from "../api/episodes";
import type { EpisodePublic, Flag, FlagAction, ValidationRun } from "../api/episodes";
import { FIXED_ATTR_FIELDS } from "../api/settings";
import { describeRunError, isRunActive, isRunOutdated } from "../utils/validationRun";
import "./ValidationResultPage.css";

const ERROR_TYPES: Record<string, string> = {
  appearance: "외형 불일치",
  location: "장소 설정 불일치",
  behavior: "행동 불일치",
  spacetime: "시공간 모순",
};

const ATTRIBUTES: Record<string, string> = { ...FIXED_ATTR_FIELDS, features: "특징" };

// Open flags first; within each group the server's order (most confident first).
function sortFlags(flags: Flag[]): Flag[] {
  return [...flags.filter((flag) => flag.status === "open"), ...flags.filter((flag) => flag.status !== "open")];
}

function describeActionError(err: unknown): string {
  if (err instanceof ApiError && err.status === 404) {
    return "검증 결과가 바뀌었습니다. 새로고침해 주세요.";
  }
  if (err instanceof ApiError && err.status === 409) {
    if (err.message.includes("card")) return "설정 카드가 삭제되어 반영할 수 없습니다.";
    if (err.message.includes("value")) return "이 항목은 반영할 값이 없습니다.";
    return "이미 처리된 항목입니다. 새로고침해 주세요.";
  }
  return describeError(err);
}

// A stretch of the manuscript: plain text, or a sentence one or more flags
// point at (those flags' ids).
type Segment = { text: string; flagIds: string[] };

// Splits the manuscript around each flag's sentence (its first occurrence).
// Flags whose sentence isn't in the text any more (the manuscript was edited
// after the run) are left out, and their cards say so.
function segment(content: string, flags: Flag[]): { segments: Segment[]; located: Set<string> } {
  const ranges = new Map<string, { start: number; end: number; flagIds: string[] }>();
  const located = new Set<string>();
  for (const flag of flags) {
    const start = flag.evidence_text ? content.indexOf(flag.evidence_text) : -1;
    if (start === -1) continue;
    located.add(flag.id);
    const key = `${start}:${flag.evidence_text.length}`;
    const range = ranges.get(key);
    if (range) range.flagIds.push(flag.id);
    else ranges.set(key, { start, end: start + flag.evidence_text.length, flagIds: [flag.id] });
  }
  // Overlapping sentences (one inside another) are drawn as one highlight
  // starting at the earlier one; the later one's flags join it.
  const sorted = [...ranges.values()].sort((a, b) => a.start - b.start || b.end - a.end);
  const segments: Segment[] = [];
  let at = 0;
  for (const range of sorted) {
    if (range.start < at) {
      const last = segments[segments.length - 1];
      if (last?.flagIds.length) {
        last.flagIds.push(...range.flagIds);
        if (range.end > at) {
          last.text += content.slice(at, range.end);
          at = range.end;
        }
      }
      continue;
    }
    if (range.start > at) segments.push({ text: content.slice(at, range.start), flagIds: [] });
    segments.push({ text: content.slice(range.start, range.end), flagIds: [...range.flagIds] });
    at = range.end;
  }
  if (at < content.length) segments.push({ text: content.slice(at), flagIds: [] });
  return { segments, located };
}

export default function ValidationResultPage() {
  const { novelId, episodeId } = useParams<{ novelId: string; episodeId: string }>();
  const [episode, setEpisode] = useState<EpisodePublic | null>(null);
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // The flag whose sentence was last jumped to, drawn more strongly.
  const [activeFlagId, setActiveFlagId] = useState<string | null>(null);
  const [busyFlagId, setBusyFlagId] = useState<string | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  const highlightRefs = useRef(new Map<string, HTMLElement>());

  const load = useCallback(() => {
    if (!novelId || !episodeId) return () => {};
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([getEpisode(novelId, episodeId), getLatestValidation(novelId, episodeId), listFlags(novelId, episodeId)])
      .then(([loadedEpisode, latest, loadedFlags]) => {
        if (cancelled) return;
        setEpisode(loadedEpisode);
        setRun(latest);
        setFlags(sortFlags(loadedFlags));
        setActionErrors({});
      })
      .catch((err) => {
        if (!cancelled) setLoadError(describeError(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [novelId, episodeId]);

  useEffect(() => load(), [load]);

  const { segments, located } = useMemo(
    () => segment(episode?.content ?? "", flags),
    [episode?.content, flags],
  );

  function jumpTo(flag: Flag) {
    setActiveFlagId(flag.id);
    highlightRefs.current.get(flag.id)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function act(flag: Flag, action: FlagAction) {
    if (!novelId || !episodeId || busyFlagId) return;
    if (action === "accept") {
      const attribute = ATTRIBUTES[flag.attribute ?? ""] ?? flag.attribute;
      const confirmed = window.confirm(
        `${flag.subject_name}의 설정 "${attribute}"을(를) 원고 내용으로 바꿉니다.\n\n` +
          `지금 설정: ${flag.reference_text}\n바뀔 값: ${flag.value}\n\n` +
          "이 설정과 비교해 이미 검증한 다른 화는 다시 검증해야 반영됩니다.",
      );
      if (!confirmed) return;
    }
    setBusyFlagId(flag.id);
    setActionErrors(({ [flag.id]: _, ...rest }) => rest);
    try {
      const updated = await actOnFlag(novelId, episodeId, flag.id, action);
      setFlags((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    } catch (err) {
      setActionErrors((current) => ({ ...current, [flag.id]: describeActionError(err) }));
    } finally {
      setBusyFlagId(null);
    }
  }

  const editorPath = `/novels/${novelId}/episodes/${episodeId}`;

  if (loading && !episode) return <div className="result-page">불러오는 중...</div>;
  if (loadError || !episode) {
    return (
      <div className="result-page">
        <Link to={editorPath} className="back-link">
          ← 원고로 돌아가기
        </Link>
        <p className="result-error" role="alert">
          {loadError ?? "검증 결과를 불러오지 못했습니다."}{" "}
          <button type="button" onClick={load}>
            다시 시도
          </button>
        </p>
      </div>
    );
  }

  const openCount = flags.filter((flag) => flag.status === "open").length;
  // The flags come from the last run that succeeded; `run` is the latest one,
  // which may be newer (still going, or failed).
  const outdated = run !== null && run.status === "succeeded" && isRunOutdated(run, episode.updated_at);

  return (
    <div className="result-page">
      <header className="result-header">
        <Link to={editorPath} className="back-link">
          ← 원고로 돌아가기
        </Link>
        <h1>{episode.episode_index}화 검증 결과</h1>
        {run?.status === "succeeded" && run.finished_at && (
          <p className="result-meta">검증 완료 · {new Date(run.finished_at).toLocaleString()}</p>
        )}
        {run === null && <p className="result-meta">아직 이 화를 검증하지 않았습니다. 원고 화면에서 검증을 실행해 주세요.</p>}
        {isRunActive(run) && <p className="result-notice">새 검증이 진행 중입니다. 끝나면 새로고침해 주세요.</p>}
        {run?.status === "failed" && (
          <p className="result-notice">
            마지막 검증이 실패했습니다: {describeRunError(run.error)} 아래는 그 전에 성공한 검증의 결과입니다.
          </p>
        )}
        {outdated && (
          <p className="result-notice">
            이 결과 이후 원고가 수정되어 최신 상태가 아닙니다. 원고 화면에서 검증을 다시 실행해 주세요.
          </p>
        )}
      </header>

      <div className="result-layout">
        <section className="result-manuscript" aria-label="원고">
          {episode.content ? (
            segments.map((part, index) =>
              part.flagIds.length ? (
                <mark
                  key={index}
                  ref={(element) => {
                    for (const id of part.flagIds) {
                      if (element) highlightRefs.current.set(id, element);
                      else highlightRefs.current.delete(id);
                    }
                  }}
                  className={[
                    "result-highlight",
                    part.flagIds.every((id) => flags.find((flag) => flag.id === id)?.status !== "open") &&
                      "result-highlight-handled",
                    activeFlagId !== null && part.flagIds.includes(activeFlagId) && "result-highlight-active",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                >
                  {part.text}
                </mark>
              ) : (
                <span key={index}>{part.text}</span>
              ),
            )
          ) : (
            <p className="result-empty">원고가 비어 있습니다.</p>
          )}
        </section>

        <section className="result-flags" aria-label="모순 후보">
          <h2>
            모순 후보 {flags.length}개{flags.length > 0 && ` · 확인할 항목 ${openCount}개`}
          </h2>
          {flags.length === 0 ? (
            <p className="result-empty">
              {run === null ? "검증 결과가 없습니다." : "설정과 어긋나는 서술을 찾지 못했습니다."}
            </p>
          ) : (
            <ol className="flag-list">
              {flags.map((flag) => (
                <FlagCard
                  key={flag.id}
                  flag={flag}
                  located={located.has(flag.id)}
                  active={flag.id === activeFlagId}
                  busy={busyFlagId === flag.id}
                  disabled={busyFlagId !== null}
                  error={actionErrors[flag.id]}
                  settingsPath={`/novels/${novelId}/settings`}
                  onJump={() => jumpTo(flag)}
                  onAct={(action) => act(flag, action)}
                />
              ))}
            </ol>
          )}
          <p className="result-hint">
            반영: 원고가 맞다면 설정을 원고 내용으로 바꿉니다. 오탐 해제: 모순이 아니라면 항목을 닫습니다. 설정에 없던 규칙
            때문이라면 설정을 보완한 뒤 다시 검증해 주세요.
          </p>
        </section>
      </div>
    </div>
  );
}

function FlagCard({
  flag,
  located,
  active,
  busy,
  disabled,
  error,
  settingsPath,
  onJump,
  onAct,
}: {
  flag: Flag;
  located: boolean;
  active: boolean;
  busy: boolean;
  disabled: boolean;
  error: string | undefined;
  settingsPath: string;
  onJump: () => void;
  onAct: (action: FlagAction) => void;
}) {
  const attribute = ATTRIBUTES[flag.attribute ?? ""] ?? flag.attribute;
  return (
    <li className={`flag-card flag-${flag.status}${active ? " flag-active" : ""}`}>
      <div className="flag-title">
        <strong>{ERROR_TYPES[flag.error_type] ?? flag.error_type}</strong>
        <span className="flag-confidence" title="판정 모델이 모순이라고 본 확률">
          모순 가능성 {Math.round(flag.confidence * 100)}%
        </span>
      </div>
      <p className="flag-subject">
        {flag.subject_name}
        {attribute && ` · ${attribute}`}
      </p>
      <dl className="flag-body">
        <dt>원고</dt>
        <dd>
          {located ? (
            <button type="button" className="flag-evidence" onClick={onJump} title="원고에서 이 문장 보기">
              {flag.evidence_text}
            </button>
          ) : (
            <>
              {flag.evidence_text} <span className="flag-missing">(지금 원고에서 찾을 수 없음)</span>
            </>
          )}
        </dd>
        <dt>설정</dt>
        <dd>{flag.reference_text}</dd>
      </dl>
      {flag.status === "open" && (
        <div className="flag-actions">
          <button type="button" onClick={() => onAct("accept")} disabled={disabled || !flag.value || !flag.subject_id}>
            {busy ? "처리 중..." : "반영"}
          </button>
          <button type="button" onClick={() => onAct("dismiss")} disabled={disabled}>
            오탐 해제
          </button>
          {flag.subject_kind === "character" && <Link to={settingsPath}>설정 보완</Link>}
        </div>
      )}
      {flag.status === "dismissed" && (
        <div className="flag-actions">
          <span className="flag-state">오탐으로 해제함</span>
          <button type="button" onClick={() => onAct("reopen")} disabled={disabled}>
            {busy ? "처리 중..." : "다시 열기"}
          </button>
        </div>
      )}
      {flag.status === "accepted" && <p className="flag-state">설정에 반영함</p>}
      {flag.status === "resolved_by_revalidation" && <p className="flag-state">재검증으로 해소됨</p>}
      {error && (
        <p className="result-error" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}
