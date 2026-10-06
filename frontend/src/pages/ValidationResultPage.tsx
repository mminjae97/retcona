// Validation result screen (design doc 2.4, the core screen)
// Left: the manuscript, with the sentences flags point at highlighted. Right:
// the flags of the latest successful run, open ones first, most confident
// first (2.5). Clicking a flag's sentence scrolls the manuscript to it. Each
// open flag can be accepted (the manuscript is right: its value replaces the
// setting card's) or dismissed as a false positive; a dismissal can be undone.
// Or the setting it was judged against can be supplemented right there and the
// flag alone judged again (7.5) — the worker does it; the page polls until it's
// done.
// Above the flags, the sentences the extraction couldn't tie to one character —
// a "그" that fits several, a name several share — ask the author which it is
// (7.1.1); the pick is judged by the worker like a revalidation.
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError, describeError } from "../api/client";
import {
  actOnFlag,
  getEpisode,
  getLatestValidation,
  isRevalidating,
  listFlags,
  listPendingLinks,
  pickPendingLink,
  revalidateFlag,
} from "../api/episodes";
import type { EpisodePublic, Flag, FlagAction, PendingLink, ValidationRun } from "../api/episodes";
import { FIXED_ATTR_FIELDS } from "../api/settings";
import { describeRunError, isRunActive } from "../utils/validationRun";
import "./ValidationResultPage.css";

const ERROR_TYPES: Record<string, string> = {
  appearance: "외형 불일치",
  location: "장소 설정 불일치",
  behavior: "행동 불일치",
  spacetime: "시공간 모순",
};

const ATTRIBUTES: Record<string, string> = { ...FIXED_ATTR_FIELDS, features: "특징" };

// How often the page checks on revalidations in progress.
const REVALIDATION_POLL_MS = 2000;

type BusyAction = FlagAction | "revalidate";

// Why a revalidation failed (FlagRevalidation.error).
const REVALIDATION_ERRORS: Record<string, string> = {
  abandoned: "재검증이 너무 오래 걸려 중단되었습니다. 다시 시도해 주세요.",
  queue_unavailable: "지금은 재검증을 요청할 수 없습니다. 잠시 후 다시 시도해 주세요.",
  superseded: "새 재검증 요청으로 대체되었습니다.",
  flag_missing: "검증 결과가 바뀌었습니다. 새로고침해 주세요.",
  flag_handled: "재검증 중에 항목이 처리되었습니다.",
  card_missing: "설정 카드가 삭제되어 재검증할 수 없습니다.",
  setting_changed: "재검증 중에 설정이 다시 바뀌었습니다. 다시 재검증해 주세요.",
  inference_failed: "판정 모델을 실행하지 못했습니다. 잠시 후 다시 시도해 주세요.",
};

// Open flags first; within each group the server's order (most confident first).
function sortFlags(flags: Flag[]): Flag[] {
  return [...flags.filter((flag) => flag.status === "open"), ...flags.filter((flag) => flag.status !== "open")];
}

// 409 details are codes (backend/api/episodes.py).
function describeActionError(err: unknown): string {
  if (err instanceof ApiError && err.status === 404) {
    return "검증 결과가 바뀌었습니다. 새로고침해 주세요.";
  }
  if (err instanceof ApiError && err.status === 409) {
    if (err.message === "flag_card_missing") return "설정 카드가 삭제되어 반영할 수 없습니다.";
    if (err.message === "flag_no_value") return "이 항목은 반영할 값이 없습니다.";
    if (err.message === "flag_run_active") return "이 화의 검증이 진행 중입니다. 검증이 끝난 뒤 반영해 주세요.";
    if (err.message === "flag_outdated") return "검증 이후 원고가 수정되었습니다. 다시 검증한 뒤 반영해 주세요.";
    if (err.message === "flag_setting_changed")
      return "검증 이후 이 설정이 바뀌었습니다. 값을 고치지 않고 재검증하면 지금 설정과 다시 비교합니다.";
    return "이미 처리된 항목입니다. 새로고침해 주세요.";
  }
  return describeError(err);
}

// 409 details are codes (backend/api/episodes.py).
function describeLinkError(err: unknown): string {
  if (err instanceof ApiError && err.status === 409) {
    if (err.message === "link_run_active") return "이 화의 검증이 진행 중입니다. 검증이 끝난 뒤 선택해 주세요.";
    if (err.message === "link_card_missing") return "선택한 인물이 삭제되었습니다. 새로고침해 주세요.";
    if (err.message === "link_not_a_candidate") return "고를 수 없는 인물입니다. 새로고침해 주세요.";
    return "이미 처리된 항목입니다. 새로고침해 주세요.";
  }
  return describeError(err);
}

type Range = { start: number; end: number };

// Where `sentence` is in `content`, every occurrence (a short line of dialogue
// can repeat, and nothing says which one the model meant): as written, or else
// comparing letters and digits only — the model's copy of a sentence may
// differ from the manuscript in spacing, quotes or punctuation (as
// backend/pipeline/merge.py allows). `text` is wordChars(content), made once
// for all of a manuscript's flags.
function locateAll(content: string, text: WordChars, sentence: string): Range[] {
  if (!sentence) return [];
  sentence = sentence.normalize("NFC");
  const whole = (range: Range) => standsAlone(content, range);
  const found = occurrences(content, sentence)
    .map((at) => ({ start: at, end: at + sentence.length }))
    .filter(whole);
  if (found.length) return found;
  const wanted = wordChars(sentence).chars;
  if (!wanted) return [];
  return occurrences(text.chars, wanted)
    .map((at) => ({ start: text.starts[at], end: text.ends[at + wanted.length - 1] }))
    .filter(whole);
}

// The manuscript just before a sentence (the first place it's at), for a
// "그" that needs the sentences before it to be read: up to this many characters.
const CONTEXT_BEFORE = 80;

function textBefore(content: string, text: WordChars, sentence: string | null): string {
  const [first] = sentence ? locateAll(content, text, sentence) : [];
  if (!first) return "";
  const before = content.slice(Math.max(0, first.start - CONTEXT_BEFORE), first.start).trim();
  return first.start > CONTEXT_BEFORE && before ? `…${before}` : before;
}

// Whether a match is the sentence itself, not the tail or head of a longer
// word or sentence: no letter or digit runs on into it on either side ("네."
// isn't in "그렇네.").
function standsAlone(content: string, { start, end }: Range): boolean {
  const before = Array.from(content.slice(Math.max(0, start - 2), start)).pop() ?? "";
  const after = Array.from(content.slice(end, end + 2))[0] ?? "";
  return !/[\p{L}\p{N}]/u.test(before) && !/[\p{L}\p{N}]/u.test(after);
}

function occurrences(haystack: string, needle: string): number[] {
  const found: number[] = [];
  for (let at = haystack.indexOf(needle); at !== -1; at = haystack.indexOf(needle, at + needle.length)) {
    found.push(at);
  }
  return found;
}

// The letters and digits of `text`, lowercased, with where each came from
// (UTF-16 offsets of the original character, per unit of `chars`).
type WordChars = { chars: string; starts: number[]; ends: number[] };

function wordChars(text: string): WordChars {
  let chars = "";
  const starts: number[] = [];
  const ends: number[] = [];
  let offset = 0;
  for (const char of text) {
    if (/[\p{L}\p{N}]/u.test(char)) {
      const lower = char.toLowerCase();
      chars += lower;
      for (let unit = 0; unit < lower.length; unit++) {
        starts.push(offset);
        ends.push(offset + char.length);
      }
    }
    offset += char.length;
  }
  return { chars, starts, ends };
}

// A stretch of the manuscript: plain text, or a sentence one or more flags
// point at (those flags' ids).
type Segment = { text: string; flagIds: string[] };

// Splits the manuscript around each flag's sentence, at every place it occurs.
// Returns, per flag, the indexes of the segments holding it, in reading order
// (empty for a flag whose sentence isn't in the text: the manuscript was
// edited after the run, or the model worded it its own way; its card says
// so). `content` is NFC and `text` its wordChars, made once per manuscript.
function segment(content: string, text: WordChars, flags: Flag[]): { segments: Segment[]; places: Map<string, number[]> } {
  const ranges = new Map<string, Range & { flagIds: string[] }>();
  for (const flag of flags) {
    for (const found of locateAll(content, text, flag.evidence_text)) {
      const key = `${found.start}:${found.end}`;
      const range = ranges.get(key);
      if (range) range.flagIds.push(flag.id);
      else ranges.set(key, { ...found, flagIds: [flag.id] });
    }
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
  const places = new Map<string, number[]>(flags.map((flag) => [flag.id, []]));
  segments.forEach((part, index) => {
    for (const id of new Set(part.flagIds)) places.get(id)?.push(index);
  });
  return { segments, places };
}

export default function ValidationResultPage() {
  const { novelId, episodeId } = useParams<{ novelId: string; episodeId: string }>();
  const [episode, setEpisode] = useState<EpisodePublic | null>(null);
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [flags, setFlags] = useState<Flag[]>([]);
  // The claims waiting for the author to pick a card, in manuscript order.
  const [pendingLinks, setPendingLinks] = useState<PendingLink[]>([]);
  // The one being picked for, and which (a candidate's id, or "skip").
  const [linkBusy, setLinkBusy] = useState<{ id: string; pick: string } | null>(null);
  const [linkErrors, setLinkErrors] = useState<Record<string, string>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // The flag whose sentence was last jumped to, drawn more strongly.
  const [activeFlagId, setActiveFlagId] = useState<string | null>(null);
  // The flag being acted on, and how (to label the right button).
  const [busy, setBusy] = useState<{ flagId: string; action: BusyAction } | null>(null);
  const [actionErrors, setActionErrors] = useState<Record<string, string>>({});
  // Not errors: e.g. an accept that went through but whose follow-up refresh didn't.
  const [actionNotices, setActionNotices] = useState<Record<string, string>>({});
  // The highlighted segments, by segment index.
  const highlightRefs = useRef(new Map<number, HTMLElement>());
  // The segment last jumped to (drawn more strongly), and for each flag which
  // of its occurrences a click goes to next.
  const [activeSegment, setActiveSegment] = useState<number | null>(null);
  const jumpCursor = useRef(new Map<string, number>());
  // Set the moment a request starts, so a second click before the next
  // render (a double click) doesn't send another.
  const actingRef = useRef(false);

  const load = useCallback(() => {
    if (!novelId || !episodeId) return () => {};
    let cancelled = false;
    setLoading(true);
    setLoadError(null);
    Promise.all([
      getEpisode(novelId, episodeId),
      getLatestValidation(novelId, episodeId),
      listFlags(novelId, episodeId),
      // Not what the page is for: without it the flags are still shown.
      listPendingLinks(novelId, episodeId).catch((): PendingLink[] => []),
    ])
      .then(([loadedEpisode, latest, loadedFlags, loadedLinks]) => {
        if (cancelled) return;
        setEpisode(loadedEpisode);
        setRun(latest);
        setFlags(sortFlags(loadedFlags));
        setPendingLinks(loadedLinks);
        setLinkErrors({});
        setActionErrors({});
        setActionNotices({});
        // Segment indexes and jump positions belong to the text just replaced.
        setActiveFlagId(null);
        setActiveSegment(null);
        jumpCursor.current.clear();
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

  // While any flag is being revalidated, check on it until it's done. Only
  // the flags are refreshed: the manuscript and jump positions stay.
  const revalidating = flags.some(isRevalidating);
  useEffect(() => {
    if (!revalidating || !novelId || !episodeId) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      listFlags(novelId, episodeId)
        .then((loaded) => {
          if (!cancelled) setFlags(sortFlags(loaded));
        })
        // Tried again on the next tick: the flags still show "revalidating".
        .catch(() => {
          if (!cancelled) setFlags((current) => [...current]);
        });
    }, REVALIDATION_POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [revalidating, flags, novelId, episodeId]);

  // While a pick is being judged, check on it until it's done: the list (it
  // leaves it when done) and the flags (what it found, if anything).
  const judgingLinks = pendingLinks.some((link) => link.status === "judging");
  useEffect(() => {
    if (!judgingLinks || !novelId || !episodeId) return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      Promise.all([listPendingLinks(novelId, episodeId), listFlags(novelId, episodeId)])
        .then(([loadedLinks, loadedFlags]) => {
          if (cancelled) return;
          setPendingLinks(loadedLinks);
          setFlags(sortFlags(loadedFlags));
        })
        // Tried again on the next tick: the pick still shows "judging".
        .catch(() => {
          if (!cancelled) setPendingLinks((current) => [...current]);
        });
    }, REVALIDATION_POLL_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [judgingLinks, pendingLinks, novelId, episodeId]);

  // NFC, as the backend compares text: a manuscript pasted from some systems
  // stores Hangul decomposed (NFD), and the model's sentences are composed.
  // Shown as NFC too, which reads the same.
  const content = useMemo(() => (episode?.content ?? "").normalize("NFC"), [episode?.content]);
  const contentWords = useMemo(() => wordChars(content), [content]);
  const { segments, places } = useMemo(
    () => segment(content, contentWords, flags),
    [content, contentWords, flags],
  );

  // Scrolls to the flag's sentence; with the sentence in several places, each
  // click goes to the next one.
  function jumpTo(flag: Flag) {
    const indexes = places.get(flag.id) ?? [];
    if (!indexes.length) return;
    const next = (jumpCursor.current.get(flag.id) ?? -1) + 1;
    const index = indexes[next % indexes.length];
    jumpCursor.current.set(flag.id, next % indexes.length);
    setActiveFlagId(flag.id);
    setActiveSegment(index);
    highlightRefs.current.get(index)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  async function act(flag: Flag, action: FlagAction) {
    if (!novelId || !episodeId || actingRef.current) return;
    if (action === "accept") {
      const attribute = ATTRIBUTES[flag.attribute ?? ""] ?? flag.attribute;
      const confirmed = window.confirm(
        `${flag.subject_name}의 설정 "${attribute}"을(를) 원고 내용으로 바꿉니다.\n\n` +
          `지금 설정: ${flag.reference_text}\n바뀔 값: ${flag.value}\n\n` +
          "이 설정과 비교해 이미 검증한 다른 화는 다시 검증해야 반영됩니다.",
      );
      if (!confirmed) return;
    }
    actingRef.current = true;
    setBusy({ flagId: flag.id, action });
    setActionErrors(({ [flag.id]: _, ...rest }) => rest);
    setActionNotices(({ [flag.id]: _, ...rest }) => rest);
    try {
      const updated = await actOnFlag(novelId, episodeId, flag.id, action);
      setFlags((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      if (action === "accept") {
        // Accepting also updates the episode's other flags on the same
        // attribute (the new setting value, or resolved with it). If this
        // fails, the accept itself still went through and is shown; the
        // others catch up on the next load.
        try {
          setFlags(sortFlags(await listFlags(novelId, episodeId)));
        } catch {
          setActionNotices((current) => ({
            ...current,
            [flag.id]: "반영했습니다. 같은 속성의 다른 항목은 새로고침하면 갱신됩니다.",
          }));
        }
      }
    } catch (err) {
      setActionErrors((current) => ({ ...current, [flag.id]: describeActionError(err) }));
    } finally {
      actingRef.current = false;
      setBusy(null);
    }
  }

  // Judges the flag again; with a new `setting`, the card takes it first. The
  // list is reloaded after: supplementing a setting sends the episode's other
  // flags on that attribute to be judged again too. Returns whether it went
  // through, so the card can close its form.
  async function revalidate(flag: Flag, setting?: string): Promise<boolean> {
    if (!novelId || !episodeId || actingRef.current) return false;
    actingRef.current = true;
    setBusy({ flagId: flag.id, action: "revalidate" });
    setActionErrors(({ [flag.id]: _, ...rest }) => rest);
    setActionNotices(({ [flag.id]: _, ...rest }) => rest);
    try {
      const updated = await revalidateFlag(novelId, episodeId, flag.id, setting);
      setFlags((current) => current.map((item) => (item.id === updated.id ? updated : item)));
      try {
        setFlags(sortFlags(await listFlags(novelId, episodeId)));
      } catch {
        // The request went through; the flag shows it, and polling catches the rest up.
      }
      return true;
    } catch (err) {
      setActionErrors((current) => ({ ...current, [flag.id]: describeActionError(err) }));
      // A supplemented setting may have been saved even though the job wasn't
      // queued: the flags then show the new value to try again with.
      listFlags(novelId, episodeId)
        .then((loaded) => setFlags(sortFlags(loaded)))
        .catch(() => {});
      return false;
    } finally {
      actingRef.current = false;
      setBusy(null);
    }
  }

  // The author's pick for a claim: a candidate, or null for "해당 없음". The
  // list is reloaded after (a pick starts being judged, a skip leaves it).
  async function pickLink(link: PendingLink, subjectId: string | null) {
    if (!novelId || !episodeId || actingRef.current) return;
    actingRef.current = true;
    setLinkBusy({ id: link.id, pick: subjectId ?? "skip" });
    setLinkErrors(({ [link.id]: _, ...rest }) => rest);
    try {
      const result = await pickPendingLink(novelId, episodeId, link.id, subjectId);
      // Shown at once, then the list is reloaded; if that doesn't get through,
      // the pick went through all the same, and the polling catches up.
      setPendingLinks((current) =>
        result.outcome === "skipped"
          ? current.filter((item) => item.id !== link.id)
          : current.map((item) => (item.id === link.id ? { ...item, status: "judging", picked_id: subjectId } : item)),
      );
      listPendingLinks(novelId, episodeId)
        .then(setPendingLinks)
        .catch(() => {});
    } catch (err) {
      setLinkErrors((current) => ({ ...current, [link.id]: describeLinkError(err) }));
      // A 409 means the list is out of date (handled elsewhere, replaced by a new run).
      listPendingLinks(novelId, episodeId)
        .then(setPendingLinks)
        .catch(() => {});
    } finally {
      actingRef.current = false;
      setLinkBusy(null);
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
  // The flags come from the last run that succeeded (`run` is the latest one,
  // which may be newer: still going, or failed). "submitted" means the saved
  // manuscript is what that run validated; a save since made it a draft (2.2).
  const outdated = flags.length > 0 && episode.status !== "submitted";

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
            마지막 검증이 실패했습니다: {describeRunError(run.error)} 그 전에 성공한 검증이 있으면 아래에 그 결과를 보여 줍니다.
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
          {content ? (
            segments.map((part, index) =>
              part.flagIds.length ? (
                <mark
                  key={index}
                  ref={(element) => {
                    if (element) highlightRefs.current.set(index, element);
                    else highlightRefs.current.delete(index);
                  }}
                  className={[
                    "result-highlight",
                    part.flagIds.every((id) => flags.find((flag) => flag.id === id)?.status !== "open") &&
                      "result-highlight-handled",
                    index === activeSegment && "result-highlight-active",
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
          {pendingLinks.length > 0 && (
            <div className="link-section" aria-label="연결이 필요한 문장">
              <h2>연결이 필요한 문장 {pendingLinks.length}개</h2>
              <p className="result-hint">
                누구에 대한 문장인지 정할 수 없었습니다. 알맞은 인물을 고르면 그 인물의 설정과 바로 비교하고, 다음
                검증에서도 같은 선택을 씁니다.
              </p>
              <ol className="flag-list">
                {pendingLinks.map((link) => (
                  <LinkCard
                    key={link.id}
                    link={link}
                    before={textBefore(content, contentWords, link.evidence_text)}
                    runActive={isRunActive(run)}
                    busy={linkBusy?.id === link.id ? linkBusy.pick : null}
                    disabled={linkBusy !== null}
                    error={linkErrors[link.id]}
                    onPick={(subjectId) => pickLink(link, subjectId)}
                  />
                ))}
              </ol>
            </div>
          )}
          <h2>
            모순 후보 {flags.length}개{flags.length > 0 && ` · 확인할 항목 ${openCount}개`}
          </h2>
          {flags.length === 0 ? (
            <p className="result-empty">{describeNoFlags(run)}</p>
          ) : (
            <ol className="flag-list">
              {flags.map((flag) => (
                <FlagCard
                  key={flag.id}
                  flag={flag}
                  places={places.get(flag.id)?.length ?? 0}
                  outdated={outdated}
                  runActive={isRunActive(run)}
                  active={flag.id === activeFlagId}
                  busy={busy?.flagId === flag.id ? busy.action : null}
                  disabled={busy !== null}
                  error={actionErrors[flag.id]}
                  notice={actionNotices[flag.id]}
                  settingsPath={`/novels/${novelId}/settings`}
                  onJump={() => jumpTo(flag)}
                  onAct={(action) => act(flag, action)}
                  onRevalidate={(setting) => revalidate(flag, setting)}
                />
              ))}
            </ol>
          )}
          <p className="result-hint">
            반영: 원고가 맞다면 설정을 원고 내용으로 바꿉니다. 오탐 해제: 모순이 아니라면 항목을 닫습니다. 설정 보완 후
            재검증: 설정을 고친 뒤 이 항목만 다시 판단합니다.
          </p>
        </section>
      </div>
    </div>
  );
}

// Why the list is empty. "Nothing contradicts" only for a run that got as far
// as judging: not one that failed, is still going, or predates judgment
// (its summary has no flags count).
function describeNoFlags(run: ValidationRun | null): string {
  if (run === null) return "검증 결과가 없습니다.";
  if (run.status !== "succeeded") return "표시할 모순 후보가 없습니다.";
  if (run.summary.flags === undefined) return "모순 판정이 추가되기 전의 검증 결과입니다. 원고 화면에서 다시 검증해 주세요.";
  return "설정과 어긋나는 서술을 찾지 못했습니다.";
}

function candidateLabel(candidate: { name: string; aliases: string[] }): string {
  return candidate.aliases.length > 0 ? `${candidate.name} (${candidate.aliases.join(", ")})` : candidate.name;
}

function LinkCard({
  link,
  before,
  runActive,
  busy,
  disabled,
  error,
  onPick,
}: {
  link: PendingLink;
  // The manuscript just before its sentence.
  before: string;
  runActive: boolean;
  // Which pick is being sent: a candidate's id, or "skip".
  busy: string | null;
  disabled: boolean;
  error: string | undefined;
  onPick: (subjectId: string | null) => void;
}) {
  const judging = link.status === "judging";
  const picked = link.candidates.find((candidate) => candidate.id === link.picked_id);
  const blocked = runActive ? "이 화의 검증이 진행 중입니다. 검증이 끝난 뒤 선택할 수 있습니다." : undefined;
  return (
    <li className="flag-card link-card">
      <p className="link-question">
        {link.subject_name ? `"${link.subject_name}"은(는) 어느 인물인가요?` : "이 문장은 누구에 대한 내용인가요?"}
      </p>
      <p className="link-sentence">
        {before && <span className="flag-missing">{before} </span>}
        <strong>{link.evidence_text}</strong>
      </p>
      <dl className="flag-body">
        {Object.entries(link.attributes).map(([key, value]) => (
          <Fragment key={key}>
            <dt>{ATTRIBUTES[key] ?? key}</dt>
            <dd>{value}</dd>
          </Fragment>
        ))}
      </dl>
      {judging ? (
        <p className="flag-state" role="status">
          {picked ? `${picked.name}의 설정과 비교하는 중...` : "설정과 비교하는 중..."}
        </p>
      ) : (
        <div className="flag-actions">
          {link.candidates.map((candidate) => (
            <button
              key={candidate.id}
              type="button"
              onClick={() => onPick(candidate.id)}
              disabled={disabled || runActive}
              title={blocked}
            >
              {busy === candidate.id ? "처리 중..." : candidateLabel(candidate)}
            </button>
          ))}
          <button
            type="button"
            onClick={() => onPick(null)}
            disabled={disabled || runActive}
            title={blocked ?? "이 문장은 위 인물 누구에 대한 내용도 아닙니다."}
          >
            {busy === "skip" ? "처리 중..." : "해당 없음"}
          </button>
        </div>
      )}
      {error && (
        <p className="result-error" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

function FlagCard({
  flag,
  places,
  outdated,
  runActive,
  active,
  busy,
  disabled,
  error,
  notice,
  settingsPath,
  onJump,
  onAct,
  onRevalidate,
}: {
  flag: Flag;
  // How many places in the manuscript hold its sentence.
  places: number;
  outdated: boolean;
  runActive: boolean;
  active: boolean;
  // The action in progress on this flag, if any.
  busy: BusyAction | null;
  disabled: boolean;
  error: string | undefined;
  notice: string | undefined;
  settingsPath: string;
  onJump: () => void;
  onAct: (action: FlagAction) => void;
  onRevalidate: (setting?: string) => Promise<boolean>;
}) {
  const attribute = ATTRIBUTES[flag.attribute ?? ""] ?? flag.attribute;
  // The "supplement the setting" form: open, and what's typed in it.
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const revalidating = isRevalidating(flag);
  const revalidation = flag.revalidation;
  // Only a flag on a card that's still there, and not while a run is going
  // (it replaces this run's flags when it finishes).
  const canRevalidate = flag.status === "open" && flag.subject_id !== null && !!flag.attribute && !runActive;

  function openForm() {
    setDraft(flag.reference_text ?? "");
    setFormError(null);
    setEditing(true);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const value = draft.trim();
    if (!value) {
      setFormError("설정 값을 입력해 주세요.");
      return;
    }
    // Unchanged: judged against the card as it is (it may have changed on
    // the settings screen since).
    const changed = value !== (flag.reference_text ?? "").trim();
    if (await onRevalidate(changed ? value : undefined)) setEditing(false);
  }
  // Why accept can't be pressed now, if it can't: the run would bring the
  // flag back, or the sentence (and its value) may be gone.
  const acceptBlocked = runActive
    ? "이 화의 검증이 진행 중입니다. 검증이 끝난 뒤 반영할 수 있습니다."
    : outdated
      ? "원고가 검증 이후 수정되었습니다. 다시 검증한 뒤 반영할 수 있습니다."
      : undefined;
  return (
    <li className={`flag-card flag-${flag.status}${active ? " flag-active" : ""}`}>
      <div className="flag-title">
        <strong>{ERROR_TYPES[flag.error_type] ?? flag.error_type}</strong>
        {flag.confidence === null ? (
          flag.status === "open" && (
            <span className="flag-confidence" title="설정이 바뀌어 아직 새 설정과 비교하지 않았습니다">
              다시 검증 필요
            </span>
          )
        ) : (
          <span className="flag-confidence" title="판정 모델이 모순이라고 본 확률">
            모순 가능성 {Math.round(flag.confidence * 100)}%
          </span>
        )}
      </div>
      <p className="flag-subject">
        {flag.subject_name}
        {attribute && ` · ${attribute}`}
      </p>
      <dl className="flag-body">
        <dt>원고</dt>
        <dd>
          {places > 0 ? (
            <>
              <button type="button" className="flag-evidence" onClick={onJump} title="원고에서 이 문장 보기">
                {flag.evidence_text}
              </button>
              {places > 1 && <span className="flag-missing"> (원고에 {places}번 나옴 · 누를 때마다 다음 위치)</span>}
            </>
          ) : (
            <>
              {flag.evidence_text}{" "}
              <span className="flag-missing">
                {/* Unedited, it's the model's own wording (a claim with no sentence) that isn't there. */}
                {outdated ? "(지금 원고에서 찾을 수 없음)" : "(원고에서 이 문장의 위치를 찾지 못함)"}
              </span>
            </>
          )}
        </dd>
        <dt>설정</dt>
        <dd>{flag.reference_text}</dd>
      </dl>
      {flag.status === "open" && (
        <div className="flag-actions">
          <button
            type="button"
            onClick={() => onAct("accept")}
            // Only against the manuscript this run validated: after an edit the
            // sentence may be gone, and its value with it.
            disabled={disabled || !flag.value || !flag.subject_id || acceptBlocked !== undefined}
            title={acceptBlocked}
          >
            {busy === "accept" ? "처리 중..." : "반영"}
          </button>
          <button type="button" onClick={() => onAct("dismiss")} disabled={disabled}>
            {busy === "dismiss" ? "처리 중..." : "오탐 해제"}
          </button>
          {!editing && (
            <button
              type="button"
              onClick={openForm}
              disabled={disabled || revalidating || !canRevalidate}
              title={
                runActive
                  ? "이 화의 검증이 진행 중입니다. 검증이 끝난 뒤 재검증할 수 있습니다."
                  : flag.subject_id === null
                    ? "설정 카드가 삭제되어 재검증할 수 없습니다."
                    : undefined
              }
            >
              설정 보완 후 재검증
            </button>
          )}
        </div>
      )}
      {flag.status === "open" && editing && (
        <form className="flag-revalidate" onSubmit={submit}>
          <label>
            {flag.subject_name}의 {attribute} 설정
            <input
              type="text"
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              maxLength={500}
              disabled={busy === "revalidate"}
              autoFocus
            />
          </label>
          <p className="flag-state">
            설정 카드의 값이 이 값으로 바뀌고, 이 항목과 같은 속성의 다른 항목을 다시 판단합니다. 값을 그대로 두면 지금
            설정과 다시 비교합니다.
            {flag.subject_kind === "character" && (
              <>
                {" "}
                <Link to={settingsPath}>다른 설정은 설정 화면에서</Link>
              </>
            )}
          </p>
          {formError && (
            <p className="result-error" role="alert">
              {formError}
            </p>
          )}
          <div className="flag-actions">
            <button type="submit" disabled={disabled || !canRevalidate}>
              {busy === "revalidate" ? "요청 중..." : "재검증"}
            </button>
            <button type="button" onClick={() => setEditing(false)} disabled={busy === "revalidate"}>
              취소
            </button>
          </div>
        </form>
      )}
      {revalidating && (
        <p className="flag-state" role="status">
          재검증 중...
        </p>
      )}
      {revalidation?.status === "failed" && flag.status === "open" && (
        <p className="result-error" role="alert">
          재검증 실패: {REVALIDATION_ERRORS[revalidation.error ?? ""] ?? "알 수 없는 오류가 발생했습니다."}
        </p>
      )}
      {revalidation?.status === "succeeded" && revalidation.outcome === "contradicts" && flag.status === "open" && (
        <p className="flag-state">재검증 결과: 지금 설정과도 어긋납니다.</p>
      )}
      {flag.status === "dismissed" && (
        <div className="flag-actions">
          <span className="flag-state">오탐으로 해제함</span>
          <button type="button" onClick={() => onAct("reopen")} disabled={disabled}>
            {busy === "reopen" ? "처리 중..." : "다시 열기"}
          </button>
        </div>
      )}
      {flag.status === "accepted" && <p className="flag-state">설정에 반영함</p>}
      {flag.status === "resolved" && <p className="flag-state">같은 속성의 다른 항목을 반영해 설정과 맞게 됨</p>}
      {flag.status === "resolved_by_revalidation" && (
        <p className="flag-state">
          재검증으로 해소됨
          {revalidation?.outcome === "resolved" &&
            (revalidation.setting === null ? " · 설정 값이 비어 비교할 대상이 없음" : ` · 설정: ${revalidation.setting}`)}
        </p>
      )}
      {error && (
        <p className="result-error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="flag-state" role="status">
          {notice}
        </p>
      )}
    </li>
  );
}
