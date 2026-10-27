# frontend

React + TypeScript + Vite. Screen composition follows design doc chapter 2 (UX design) as-is.

| Path | Screen | Design doc section |
|---|---|---|
| `/` | Novel list (the app opens on it; no accounts) | 2.1, 2.6 |
| `/novels/:novelId/settings` | World/character presets | 2.3 |
| `/novels/:novelId/episodes/:episodeId` | Manuscript editor | 2.2 |
| `/novels/:novelId/episodes/:episodeId/result` | Validation results | 2.4 |
| `/novels/:novelId/graph` | Character relationship graph · story timeline | 2.7, chapter 8 |

Graph visualizations (relationship graph, timeline) reuse the same force-graph/D3.js-family component (8.4).

## Getting started

```bash
npm install
npm run dev
```

`vite.config.ts` proxies `/api` requests to `http://localhost:8000` (backend).

Open the app at `localhost` (or `127.0.0.1`): the backend only answers requests addressed to this PC (`ALLOWED_HOSTS`, `backend/api/main.py`), so reaching the dev server from another device (`vite --host`, then the PC's LAN address) gets every API call refused with 400. That's deliberate — it's what keeps another website from using the local API (design doc 10.4.2).

## Site icon

The browser tab / home-screen icon is `src/assets/favicon.png`, the only file to change — `index.html` points both `icon` and `apple-touch-icon` at it.

- Replace it with a square PNG, 512×512 recommended, with a real transparent background (an image that merely *shows* a checkerboard has it baked in as pixels, and the checkerboard will show up in the tab).
- Keep the same file name, or update the two `<link>` tags in `index.html` to match.
- No cache busting needed: the build fingerprints it (`dist/assets/favicon-<hash>.png`), so a new icon gets a new URL.
