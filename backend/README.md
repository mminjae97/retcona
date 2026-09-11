# backend

설계서 6.2절 코드 구조를 그대로 따릅니다. 각 모듈의 책임은 다음과 같습니다.

| 모듈 | 책임 | 관련 설계서 섹션 |
|---|---|---|
| `api/` | REST 엔드포인트 | 전체 |
| `auth/` | 로그인 · 소셜 로그인(OAuth) · 토큰(JWE) 발급 | 3장 |
| `pipeline/` | extract_claims, context_bundle, 판단 모듈 3종, merge | 7장 |
| `models/` | DB 모델 (users, novels, characters, locations ...) | 4장 |
| `ai/` | 임베딩 · 리랭커 · NLI · LLM 클라이언트 래퍼 | 5장 |
| `workers/` | cpu_worker / gpu_worker 진입점 (`WORKER_TYPE`으로 분기) | 10.4절 |
| `infra/` | QueueClient · StorageClient · InferenceClient · LLMClient 등 클라우드 추상화 계층 | 10.4.3절 |

## 설계 원칙 (지켜야 할 것)

- 모든 `models/`, `pipeline/` 함수는 `novel_id`를 필수 인자로 받는다 (10.1) — 격리 누락을 코드 레벨에서 차단
- `pipeline/`과 `ai/`는 비즈니스 로직만 담고, 큐·스토리지·추론·LLM 접근은 항상 `infra/`의 인터페이스를 거친다 (10.4.3)
- `pipeline/` 내 3개 판단 모듈은 동일 인터페이스(`claims + context_bundle` 입력 → `flags` 출력)를 공유한다 (6.2)
