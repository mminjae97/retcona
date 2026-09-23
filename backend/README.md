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

## Startup checks

The API server (and `python -m workers.purge`) refuses to start, with an error saying what to do, when:

- the database is behind the migrations in `db/migrations` (including one with none applied) — run `alembic upgrade head` from `db/`;
- `users.nickname` is narrower than `maxLength` in `shared/nickname-rules.json` (API server only).

A database at a revision this code doesn't know (a newer release migrated it during a rolling deploy), or an install without `db/migrations`, is checked against the models instead: it starts, with a warning, if nothing this code needs is missing. The checks live in `models/db.py` (`check_schema_is_current`) and `models/user.py` (`check_nickname_column_length`).

Database connections time out after 10 seconds by default (see `.env.example`).

## Design principles (must follow)

- Every `models/`, `pipeline/` function takes `novel_id` as a required argument (10.1) — blocks isolation gaps at the code level
- `pipeline/` and `ai/` hold only business logic; queue/storage/inference/LLM access always goes through `infra/` interfaces (10.4.3)
- The 3 judgment modules inside `pipeline/` share the same interface (`claims + context_bundle` in → `flags` out) (6.2)
