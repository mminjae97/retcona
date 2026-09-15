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
