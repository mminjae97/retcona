# frontend

React + TypeScript + Vite. Screen composition follows design doc chapter 2 (UX design) as-is.

| Path | Screen | Design doc section |
|---|---|---|
| `/login` | Login / social login | 3.1, 3.2 |
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
