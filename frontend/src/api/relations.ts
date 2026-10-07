// Relationships between a novel's characters (backend/api/relations.py): the
// edges of the relationship graph.
import { apiFetch } from "./client";

export interface RelationInput {
  from_id: string;
  to_id: string;
  relation_type: string;
  // Points from from_id to to_id; otherwise the relation is mutual.
  directed: boolean;
}

export interface RelationPublic extends RelationInput {
  id: string;
}

// Types the form suggests; the author may write any other.
export const RELATION_TYPE_SUGGESTIONS = ["가족", "연인", "친구", "라이벌", "스승", "제자", "동료", "적대"];
export const RELATION_TYPE_MAX_LENGTH = 50;

export function listRelations(novelId: string): Promise<RelationPublic[]> {
  return apiFetch<RelationPublic[]>(`/novels/${novelId}/relations`);
}

export function createRelation(novelId: string, input: RelationInput): Promise<RelationPublic> {
  return apiFetch<RelationPublic>(`/novels/${novelId}/relations`, { method: "POST", body: JSON.stringify(input) });
}

export function updateRelation(novelId: string, relationId: string, input: RelationInput): Promise<RelationPublic> {
  return apiFetch<RelationPublic>(`/novels/${novelId}/relations/${relationId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteRelation(novelId: string, relationId: string): Promise<void> {
  await apiFetch<void>(`/novels/${novelId}/relations/${relationId}`, { method: "DELETE" });
}
