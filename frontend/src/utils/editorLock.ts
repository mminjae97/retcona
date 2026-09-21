// Which tab "owns" an episode's local draft. The draft lives in localStorage,
// shared by every tab of the same site, but only one tab should be reading it
// back, restoring it or rewriting it: a second tab that opened the same
// episode would otherwise take the first tab's live, unsaved text for an
// orphan left by a crash, restore it and save it over whatever the first tab
// saved meanwhile.
//
// Ownership is a Web Lock held for as long as the editor is open, released
// automatically by the browser when the tab closes or crashes — which is what
// makes "the other tab is still alive" knowable, unlike anything written to
// storage.

export interface EpisodeClaim {
  owned: boolean;
  release: () => void;
}

const NOT_PROTECTED: EpisodeClaim = { owned: true, release: () => {} };

function tryClaim(episodeId: string): Promise<EpisodeClaim> {
  return new Promise((resolve) => {
    navigator.locks
      .request(`retcona-editor:${episodeId}`, { ifAvailable: true }, (lock) => {
        if (lock === null) {
          resolve({ owned: false, release: () => {} });
          return;
        }
        // Holding the lock = keeping this promise pending until release().
        return new Promise<void>((release) => resolve({ owned: true, release: () => release() }));
      })
      .catch(() => resolve(NOT_PROTECTED)); // e.g. an insecure context
  });
}

export async function claimEpisode(episodeId: string): Promise<EpisodeClaim> {
  // Without Web Locks nothing can be told apart, so behave as before: this tab owns it.
  if (typeof navigator === "undefined" || !navigator.locks) return NOT_PROTECTED;
  const claim = await tryClaim(episodeId);
  if (claim.owned) return claim;
  // The holder may be this very tab, still tearing down (a dev-mode remount,
  // a quick A -> B -> A navigation): give it a moment to let go before
  // concluding another tab has the episode.
  await new Promise((r) => setTimeout(r, 200));
  return tryClaim(episodeId);
}
