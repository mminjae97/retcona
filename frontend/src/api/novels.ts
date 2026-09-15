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

export async function deleteNovel(id: string): Promise<void> {
  await apiFetch<void>(`/novels/${id}`, { method: "DELETE" });
}
