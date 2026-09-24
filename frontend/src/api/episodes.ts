// Episode (화) API calls (design doc 2.2).

import { apiFetch } from "./client";

export interface EpisodeSummary {
  id: string;
  episode_index: number;
  status: "draft" | "submitted";
  updated_at: string;
}

export interface EpisodePublic extends EpisodeSummary {
  content: string;
}

export function listEpisodes(novelId: string): Promise<EpisodeSummary[]> {
  return apiFetch<EpisodeSummary[]>(`/novels/${novelId}/episodes`);
}

export function createEpisode(novelId: string, content = ""): Promise<EpisodePublic> {
  return apiFetch<EpisodePublic>(`/novels/${novelId}/episodes`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function getEpisode(novelId: string, episodeId: string): Promise<EpisodePublic> {
  return apiFetch<EpisodePublic>(`/novels/${novelId}/episodes/${episodeId}`);
}

export function saveEpisode(novelId: string, episodeId: string, content: string): Promise<EpisodePublic> {
  return apiFetch<EpisodePublic>(`/novels/${novelId}/episodes/${episodeId}`, {
    method: "PATCH",
    body: JSON.stringify({ content }),
  });
}

// "Run validation" (2.2): the server records a run and a worker processes it;
// the editor polls the latest run until it finishes.
export type ValidationRunStatus = "queued" | "running" | "succeeded" | "failed";

export type ValidationRunError =
  | "abandoned"
  | "queue_unavailable"
  | "episode_missing"
  | "empty_manuscript"
  | "llm_failed"
  | "bad_llm_response"
  | "inference_failed"
  | "internal";

export interface ValidationRunSummary {
  claims?: number;
  dropped_claims?: number;
  new_characters?: string[];
  new_locations?: string[];
  // How many claims contradict the settings (appearance, location).
  flags?: number;
}

export interface ValidationRun {
  id: string;
  episode_id: string;
  status: ValidationRunStatus;
  error: ValidationRunError | string | null;
  summary: ValidationRunSummary;
  // The episode's updated_at as of the content this run validated.
  content_updated_at: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

// Starts a run on the episode's saved content — or, while one is already
// queued or running, returns that one.
export function requestValidation(novelId: string, episodeId: string): Promise<ValidationRun> {
  return apiFetch<ValidationRun>(`/novels/${novelId}/episodes/${episodeId}/validations`, { method: "POST" });
}

// null when the episode has never been validated (204).
export async function getLatestValidation(novelId: string, episodeId: string): Promise<ValidationRun | null> {
  return (await apiFetch<ValidationRun | undefined>(`/novels/${novelId}/episodes/${episodeId}/validations/latest`)) ?? null;
}
