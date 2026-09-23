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
| `workers/purge.py` | Account purge job: permanently deletes accounts (and all their novels' data) whose deletion request is past the 30-day grace period. Runs by itself inside the API server shortly after startup and then every day at midnight (`PURGE_TIMEZONE`, default `Asia/Seoul`; `PURGE_ENABLED=0` turns it off), retrying a failed pass after an hour; also runnable alone: `python -m workers.purge [--loop]` | Section 3.5 |
| `infra/` | QueueClient · StorageClient · InferenceClient · LLMClient etc. cloud abstraction layer | Section 10.4.3 |

## Startup checks

The API server (and `python -m workers.purge`) refuses to start, with an error saying what to do, when:

- the database is behind the migrations in `db/migrations` (including one with none applied) — run `alembic upgrade head` from `db/`;
- `users.nickname` is narrower than `maxLength` in `shared/nickname-rules.json`, or not a string column at all (API server only — it has nothing to do with purging; a wider one only logs a warning).

A database at a revision this code doesn't know (a newer release migrated it during a rolling deploy), or an install without `db/migrations`, is checked against the models instead: it starts, with a warning, if nothing this code needs is missing. Both entry points run them through `models/db.py`'s `check_database` (`check_schema_is_current` there, `check_nickname_column_length` in `models/user.py` — the API server only).

Database connections time out after 10 seconds by default (see `.env.example`).

`python -m workers.purge --loop` retries the startup check every minute while the database can't be reached, for up to 10 minutes (then it exits non-zero: a wrong password or host looks the same as a database still starting — so run it under a restart policy). Both it and the API server retry a pass that failed because of the database as a whole after an hour instead of waiting for the next midnight; the pass stops there and logs, in one ERROR, how many accounts it had already purged. Only errors known to be about one account's statements (deadlock/serialization, statement timeout, lock not available, constraint or data errors: `_PER_ACCOUNT_SQLSTATES`) are counted per account — logged as a warning and retried at the next midnight's pass, without holding up the rest — unless the same timeout or lock error hits several accounts in a row, which stops the pass too. Anything else (unreachable, lost partway, shutting down, read-only after a failover, out of disk, a table renamed by a newer migration) is the database's: see `_is_database_wide`.

Logging: the app's own packages (`infra/app_logging.py`) log at uvicorn's `--log-level` (INFO when run without uvicorn), unless a `--log-config` set their level itself. With no logging configured, they print in uvicorn's format through Python's last-resort handler; anything that configures the root logger (a `--log-config`, `logging.basicConfig`, Cloud Logging) takes over completely, with nothing printed twice.

## Design principles (must follow)

- Every `models/`, `pipeline/` function takes `novel_id` as a required argument (10.1) — blocks isolation gaps at the code level
- `pipeline/` and `ai/` hold only business logic; queue/storage/inference/LLM access always goes through `infra/` interfaces (10.4.3)
- The 3 judgment modules inside `pipeline/` share the same interface (`claims + context_bundle` in → `flags` out) (6.2)
