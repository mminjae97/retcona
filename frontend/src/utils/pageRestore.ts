import { useEffect, useRef } from "react";

// A page left for another site (Google's sign-in) and then returned to with
// the browser's Back button can come back from the back/forward cache exactly
// as it was left — React state included, such as a "leaving for Google..." flag
// that nothing on the page will ever clear, since the navigation it was waiting
// for is what the user just undid. `onRestore` runs when that happens (a
// `pageshow` with `persisted`), to put such state back; an ordinary load or
// in-app navigation doesn't trigger it.
export function useOnPageRestore(onRestore: () => void): void {
  const latest = useRef(onRestore);
  latest.current = onRestore;
  useEffect(() => {
    const handler = (e: PageTransitionEvent) => {
      if (e.persisted) latest.current();
    };
    window.addEventListener("pageshow", handler);
    return () => window.removeEventListener("pageshow", handler);
  }, []);
}
