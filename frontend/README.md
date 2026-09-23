# frontend

React + TypeScript + Vite. Screen composition follows design doc chapter 2 (UX design) as-is.

| Path | Screen | Design doc section |
|---|---|---|
| `/login` | Login / Google login | 3.1, 3.2 |
| `/auth/google/callback` | Google login return, nickname setup for a new account | 3.2, 3.6 |
| `/` | Dashboard | 2.1 |
| `/novels/:novelId/settings` | World/character presets | 2.3 |
| `/novels/:novelId/episodes/:episodeId` | Manuscript editor | 2.2 |
| `/novels/:novelId/episodes/:episodeId/result` | Validation results | 2.4 |
| `/mypage` | My Page | 2.6 |
| `/novels/:novelId/graph` | Character relationship graph · story timeline | 2.7, chapter 8 |

Graph visualizations (relationship graph, timeline) reuse the same force-graph/D3.js-family component (8.4).

## Getting started

```bash
npm install
npm run dev
```

`vite.config.ts` proxies `/api` requests to `http://localhost:8000` (backend).

## Site icon

The browser tab / home-screen icon is `src/assets/favicon.png`, the only file to change — `index.html` points both `icon` and `apple-touch-icon` at it.

- Replace it with a square PNG, 512×512 recommended, with a real transparent background (an image that merely *shows* a checkerboard has it baked in as pixels, and the checkerboard will show up in the tab).
- Keep the same file name, or update the two `<link>` tags in `index.html` to match.
- No cache busting needed: the build fingerprints it (`dist/assets/favicon-<hash>.png`), so a new icon gets a new URL.
