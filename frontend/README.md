# frontend

React + TypeScript + Vite. 화면 구성은 설계서 2장 UX 설계를 그대로 따릅니다.

| 경로 | 화면 | 설계서 섹션 |
|---|---|---|
| `/login` | 로그인 / 소셜 로그인 | 3.1, 3.2 |
| `/` | 대시보드 | 2.1 |
| `/novels/:novelId/settings` | 세계관·캐릭터 사전 설정 | 2.3 |
| `/novels/:novelId/episodes/:episodeId` | 원고 작성 에디터 | 2.2 |
| `/novels/:novelId/episodes/:episodeId/result` | 검증 결과 | 2.4 |
| `/mypage` | 마이페이지 | 2.6 |
| `/novels/:novelId/graph` | 인물 관계도 · 스토리 타임라인 | 2.7, 8장 |

그래프 시각화(관계도·타임라인)는 동일한 force-graph/D3.js 계열 컴포넌트를 재사용합니다 (8.4).

## 시작하기

```bash
npm install
npm run dev
```

`vite.config.ts`에서 `/api` 요청을 `http://localhost:8000`(backend)으로 프록시합니다.
