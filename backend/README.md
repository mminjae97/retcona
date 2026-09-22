# backend

Follows the code structure from design doc section 6.2 as-is. Each module's responsibility:

| Module | Responsibility | Related design doc section |
|---|---|---|
| `api/` | REST endpoints | All |
| `auth/` | Login · social login (OAuth) · token (JWE) issuance | Chapter 3 |
| `pipeline/` | extract_claims, context_bundle, 3 judgment modules, merge | Chapter 7 |
| `models/` | DB models (users, novels, characters, locations ...) | Chapter 4 |
| `ai/` | Embedding · reranker · NLI · LLM client wrappers | Chapter 5 |
| `workers/` | cpu_worker / gpu_worker entry points (branch via `WORKER_TYPE`) | Section 10.4 |
| `workers/purge.py` | Account purge job: permanently deletes accounts (and all their novels' data) whose deletion request is past the 30-day grace period. Runs by itself inside the API server shortly after startup and then every day at midnight (`PURGE_TIMEZONE`, default `Asia/Seoul`; `PURGE_ENABLED=0` turns it off); also runnable alone: `python -m workers.purge [--loop]` | Section 3.5 |
| `infra/` | QueueClient · StorageClient · InferenceClient · LLMClient etc. cloud abstraction layer | Section 10.4.3 |

## Design principles (must follow)

- Every `models/`, `pipeline/` function takes `novel_id` as a required argument (10.1) — blocks isolation gaps at the code level
- `pipeline/` and `ai/` hold only business logic; queue/storage/inference/LLM access always goes through `infra/` interfaces (10.4.3)
- The 3 judgment modules inside `pipeline/` share the same interface (`claims + context_bundle` in → `flags` out) (6.2)
