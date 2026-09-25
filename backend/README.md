# backend

Follows the code structure from design doc section 6.2 as-is. Each module's responsibility:

| Module | Responsibility | Related design doc section |
|---|---|---|
| `api/` | REST endpoints | All |
| `auth/` | Login · Google login (OAuth, `auth/oauth.py`) · token (JWE) issuance | Chapter 3 |
| `pipeline/` | extract_claims, context_bundle, 3 judgment modules, merge | Chapter 7 |
| `models/` | DB models (users, novels, characters, locations ...) | Chapter 4 |
| `ai/` | Embedding · reranker · NLI · LLM client wrappers | Chapter 5 |
| `workers/` | cpu_worker / gpu_worker entry points (branch via `WORKER_TYPE`) | Section 10.4 |
| `workers/purge.py` | Account purge job: permanently deletes accounts (and all their novels' data) whose deletion request is past the 30-day grace period. Runs by itself inside the API server shortly after startup and then every day at midnight (`PURGE_TIMEZONE`, default `Asia/Seoul`; `PURGE_ENABLED=0` turns it off), retrying a failed pass after an hour; also runnable alone: `python -m workers.purge [--loop]` | Section 3.5 |
| `workers/cpu_worker.py` | Runs "run validation" jobs from the queue: `python -m workers.cpu_worker` (keeps running until Ctrl-C/SIGTERM; needs Redis and the database). See "Validation runs" below | Sections 2.2, 10.4 |
| `infra/` | QueueClient · StorageClient · InferenceClient · LLMClient etc. cloud abstraction layer | Section 10.4.3 |

## Startup checks

The API server (and `python -m workers.purge`) refuses to start, with an error saying what to do, when:

- the database is behind the migrations in `db/migrations` (including one with none applied) — run `alembic upgrade head` from `db/`;
- `users.nickname` is narrower than `maxLength` in `shared/nickname-rules.json`, or not a string column at all (API server only — it has nothing to do with purging; a wider one only logs a warning).

A database at a revision this code doesn't know (a newer release migrated it during a rolling deploy), or an install without `db/migrations`, is checked against the models instead: it starts, with a warning, if nothing this code needs is missing. Both entry points run them through `models/db.py`'s `check_database` (`check_schema_is_current` there, `check_nickname_column_length` in `models/user.py` — the API server only).

Database connections time out after 10 seconds by default (see `.env.example`).

`python -m workers.purge --loop` retries the startup check every minute while the database can't be reached, for up to 10 minutes (then it exits non-zero: a wrong password or host looks the same as a database still starting — so run it under a restart policy). Each pass works through the expired accounts in a random order. It stops early only when the database itself fails (unreachable or lost partway — checked with a `SELECT 1` when the error carries no SQLSTATE —, shutting down, read-only after a failover, out of disk, I/O errors or corruption, a table renamed by a newer migration: `_DATABASE_WIDE_SQLSTATES`), or when 3 accounts in the pass hit the same statement timeout or lock error (contention: `_CONTENTION_SQLSTATES` — only with a `statement_timeout`/`lock_timeout` set on the database or role, which the app itself doesn't set; without one, a blocked DELETE simply waits), logging in one ERROR how many accounts it had already purged. Any other failure is counted against its account and the pass goes on; with the order shuffled, no set of accounts can keep the others from being purged. A stopped pass is retried after an hour, up to 3 times after each midnight's pass; accounts that failed on their own are logged as a warning and wait for the next midnight. On shutdown (SIGTERM, or the API server stopping) a pass ends after the account it's on.

Logging: the app's own packages (`infra/app_logging.py`) log at uvicorn's `--log-level` (INFO when run without uvicorn), unless a `--log-config` set their level itself. With no logging configured, they print in uvicorn's format through Python's last-resort handler; anything that configures the root logger (a `--log-config`, `logging.basicConfig`, Cloud Logging) takes over completely, with nothing printed twice.

## Validation runs

"Run validation" in the editor (`POST /novels/{id}/episodes/{id}/validations`) records a `validation_runs` row (queued) and puts a job on the queue (`QUEUE_PROVIDER=redis` locally); the CPU worker takes it (running) and ends it succeeded or failed. The editor polls `GET .../validations/latest` (204 before the first run). While a run is queued or running, another request returns that run instead of starting a second one; one still queued or running 15 minutes after it was requested is failed as `abandoned` (no worker running, or one that died — the Redis queue doesn't redeliver), so it can be run again.

What a run does (`pipeline/validate_episode.py`, 7.1):

1. Claim extraction (`pipeline/extract_claims.py`).
2. Judgment against the setting cards the claims are about (`pipeline/context_bundle.py`, `pipeline/judges.py`, 7.2): a character's fixed attributes (age, eye/hair color, height, scars, origin) and a location's features, by NLI. The card's value, as a sentence, is the premise; the manuscript sentence the claim came from is the hypothesis. A contradiction probability of 0.5 or more is a flag, with that probability as its confidence. Mutable attributes (hairstyle, outfit, ...) aren't judged — they change over the story. Behavior (OOC) and spacetime come in later stages.
3. In one transaction: the episode's earlier claims and flags are replaced; each claim is linked to its character/location by name — an `auto_detected` card is created, with this episode's attributes, for a name the novel doesn't have yet (`pipeline/entities.py`, 7.4) —; and what doesn't contradict anything is added to the settings (`pipeline/merge.py`): a card attribute that's still empty is filled in, and characters' mutable attributes go to `character_state_history` for this episode. An attribute a card already has is never changed by a run. A card remembers which episode each attribute was filled in from (`attr_sources`), so validating that episode again after editing it replaces that value instead of flagging the new wording against the old (or clears it once the sentence it came from is gone from the episode); the author editing the value on the settings screen makes it theirs.

`GET /novels/{id}/episodes/{id}/flags` lists the flags of the episode's latest successful run, most confident first; the result screen (2.4) shows them next to the manuscript. `PATCH .../flags/{id}` acts on one: `accept` (the manuscript is right — its value replaces the card's, which becomes the author's value), `dismiss` (a false positive), `reopen` (undoes a dismissal). A dismissal is recorded apart from the run's flags (`flag_dismissals`, `pipeline/dismissals.py`), so it holds in every later run that flags the same sentence against the same setting — even after a run that didn't flag it. It names who or what the flag is about by kind and name, as entity matching does, not by card id: a card deleted and made again keeps its dismissals, and renaming a card moves them (and its claims' names) to the new name. Character names are unique within a novel as matching compares them ("Leon" and "leon" are one name). `GET .../validations/latest` also returns `flag_counts` (open / total flags now).

NLI runs in the worker process on the CPU (`INFERENCE_BACKEND=cpu`, `infra/inference_client.py`) with the model trained in `ml/nli`: `klue/roberta-base` fine-tuned on KorNLI + KLUE-NLI (chapter 5; how it compares with other checkpoints is in `ml/nli/RESULTS.md`). It's kept on the machine for now, in `ml/nli/runs/mixed` (not committed — train it with `ml/nli`, see its README); `NLI_MODEL` names another local directory or a Hugging Face checkpoint. Without either, the worker falls back to `Huffon/klue-roberta-base-nli` (downloaded from Hugging Face, about 440 MB), which catches about half as many contradictions in novel prose, and logs a warning. The worker loads the model at startup and keeps it loaded; if that fails, the worker still starts and the first run that needs it tries again. Expect some false positives (synonyms, sentences that don't state the attribute), which the author dismisses.

The model isn't chosen yet (chapter 5): `LLM_PROVIDER=mock` (`infra/mock_llm.py`) answers the extraction prompt from keyword rules, rough but enough to run everything end to end. Failures are recorded on the run as a code: `queue_unavailable`, `abandoned`, `episode_missing`, `empty_manuscript`, `llm_failed`, `bad_llm_response`, `inference_failed` (the NLI model couldn't be downloaded, loaded or run), `internal`.

## Design principles (must follow)

- Every `models/`, `pipeline/` function takes `novel_id` as a required argument (10.1) — blocks isolation gaps at the code level
- `pipeline/` and `ai/` hold only business logic; queue/storage/inference/LLM access always goes through `infra/` interfaces (10.4.3)
- The 3 judgment modules inside `pipeline/` share the same interface (`claims + context_bundle` in → `flags` out) (6.2)
