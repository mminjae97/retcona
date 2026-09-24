// "Run validation" state for one episode (design doc 2.2): the latest run, a
// request in flight, and polling while a run is queued or running (the worker
// processes it in the background; the author can keep writing meanwhile).
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, describeError } from "../api/client";
import { getLatestValidation, requestValidation } from "../api/episodes";
import type { ValidationRun } from "../api/episodes";

// How often a queued/running run is checked on.
const POLL_INTERVAL_MS = 2000;

export function isRunActive(run: ValidationRun | null): boolean {
  return run !== null && (run.status === "queued" || run.status === "running");
}

// Why a finished run failed, in words for the author. The codes are the
// backend's (pipeline/validate_episode.py, api/episodes.py).
export function describeRunError(code: string | null): string {
  switch (code) {
    case "abandoned":
      return "검증이 제시간에 끝나지 않았습니다. 다시 실행해 주세요.";
    case "queue_unavailable":
      return "검증을 시작하지 못했습니다. 잠시 후 다시 시도해주세요.";
    case "episode_missing":
      return "이 화를 찾을 수 없어 검증하지 못했습니다.";
    case "empty_manuscript":
      return "원고가 비어 있어 검증하지 못했습니다.";
    case "llm_failed":
      return "원고 분석 서버에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.";
    case "bad_llm_response":
      return "원고 분석 결과를 해석하지 못했습니다. 다시 실행해 주세요.";
    case "inference_failed":
      return "설정과 대조하는 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.";
    default:
      return "검증 중 오류가 발생했습니다. 잠시 후 다시 시도해주세요.";
  }
}

function describeRequestError(err: unknown): string {
  if (err instanceof ApiError && err.status === 422) return "원고가 비어 있어 검증할 수 없습니다.";
  if (err instanceof ApiError && err.status === 503) return "지금은 검증을 시작할 수 없습니다. 잠시 후 다시 시도해주세요.";
  return describeError(err);
}

// Whether a finished run's result still describes the saved manuscript: a
// save after it (or during it) makes it out of date (2.2).
export function isRunOutdated(run: ValidationRun, episodeUpdatedAt: string): boolean {
  return run.content_updated_at !== null && Date.parse(run.content_updated_at) !== Date.parse(episodeUpdatedAt);
}

export function useValidationRun(novelId: string | undefined, episodeId: string | undefined) {
  const [run, setRun] = useState<ValidationRun | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  // The episode this hook is currently for, so a response that arrives after
  // the editor has moved to another episode is dropped.
  const episodeKeyRef = useRef("");
  const episodeKey = `${novelId}/${episodeId}`;

  useEffect(() => {
    episodeKeyRef.current = episodeKey;
    setRun(null);
    setRequesting(false);
    setRequestError(null);
    if (!novelId || !episodeId) return;
    let cancelled = false;
    getLatestValidation(novelId, episodeId)
      // A run this page just requested is newer than whatever this finds.
      .then((latest) => {
        if (!cancelled) setRun((current) => current ?? latest);
      })
      // The editor works without it; the next request or poll shows the state.
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [novelId, episodeId, episodeKey]);

  const active = isRunActive(run);
  useEffect(() => {
    if (!active || !novelId || !episodeId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      timer = setTimeout(() => {
        getLatestValidation(novelId, episodeId)
          .then((latest) => {
            if (cancelled) return;
            setRun(latest);
            // Still going: keep checking. (A finished one ends this effect
            // through `active` instead.)
            if (isRunActive(latest)) schedule();
          })
          // A failed check (network blip) is retried on the same schedule.
          .catch(() => {
            if (!cancelled) schedule();
          });
      }, POLL_INTERVAL_MS);
    };
    schedule();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [active, novelId, episodeId]);

  // `saveFirst`, when given, saves the manuscript and says whether that
  // worked: the server validates what's saved (2.2), so unsaved text is saved
  // before the request, and a failed save (which shows its own error) stops it.
  const start = useCallback(
    async (saveFirst?: () => Promise<boolean>) => {
      if (!novelId || !episodeId) return;
      const key = episodeKey;
      setRequesting(true);
      setRequestError(null);
      try {
        if (saveFirst && !(await saveFirst())) return;
        if (episodeKeyRef.current !== key) return;
        const started = await requestValidation(novelId, episodeId);
        if (episodeKeyRef.current === key) setRun(started);
      } catch (err) {
        if (episodeKeyRef.current === key) setRequestError(describeRequestError(err));
      } finally {
        if (episodeKeyRef.current === key) setRequesting(false);
      }
    },
    [novelId, episodeId, episodeKey]
  );

  return { run, active, requesting, requestError, start };
}
