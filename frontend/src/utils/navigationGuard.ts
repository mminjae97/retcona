// Lets a page ask to be confirmed with before a *forced* navigation (one not
// triggered by the user clicking a Link) tears it down — the same protection
// EditorPage's own back-link gives against losing unsaved, unbacked-up text.
// Router-level blocking (react-router's useBlocker) needs a data router,
// which this app's plain BrowserRouter doesn't set up; this is a much smaller
// stand-in for the one caller (AuthExpiryRedirect) that needs it. It doesn't
// cover browser back/forward (popstate) — that gap predates this file and
// would need the same data-router migration to close.

// Returns the confirm message to show, or null/undefined to allow leaving
// freely. Only one page can guard at a time.
type NavigationCheck = () => string | null | undefined;

let guard: NavigationCheck | null = null;

// Registers `check`; the returned function unregisters it, but only if it's
// still the current guard (an unmounting page can't clobber whichever page
// registered after it).
export function setNavigationGuard(check: NavigationCheck): () => void {
  guard = check;
  return () => {
    if (guard === check) guard = null;
  };
}

// Call before a forced navigation. Returns whether it may proceed.
export function confirmNavigation(): boolean {
  const message = guard?.();
  return message === null || message === undefined || window.confirm(message);
}
