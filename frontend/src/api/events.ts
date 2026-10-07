// The story timeline's events and the links between them (backend/api/events.py):
// the nodes and edges of the timeline graph.
import { apiFetch } from "./client";

export interface EventInput {
  episode_index: number;
  summary: string;
  character_ids: string[];
  location_ids: string[];
}

export interface EventPublic extends EventInput {
  id: string;
}

// sequential: the story goes on; branch: one event leads on to several that go
// their own ways; merge: separate lines come together. Stored as these codes;
// the labels are this side's.
export const LINK_TYPES = { sequential: "이어짐", branch: "갈라짐", merge: "합쳐짐" } as const;
export type LinkType = keyof typeof LINK_TYPES;
export const SUMMARY_MAX_LENGTH = 500;
export const BRANCH_REASON_MAX_LENGTH = 200;

export interface LinkInput {
  from_id: string;
  to_id: string;
  link_type: LinkType;
  // Only a branch has one: what set the lines apart.
  branch_reason: string | null;
}

export interface LinkPublic extends LinkInput {
  id: string;
}

export interface LocationPublic {
  id: string;
  name: string;
}

export function listLocations(novelId: string): Promise<LocationPublic[]> {
  return apiFetch<LocationPublic[]>(`/novels/${novelId}/locations`);
}

export function listEvents(novelId: string): Promise<EventPublic[]> {
  return apiFetch<EventPublic[]>(`/novels/${novelId}/events`);
}

export function createEvent(novelId: string, input: EventInput): Promise<EventPublic> {
  return apiFetch<EventPublic>(`/novels/${novelId}/events`, { method: "POST", body: JSON.stringify(input) });
}

export function updateEvent(novelId: string, eventId: string, input: EventInput): Promise<EventPublic> {
  return apiFetch<EventPublic>(`/novels/${novelId}/events/${eventId}`, { method: "PUT", body: JSON.stringify(input) });
}

export async function deleteEvent(novelId: string, eventId: string): Promise<void> {
  await apiFetch<void>(`/novels/${novelId}/events/${eventId}`, { method: "DELETE" });
}

export function listLinks(novelId: string): Promise<LinkPublic[]> {
  return apiFetch<LinkPublic[]>(`/novels/${novelId}/event-links`);
}

export function createLink(novelId: string, input: LinkInput): Promise<LinkPublic> {
  return apiFetch<LinkPublic>(`/novels/${novelId}/event-links`, { method: "POST", body: JSON.stringify(input) });
}

export function updateLink(novelId: string, linkId: string, input: LinkInput): Promise<LinkPublic> {
  return apiFetch<LinkPublic>(`/novels/${novelId}/event-links/${linkId}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export async function deleteLink(novelId: string, linkId: string): Promise<void> {
  await apiFetch<void>(`/novels/${novelId}/event-links/${linkId}`, { method: "DELETE" });
}
