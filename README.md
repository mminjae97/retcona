# Retcona

> "Recording Every Timeline Change: Oversight Network, Assistant" — 모든 타임라인 변화를 기록하다: 감독 네트워크, 보조자

웹소설 연재 중 쌓이는 캐릭터·장소·사건 설정을 자동으로 기록하고, 새 원고가 기존 기록과 모순되는지 자동으로 찾아주는 서비스입니다.

전체 기획/설계 내용은 [`docs/기획_설계서.md`](./docs/기획_설계서.md) 문서를 참고하세요. 이 저장소의 폴더 구조와 초기 스캐폴드는 해당 문서의 내용을 그대로 반영해 구성했습니다.

## 핵심 아이디어

- 새 화 원고를 입력하는 것만으로 기존 설정·기록과 자동 대조하여 개연성 오류 후보를 탐지
- 캐릭터/장소 설정은 사전 입력이 선택 사항 — 입력하지 않으면 원고에 처음 등장하는 순간 자동 생성
- 오류를 자동으로 고치지 않고, 근거 문장과 함께 "발견하여 제시" — 최종 판단은 작가가 내림
- 세 가지 판단 관점(외형/행동, 장소, 시공간)으로 모듈을 분리, 판단 결과는 병합 후 제시

## 폴더 구조

```
retcona/
├── docs/                 # 기획/설계 문서
├── frontend/             # 로그인, 설정 카드, 에디터, 검증 결과, 관계도·타임라인 화면
├── backend/
│   ├── api/              # REST 엔드포인트
│   ├── auth/             # 로그인 · 소셜 로그인(OAuth) · 토큰(JWE) 발급
│   ├── pipeline/         # extract_claims, context_bundle, 판단 모듈 3종, merge
│   ├── models/           # DB 모델 (users, novels, characters, locations ...)
│   ├── ai/               # 임베딩 · 리랭커 · NLI · LLM 클라이언트 래퍼
│   ├── workers/          # cpu_worker / gpu_worker 진입점 (WORKER_TYPE으로 분기)
│   └── infra/            # QueueClient · StorageClient 등 클라우드 추상화 계층
└── db/                   # 마이그레이션 · 스키마
```

이 구조는 설계서 6.2절의 코드 구조를 그대로 따릅니다.

## 기술 스택 (설계서 5장 기준)

| 구성 요소 | 선택 |
|---|---|
| 임베딩 | KURE-v1 + BM25 하이브리드 |
| Cross-encoder 리랭커 | bge-reranker-v2-m3-ko 계열 |
| NLI | klue-roberta + KorNLI 기반 |
| LLM | 외부 API (모델 미정) |
| DB | PostgreSQL + pgvector |
| 배포 | GCP (Cloud Run, Pub/Sub, Cloud SQL 등, 10장 참고) |

## 로컬 개발 환경 시작하기

### 1. DB 실행 (PostgreSQL + pgvector)

```bash
docker compose up -d
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 값 채우기
```

### 3. 백엔드

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
uvicorn api.main:app --reload
```

### 4. 프론트엔드

```bash
cd frontend
npm install
npm run dev
```

## 로드맵

단계별 MVP 로드맵은 [`ROADMAP.md`](./ROADMAP.md)를 참고하세요. GitHub에서는 각 단계를 Milestone으로, 세부 항목을 Issue로 등록해 진행 상황을 추적하는 것을 권장합니다.

## 라이선스

아직 라이선스가 지정되지 않았습니다. 공개 여부와 라이선스 종류를 정하면 `LICENSE` 파일을 추가하세요.
