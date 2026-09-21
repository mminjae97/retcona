// Local backup of manuscript text that hasn't been confirmed saved yet (design
// doc 2.2: work in progress must never be lost). The editor writes it while
// typing and drops it once a save confirms it, so it only survives when
// something got in the way — an expired session, a network failure, a closed
// tab. Best effort throughout: storage can be full, blocked or absent.

const DRAFT_PREFIX = "retcona_draft:";
const CONFLICT_PREFIX = "retcona_draft_conflict:";

// A draft nobody came back for is dropped after this long.
const MAX_DRAFT_AGE_MS = 30 * 24 * 60 * 60 * 1000;
// Upper bound on parked drafts per episode, so they can't grow without limit.
const MAX_CONFLICT_DRAFTS = 10;

// Identifies this page load. Two tabs can have the same episode open; a draft
// only ever gets adjusted by the tab that wrote it, never by the other one.
export const TAB_ID = Math.random().toString(36).slice(2) + Date.now().toString(36);

export interface Draft {
  content: string;
  // The episode's `updated_at` this draft was written on top of. If the
  // server's copy has moved on since (edited elsewhere), restoring the draft
  // would silently overwrite that newer work.
  baseUpdatedAt: string;
  savedAt: number; // ms since epoch
  writer?: string; // TAB_ID of the tab that wrote it
}

export type DraftInput = Omit<Draft, "savedAt" | "writer"> & { savedAt?: number; writer?: string };

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

function withSavedAt(draft: DraftInput): Draft {
  return { ...draft, savedAt: draft.savedAt ?? Date.now() };
}

export function loadDraft(episodeId: string): Draft | null {
  const value = readJson(DRAFT_PREFIX + episodeId);
  return isDraft(value) ? value : null;
}

export const saveDraft = (episodeId: string, draft: DraftInput): boolean =>
  writeJson(DRAFT_PREFIX + episodeId, withSavedAt({ writer: TAB_ID, ...draft }));

export const clearDraft = (episodeId: string): void => remove(DRAFT_PREFIX + episodeId);

// A draft that conflicts with a newer server copy is parked under its own key,
// so ordinary edits (which rewrite the regular draft) can't overwrite it
// before the author has chosen what to do with it. Several can pile up, each
// kept until resolved, so a new one never replaces an older one — and when the
// list is full, a new one is refused (false) rather than evicting an old one.
export function loadConflictDrafts(episodeId: string): Draft[] {
  const value = readJson(CONFLICT_PREFIX + episodeId);
  return Array.isArray(value) ? value.filter(isDraft) : [];
}

export function addConflictDraft(episodeId: string, draft: DraftInput): boolean {
  const drafts = loadConflictDrafts(episodeId);
  if (drafts.some((d) => d.content === draft.content)) return true; // already parked
  if (drafts.length >= MAX_CONFLICT_DRAFTS) return false;
  return writeJson(CONFLICT_PREFIX + episodeId, [...drafts, withSavedAt(draft)]);
}

export function removeConflictDraft(episodeId: string, draft: Draft): void {
  const rest = loadConflictDrafts(episodeId).filter((d) => d.content !== draft.content);
  if (rest.length === 0) remove(CONFLICT_PREFIX + episodeId);
  else writeJson(CONFLICT_PREFIX + episodeId, rest);
}

function draftKeys(): string[] {
  const keys: string[] = [];
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      if (key !== null && (key.startsWith(DRAFT_PREFIX) || key.startsWith(CONFLICT_PREFIX))) keys.push(key);
    }
  } catch {
    // storage blocked
  }
  return keys;
}

// Manuscript text shouldn't outlive the account on a shared machine.
export function clearAllDrafts(): void {
  draftKeys().forEach(remove);
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
  const fresh = (d: Draft) => now - d.savedAt < MAX_DRAFT_AGE_MS;
  for (const key of draftKeys()) {
    const value = readJson(key);
    if (key.startsWith(DRAFT_PREFIX)) {
      if (!isDraft(value) || !fresh(value)) remove(key);
    } else {
      const keep = Array.isArray(value) ? value.filter(isDraft).filter(fresh) : [];
      if (keep.length === 0) remove(key);
      else if (keep.length !== (value as unknown[]).length) writeJson(key, keep);
    }
  }
}
