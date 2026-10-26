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
