// Local backup of manuscript text that hasn't been confirmed saved yet (design
// doc 2.2: work in progress must never be lost). The editor writes it on every
// keystroke and drops it once a save has gone through, so it only survives
// when something got in the way — an expired session, a network failure, a
// closed tab. Best effort throughout: storage can be full, blocked or absent.

const DRAFT_PREFIX = "retcona_draft:";
const CONFLICT_PREFIX = "retcona_draft_conflict:";

export interface Draft {
  content: string;
  // The episode's `updated_at` this draft was written on top of. If the
  // server's copy has moved on since (edited elsewhere), restoring the draft
  // would silently overwrite that newer work.
  baseUpdatedAt: string;
}

function read(key: string): Draft | null {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof (parsed as Draft).content === "string" &&
      typeof (parsed as Draft).baseUpdatedAt === "string"
    ) {
      return parsed as Draft;
    }
  } catch {
    // unreadable or corrupt — treat as no draft
  }
  return null;
}

function write(key: string, draft: Draft): void {
  try {
    localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    // quota exceeded / storage blocked — the draft is a safety net, not required
  }
}

function remove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // see write()
  }
}

export const loadDraft = (episodeId: string) => read(DRAFT_PREFIX + episodeId);
export const saveDraft = (episodeId: string, draft: Draft) => write(DRAFT_PREFIX + episodeId, draft);
export const clearDraft = (episodeId: string) => remove(DRAFT_PREFIX + episodeId);

// A draft that conflicts with a newer server copy is parked under its own key,
// so ordinary edits (which rewrite the regular draft) can't overwrite it
// before the author has chosen what to do with it.
export const loadConflictDraft = (episodeId: string) => read(CONFLICT_PREFIX + episodeId);
export const saveConflictDraft = (episodeId: string, draft: Draft) => write(CONFLICT_PREFIX + episodeId, draft);
export const clearConflictDraft = (episodeId: string) => remove(CONFLICT_PREFIX + episodeId);
