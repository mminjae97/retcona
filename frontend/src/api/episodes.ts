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

// A request sent as the tab closes is cancelled unless it is `keepalive`, which
// browsers only allow up to 64 KB of body (a chapter is about 15 KB). A longer
// text is sent without it rather than rejected outright.
const KEEPALIVE_MAX_BYTES = 60_000;

export function saveEpisode(novelId: string, episodeId: string, content: string): Promise<EpisodePublic> {
  const body = JSON.stringify({ content });
  return apiFetch<EpisodePublic>(`/novels/${novelId}/episodes/${episodeId}`, {
    method: "PATCH",
    body,
    keepalive: new TextEncoder().encode(body).length < KEEPALIVE_MAX_BYTES,
  });
}
