// Local backup of manuscript text that hasn't been confirmed saved yet (design
// doc 2.2: work in progress must never be lost). The editor writes it while
// typing and drops it once a save confirms it, so it only survives when
// something got in the way — an expired session, a network failure, a closed
// tab. Best effort throughout: storage can be full, blocked or absent.
//
// Drafts are kept per account, per episode and per editor session ("slot"): a
// tab rewrites its own slot every time and never touches another's, so two tabs
// on one episode can't overwrite each other's backup, and the author can pick
// any of them back up from the list (listOtherDrafts / the editor's load
// button). A page load gets a fresh slot, so what a closed or reloaded tab
// left behind is offered rather than silently written over.

import { getUserId } from "./session";

const DRAFT_PREFIX = "retcona_draft:";
// Set when an account is put up for deletion, cleared by its next login; one per account.
const WIPED_PREFIX = "retcona_drafts_wiped:";

// A draft nobody came back for is dropped after this long.
const MAX_DRAFT_AGE_MS = 30 * 24 * 60 * 60 * 1000;
// Upper bound on drafts per account and episode, so left-behind slots can't
// grow without limit. A new slot pushes the oldest one out.
const MAX_DRAFTS_PER_EPISODE = 10;

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

function readJson(key: string): unknown {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null; // unreadable, corrupt or storage blocked — same as absent
  }
}

// Returns whether the write went through; callers that would be left holding
// an out-of-date copy on failure (see the editor) need to know.
function writeJson(key: string, value: unknown): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false; // quota exceeded / storage blocked
  }
}

function remove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // see writeJson()
  }
}

function keysStartingWith(prefix: string): string[] {
  const keys: string[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key !== null && key.startsWith(prefix)) keys.push(key);
    }
  } catch {
    // storage blocked
  }
  return keys;
}

function newSlotId(): string {
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

// This page load's slot for each episode it has opened.
const slots = new Map<string, string>();

// Called when the editor opens an episode: what an earlier session left in
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

function episodePrefix(userId: string, episodeId: string): string {
  return `${DRAFT_PREFIX}${userId}:${episodeId}:`;
}

function ownKey(userId: string, episodeId: string): string {
  return episodePrefix(userId, episodeId) + currentSlot(episodeId);
}

// While the account is being deleted (or is pending deletion) no draft of it is
// written, in any tab: an editor still open elsewhere flushes its pending text
// as it unmounts (the 401 that ends its session routes it away), which would
// otherwise bring back what was just wiped.
function draftsWiped(userId: string): boolean {
  try {
    return localStorage.getItem(WIPED_PREFIX + userId) !== null;
  } catch {
    return true; // storage blocked: nothing could be written anyway
  }
}

// This session's own draft of the episode.
export function loadDraft(episodeId: string): Draft | null {
  const userId = getUserId();
  if (userId === null) return null;
  const value = readJson(ownKey(userId, episodeId));
  return isDraft(value) ? value : null;
}

export function saveDraft(episodeId: string, draft: DraftInput): boolean {
  const userId = getUserId();
  if (userId === null || draftsWiped(userId)) return false;
  const key = ownKey(userId, episodeId);
  if (readJson(key) === null) makeRoom(userId, episodeId);
  const stored: Draft = { content: draft.content, baseUpdatedAt: draft.baseUpdatedAt, savedAt: Date.now() };
  return writeJson(key, stored);
}

export function clearDraft(episodeId: string): void {
  const userId = getUserId();
  if (userId !== null) remove(ownKey(userId, episodeId));
}

// Drafts of this episode that other sessions left (another tab, or an earlier
// load of this one), newest first. This session's own draft is not included.
export function listOtherDrafts(episodeId: string): StoredDraft[] {
  const userId = getUserId();
  if (userId === null) return [];
  const own = ownKey(userId, episodeId);
  const found: StoredDraft[] = [];
  for (const key of keysStartingWith(episodePrefix(userId, episodeId))) {
    if (key === own) continue;
    const value = readJson(key);
    if (isDraft(value)) found.push({ ...value, key });
    else remove(key); // corrupt
  }
  return found.sort((a, b) => b.savedAt - a.savedAt);
}

export function discardDraft(key: string): void {
  if (key.startsWith(DRAFT_PREFIX)) remove(key);
}

// Frees a slot for a new session's first write when the episode is at its cap.
function makeRoom(userId: string, episodeId: string): void {
  const others = keysStartingWith(episodePrefix(userId, episodeId)).map((key) => {
    const value = readJson(key);
    return { key, savedAt: isDraft(value) ? value.savedAt : 0 };
  });
  others.sort((a, b) => a.savedAt - b.savedAt);
  for (const { key } of others.slice(0, Math.max(0, others.length - MAX_DRAFTS_PER_EPISODE + 1))) remove(key);
}

// Whether a storage event is about a draft of this episode (another tab wrote,
// or removed, one); the editor refreshes its list on those.
export function isDraftEventFor(episodeId: string, storageKey: string | null): boolean {
  const userId = getUserId();
  if (userId === null) return false;
  // A storage event with no key means the whole storage was cleared.
  return storageKey === null || storageKey.startsWith(episodePrefix(userId, episodeId));
}

// Manuscript text shouldn't outlive the account on a shared machine. Called
// once the deletion request has gone through; logging in again within the grace
// period cancels the deletion, but unsaved drafts are not brought back. Only
// this account's drafts go: other accounts on the same browser keep theirs.
export function discardDraftsForDeletion(): void {
  const userId = getUserId();
  if (userId === null) return;
  // Marker first, so a write racing with the removal below is refused.
  const mark = () => {
    try {
      localStorage.setItem(WIPED_PREFIX + userId, String(Date.now()));
    } catch {
      // full or blocked
    }
  };
  const removeAll = () => keysStartingWith(`${DRAFT_PREFIX}${userId}:`).forEach(remove);
  mark();
  removeAll();
  // Storage that was full refused the marker; the drafts just removed made
  // room. (Blocked storage still fails, but then draftsWiped() is true anyway.)
  if (!draftsWiped(userId)) mark();
}

// A login starts a fresh session, so this account's drafts are written again.
export function resumeDrafts(userId: string): void {
  remove(WIPED_PREFIX + userId);
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
  for (const key of keysStartingWith(DRAFT_PREFIX)) {
    const value = readJson(key);
    if (!isDraft(value) || now - value.savedAt >= MAX_DRAFT_AGE_MS) remove(key);
  }
}
