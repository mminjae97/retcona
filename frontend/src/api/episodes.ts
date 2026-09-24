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
  // How many contradictions with the settings the run found (appearance,
  // location), one per claim and attribute. Missing on runs from before
  // contradiction judgment.
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

// Contradiction flags (2.4): what the latest successful run found
// contradicting the settings, most confident first.
export type FlagStatus = "open" | "resolved_by_revalidation" | "accepted" | "dismissed";

export interface Flag {
  id: string;
  error_type: "appearance" | "location" | string;
  // The setting-card key it contradicts (eye_color, features, ...).
  attribute: string | null;
  // The model's contradiction probability, 0-1.
  confidence: number;
  status: FlagStatus;
  // The manuscript sentence.
  evidence_text: string;
  // The setting's value it contradicts.
  reference_text: string | null;
  subject_kind: "character" | "location" | null;
  // null once the card has been deleted.
  subject_id: string | null;
  subject_name: string | null;
  claim_text: string;
  // What the manuscript says for the attribute: what "accept" writes to the card.
  value: string | null;
}

// accept: the manuscript is right, its value replaces the card's.
// dismiss: a false positive. reopen: undoes a dismissal.
export type FlagAction = "accept" | "dismiss" | "reopen";

export function listFlags(novelId: string, episodeId: string): Promise<Flag[]> {
  return apiFetch<Flag[]>(`/novels/${novelId}/episodes/${episodeId}/flags`);
}

export function actOnFlag(novelId: string, episodeId: string, flagId: string, action: FlagAction): Promise<Flag> {
  return apiFetch<Flag>(`/novels/${novelId}/episodes/${episodeId}/flags/${flagId}`, {
    method: "PATCH",
    body: JSON.stringify({ action }),
  });
}
