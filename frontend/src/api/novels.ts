// Novel (작품) management API calls (design doc 2.6).

import { apiFetch } from "./client";

export interface NovelPublic {
  id: string;
  title: string;
  created_at: string;
}

export function listNovels(): Promise<NovelPublic[]> {
  return apiFetch<NovelPublic[]>("/novels");
}

export function getNovel(id: string): Promise<NovelPublic> {
  return apiFetch<NovelPublic>(`/novels/${id}`);
}

export function createNovel(title: string): Promise<NovelPublic> {
  return apiFetch<NovelPublic>("/novels", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export function renameNovel(id: string, title: string): Promise<NovelPublic> {
  return apiFetch<NovelPublic>(`/novels/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

// To the trash (2.6): restorable until purge_after, then deleted for good.
export async function deleteNovel(id: string): Promise<void> {
  await apiFetch<void>(`/novels/${id}`, { method: "DELETE" });
}

export interface TrashedNovel {
  id: string;
  title: string;
  deleted_at: string;
  // When it's deleted for good (the first daily pass after this).
  purge_after: string;
}

export function listTrash(): Promise<TrashedNovel[]> {
  return apiFetch<TrashedNovel[]>("/novels/trash");
}

export function restoreNovel(id: string): Promise<NovelPublic> {
  return apiFetch<NovelPublic>(`/novels/${id}/restore`, { method: "POST" });
}
