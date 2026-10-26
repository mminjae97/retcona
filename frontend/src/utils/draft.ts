// Local backup of manuscript text that hasn't been confirmed saved yet (design
// doc 2.2: work in progress must never be lost). The editor writes it while
// typing and drops it once a save confirms it, so it only survives when
// something got in the way — a failed save, a crash, a closed window. Best effort throughout: storage can be full, blocked or absent (see
// safeStorage.ts).
//
// Drafts are kept per episode and per editor session ("slot"): a
// tab rewrites its own slot every time and never touches another's, so two tabs
// on one episode can't overwrite each other's backup, and the author can pick
// any of them back up from the list (listOtherDrafts / the editor's load
// button). A page load gets a fresh slot, so what a closed or reloaded tab
// left behind is offered rather than silently written over.

import { storageGet, storageKeys, storageRemove, storageSet } from "./safeStorage";

const DRAFT_PREFIX = "retcona_draft:";

// A draft nobody came back for is dropped after this long.
const MAX_DRAFT_AGE_MS = 30 * 24 * 60 * 60 * 1000;
// Upper bound on drafts per episode, so left-behind slots can't
// grow without limit.
export const MAX_DRAFTS_PER_EPISODE = 10;
// When the episode is full a new session's slot replaces the oldest one, but
// only one that hasn't been written to for this long: a slot touched recently
// may belong to a tab that is still open (its save is failing, which is the
// only reason a draft outlives a save). If every slot is that recent, the new
// session gets no backup rather than pushing someone else's out.
const STALE_SLOT_MS = 60 * 60 * 1000;

export interface Draft {
  content: string;
  // The episode's `updated_at` this draft was written on top of. If the
  // server's copy has moved on since (edited elsewhere), loading the draft
  // replaces newer work.
  baseUpdatedAt: string;
  savedAt: number; // ms since epoch
}

export type DraftInput = Pick<Draft, "content" | "baseUpdatedAt">;

// A draft as found in storage; `key` identifies it for discardDraft().
export interface StoredDraft extends Draft {
  key: string;
}

function isDraft(value: unknown): value is Draft {
  if (typeof value !== "object" || value === null) return false;
  const draft = value as Partial<Draft>;
  return (
    typeof draft.content === "string" && typeof draft.baseUpdatedAt === "string" && typeof draft.savedAt === "number"
  );
}

function parseDraft(raw: string | null): Draft | null {
  if (raw === null) return null;
  try {
    const value: unknown = JSON.parse(raw);
    return isDraft(value) ? value : null;
  } catch {
    return null; // corrupt
  }
}

function readDraft(key: string): Draft | null {
  return parseDraft(storageGet(key));
}

function newSlotId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// This page load's slot for each episode it has opened.
const slots = new Map<string, string>();

// Called when the editor opens an episode. What an earlier session left in
// storage stays put, and this session writes to a slot of its own.
export function startDraftSlot(episodeId: string): void {
  slots.set(episodeId, newSlotId());
}

function currentSlot(episodeId: string): string {
  let slot = slots.get(episodeId);
  if (slot === undefined) {
    slot = newSlotId();
    slots.set(episodeId, slot);
  }
  return slot;
}

function episodePrefix(episodeId: string): string {
  return `${DRAFT_PREFIX}${episodeId}:`;
}

function ownKey(episodeId: string): string {
  return episodePrefix(episodeId) + currentSlot(episodeId);
}

// This session's own draft of the episode.
export function loadDraft(episodeId: string): Draft | null {
  return readDraft(ownKey(episodeId));
}

// A slot that found the episode full isn't retried on every keystroke burst
// (each try reads other drafts' text back); it looks again after a while.
const ROOM_RETRY_MS = 30_000;
const retryRoomAt = new Map<string, number>();

export function saveDraft(episodeId: string, draft: DraftInput): boolean {
  const key = ownKey(episodeId);
  // Room is checked whenever the slot has to be created — not just the first
  // time, because a confirmed save removes it and other tabs or loads may have
  // filled the episode since. Rewriting an existing slot never needs room.
  const creating = storageGet(key) === null;
  if (creating) {
    if ((retryRoomAt.get(key) ?? 0) > Date.now()) return false;
    if (!makeRoom(episodeId)) {
      retryRoomAt.set(key, Date.now() + ROOM_RETRY_MS);
      return false;
    }
    retryRoomAt.delete(key);
  }
  const stored: Draft = { content: draft.content, baseUpdatedAt: draft.baseUpdatedAt, savedAt: Date.now() };
  if (!storageSet(key, JSON.stringify(stored))) return false;
  // Checking for room and writing aren't one step: another tab may have made
  // its slot in between, both seeing the last free place. Counting again after
  // the write catches it — the later writer sees both slots and backs out, and
  // if both wrote before either counted, both back out and look again later.
  if (creating && storageKeys(episodePrefix(episodeId)).length > MAX_DRAFTS_PER_EPISODE) {
    storageRemove(key);
    retryRoomAt.set(key, Date.now() + ROOM_RETRY_MS);
    return false;
  }
  return true;
}

export function clearDraft(episodeId: string): void {
  storageRemove(ownKey(episodeId));
}

// Parsing a draft means parsing the whole manuscript, and the list is re-read
// often (every save, every write another tab makes), so a slot whose stored
// text hasn't changed is not parsed again.
const parsedByKey = new Map<string, { raw: string; draft: Draft | null }>();

function readDraftCached(key: string): Draft | null {
  const raw = storageGet(key);
  if (raw === null) {
    parsedByKey.delete(key);
    return null;
  }
  const cached = parsedByKey.get(key);
  if (cached !== undefined && cached.raw === raw) return cached.draft;
  const draft = parseDraft(raw);
  parsedByKey.set(key, { raw, draft });
  return draft;
}

// Drafts of this episode that other sessions left (another tab, or an earlier
// load of this one), newest first. This session's own draft is not included.
export function listOtherDrafts(episodeId: string): StoredDraft[] {
  const own = ownKey(episodeId);
  const prefix = episodePrefix(episodeId);
  const keys = storageKeys(prefix);
  const found: StoredDraft[] = [];
  for (const key of keys) {
    if (key === own) continue;
    const draft = readDraftCached(key);
    if (draft !== null) found.push({ ...draft, key });
    else storageRemove(key); // corrupt
  }
  // Slots another tab has removed since: their cached manuscripts go too.
  const present = new Set(keys);
  for (const key of parsedByKey.keys()) {
    if (key.startsWith(prefix) && !present.has(key)) parsedByKey.delete(key);
  }
  return found.sort((a, b) => b.savedAt - a.savedAt);
}

// Drops the parsed copies of this episode's other drafts held for the list. Called
// when the editor is left; the (small) slot records stay, because a
// save still in flight refers to them when it completes.
export function releaseDraftCache(episodeId: string): void {
  const prefix = episodePrefix(episodeId);
  for (const key of parsedByKey.keys()) {
    if (key.startsWith(prefix)) parsedByKey.delete(key);
  }
}

// Removes the draft only if it still holds exactly this text: the caller's copy
// may be a moment old, and its owner may have typed more since.
export function discardDraftIfContent(key: string, content: string): boolean {
  if (!key.startsWith(DRAFT_PREFIX) || readDraft(key)?.content !== content) return false;
  discardDraft(key);
  return true;
}

export function discardDraft(key: string): void {
  if (!key.startsWith(DRAFT_PREFIX)) return;
  storageRemove(key);
  parsedByKey.delete(key);
}

// Frees a slot for a new session's first write when the episode is at its cap,
// oldest first and never one written to recently. Returns whether there is room.
function makeRoom(episodeId: string): boolean {
  const keys = storageKeys(episodePrefix(episodeId));
  // Runs each time a slot is created, so the common case (room to spare) only
  // counts keys and reads no manuscript text.
  const excess = keys.length - MAX_DRAFTS_PER_EPISODE + 1;
  if (excess <= 0) return true;
  const others = keys.map((key) => ({ key, savedAt: readDraftCached(key)?.savedAt ?? 0 }));
  const now = Date.now();
  const stale = others.filter((o) => now - o.savedAt >= STALE_SLOT_MS).sort((a, b) => a.savedAt - b.savedAt);
  if (stale.length < excess) return false;
  for (const { key } of stale.slice(0, excess)) discardDraft(key);
  return true;
}

// Whether a storage event is about a draft of this episode (another tab wrote,
// or removed, one); the editor refreshes its list on those.
export function isDraftEventFor(episodeId: string, storageKey: string | null): boolean {
  // A storage event with no key means the whole storage was cleared.
  return storageKey === null || storageKey.startsWith(episodePrefix(episodeId));
}

// Runs the prune once the browser is idle rather than during startup: it has
// to parse every stored draft (big text blobs), which would delay first paint.
export function schedulePruneStaleDrafts(): void {
  if (typeof requestIdleCallback === "function") {
    requestIdleCallback(() => pruneStaleDrafts(), { timeout: 10_000 });
  } else {
    setTimeout(() => pruneStaleDrafts(), 2_000);
  }
}

// Drops drafts nobody came back for (including those of episodes or novels
// that no longer exist), so they don't accumulate forever.
export function pruneStaleDrafts(now = Date.now()): void {
  for (const key of storageKeys(DRAFT_PREFIX)) {
    const draft = readDraft(key);
    if (draft === null || now - draft.savedAt >= MAX_DRAFT_AGE_MS) discardDraft(key);
  }
}
