// localStorage that never throws. Storage can be blocked (site data disabled,
// some private modes), full, or absent, and every access can then throw; none
// of the callers can do anything useful with the exception, so failures come
// back as "nothing there" / `false` instead. The one place this is decided.

export function storageGet(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

// Returns whether the write went through.
export function storageSet(key: string, value: string): boolean {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}

export function storageRemove(key: string): void {
  try {
    localStorage.removeItem(key);
  } catch {
    // nothing stored to remove
  }
}

export function storageKeys(prefix: string): string[] {
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

export interface PersistedValue {
  get(): string | null;
  set(value: string): void;
  clear(): void;
}

// A string kept in localStorage that still works for this page load when the
// write is refused: the value is then held in memory, and wins over whatever
// storage may still hold (a stale copy). The memory copy is only used after a
// refused write, never while storage works, so another tab's change (a logout,
// say) isn't undone by it — a `storage` event for this key (or a whole-storage
// clear, reported with a null key) drops the memory copy, since it means
// another tab's own write or removal did go through and is what should show.
export function persistedValue(key: string): PersistedValue {
  let memory: string | null = null;
  window.addEventListener("storage", (e) => {
    if (e.key === null || e.key === key) memory = null;
  });
  return {
    get: () => memory ?? storageGet(key),
    set(value) {
      memory = storageSet(key, value) ? null : value;
    },
    clear() {
      memory = null;
      storageRemove(key);
    },
  };
}
