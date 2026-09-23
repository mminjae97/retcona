# Spec Reference

English working reference for the Retcona design doc (`README.md`, written in
Korean). This covers the full product + implementation spec, written as if
no part of the project has been built yet, so that during implementation you
can read this file instead of the full README each time.

---

## 0. Product summary

Retcona ("Recording Every Timeline Change: Oversight Network, Assistant") is
a web service for web-novel authors. While an author serializes a long-form
novel episode by episode, it automatically records the character/location/
event settings that accumulate over time, and automatically flags when a new
episode's manuscript contradicts what was already established.

Problem it solves: as episode count grows, an author can no longer reliably
remember every detail they set up early on. Recurring failure types:
- **Appearance mismatch** — e.g. eye color or scar location set early
  contradicts a later description.
- **Behavioral mismatch (OOC / out of character)** — narrated behavior that
  doesn't fit a character's established personality.
- **Spacetime contradictions** — a dead character reappearing, wrong
  age/season math, movement across a distance that isn't physically
  possible in the elapsed time.
- **Location errors** — described distance or geography between locations
  contradicts earlier text.

Manually re-reading the whole manuscript to check for these before every new
episode does not scale as episode count grows.

Core value proposition:
- Author doesn't need to re-review the whole manuscript — just submit the
  new episode and contradictions are surfaced automatically.
- Fixed character/location settings can be pre-entered, or left blank and
  auto-created the first time they appear in a manuscript. Both fixed
  presets and settings accumulated during serialization (events, locations,
  relationships) are checked together.
- The system never auto-corrects an error — it always "surfaces it with
  supporting evidence" and lets the author make the final call.
- If the author realizes a flag was a false positive because of a setting
  they hadn't entered yet, they can re-validate just that one flag instead
  of re-running everything.

Target users: solo authors writing long-running serialized web novels,
especially in setting-heavy genres (fantasy, romance fantasy, martial arts)
where the character/world count is large.

### Core features (functional requirements)

1. **Account & My Page** — sign up via email or a Google account; use a pen
   name instead of a real name; manage multiple novels
   under one account from My Page; view per-novel relationship graph/
   timeline; account deletion.
2. **In-service writing editor** — long-form text editor; a local, in-browser
   draft plus an explicit save button so work in progress is never lost;
   validation runs against the saved manuscript; previously saved episodes
   can be reopened and edited.
3. **World/character presets (optional)** — before writing, an author can
   pre-enter world-building (era/setting, magic-or-martial-arts systems,
   factions/organizations, history) and characters (name, appearance,
   personality, speech, etc). Whatever is entered becomes the baseline for
   all later validation; if left blank, it gets filled automatically as
   the manuscript is written.
4. **Character setting cross-check (appearance / behavior)** — character
   setting cards (fixed + mutable attributes) are optional to pre-enter; if
   present, use them as the baseline, otherwise use the auto-created
   settings from the character's first appearance. Detects appearance/
   behavior descriptions that don't match. Non-contradicting new
   information is automatically accumulated into the settings as
   serialization continues.
5. **Event timeline cross-check** — using both publication order (episode
   number) and in-story time, detect whether new manuscript content
   contradicts the accumulated state-change history of characters/
   locations.
6. **Location setting cross-check** — detects description errors or
   movement contradictions based on a location's geography and its
   distance/connection relationships to other locations.
7. **Auto-generated character relationship graph & story timeline** — from
   accumulated relationship/state-history data, automatically render a
   character relationship graph and an episode/in-story-time-based story
   timeline as graphs, with no extra authoring work. The story timeline is
   not a flat chronological list — it represents storylines branching and
   later merging based on which characters/locations diverge.
8. **(Bonus, low priority) Character illustration generation** — generate
   illustrations from entered character settings. A separate module from
   the core plausibility engine; developed last.

### Differentiator

Unlike wiki/notebook-style setting trackers, this service proactively
cross-checks new manuscript input against existing records and surfaces
contradiction candidates first — the author doesn't have to go looking for
inconsistencies, the service raises them. Authors can also start writing
immediately without pre-filling any settings, lowering the barrier to entry.

---

## 1. System overview

- **Purpose**: when a new episode's manuscript is submitted, automatically
  cross-check it against accumulated settings/records and surface
  plausibility-error candidates.
- **Three validation perspectives**: appearance/behavior violations,
  location errors, spacetime (timeline) contradictions.
- **Design principle**: split module boundaries by **judgment perspective**,
  not by data type (character vs. location) — data lookups happen in one
  shared layer. Since this is a multi-user service, all data and AI
  processing must be isolated per user (per novel).

---

## 2. UX design

### 2.1 Overall screen flow

```
Login / social login -> Dashboard
Dashboard -> Preset management (optional): characters · locations
Dashboard -> Manuscript editor
  editor --(save)--> editor
  editor --(run validation)--> automatic validation run (includes auto-registering new characters/locations)
    -> Validation result screen
       --(accept)--> setting history updated
       --(dismiss as false positive)--> flag dismissed
       --(supplement settings)--> add world/character settings -> re-run validation -> back to validation result screen
Dashboard -> pre-writing brief / checklist
Dashboard -> My Page
My Page -> per-novel relationship graph · timeline (scoped to that novel_id only)
```

### 2.2 Manuscript editor screen

```
+--------------------------------------------------+
|  Episode 12                                       |
+--------------------------------------------------+
|                                                    |
|   (long-form text input area)                     |
|                                                    |
+--------------------------------------------------+
|  Last saved: 2 min ago              [Save] [Run validation] |
+--------------------------------------------------+
```

- **Local draft**: while typing, the manuscript is written to a draft kept in
  this browser only (debounced, on a short delay) — never sent to the server.
  It's a safety net against an expired session, a network failure or a closed
  tab: whichever of those happens, the text since the last **Save** is still
  recoverable in this browser, and a page reopening the episode offers it back
  if the server's own copy is older. It's flushed one last time when the tab
  is hidden or the editor is left, and dropped once a save confirms the server
  has the same text. A confirmation is shown before leaving with changes this
  draft failed to capture (storage blocked, full, or otherwise unavailable) —
  the only case leaving the editor can actually lose text.
- **Save**: the only thing that reaches the server. Manual, immediate save
  button; does not trigger the AI pipeline.
- **Run validation**: enqueues the saved manuscript onto the job queue
  (§8.2) to run the pipeline. Saving (write) and validating (AI processing)
  are intentionally separate so every keystroke doesn't trigger an AI call.
- **Reopening an existing episode**: selecting an episode from My Page
  (§2.5) loads its raw text into this same editor for continued editing,
  regardless of whether its status is `draft` or `submitted`.
- **Editing an already-validated episode**: saving edits to a `submitted`
  episode flips its status back to `draft`. Existing validation results
  (§2.4) remain visible but a "manuscript changed — results may be stale"
  banner is shown. Re-validation is never automatic — the author must click
  "Run validation" again, consistent with the save/validate separation.

### 2.3 World-building / character preset screens

World settings:
```
+--------------------------------------------------+
|  World Settings                       [+ Add]     |
+--------------------------------------------------+
|  [Magic system] Aud Mana System                   |
|   Mana is generated internally, max 3 uses/day    |
+--------------------------------------------------+
|  [Faction] Kingdom of Astel                       |
|   A monarchy ruling the eastern continent ...      |
+--------------------------------------------------+
```

Character settings:
```
+--------------------------------------------------+
|  Character — Seo-ha                     [Save]    |
+--------------------------------------------------+
|  Fixed attributes                                  |
|   name · age · eye color · hair color · height ·   |
|   scars · origin                                   |
+--------------------------------------------------+
|  Mutable attributes                                |
|   hairstyle · outfit · injury/health status ·      |
|   belongings                                       |
+--------------------------------------------------+
|  Personality / speech                              |
|   personality keywords · speech quirks ·           |
|   goals/values                                     |
+--------------------------------------------------+
```

- World settings: category (era/setting, magic-or-martial-arts system,
  faction/organization, history, other rules) + title + free-text content.
- Characters: three sections — fixed attributes / mutable attributes /
  personality & speech (personality & speech feeds OOC judgment).
- All of this is **optional input** — if left blank it gets auto-populated
  from manuscripts written in the editor (see §7.4 pipeline design below).

### 2.4 Validation result screen (core screen)

```
+-------------------------+--------------------------+
|                         |  Contradiction candidates (3) |
|   Manuscript body       |  1) Appearance mismatch    |
|  (contradicting spans   |     evidence -> Ep.3 "blue eyes" |
|   highlighted)          |  2) Location error         |
|                         |  3) Timeline contradiction |
+-------------------------+--------------------------+
```

- Manuscript and flags are laid out side by side so evidence sentences can
  be checked directly against the source text.
- Each flag supports "accept", "dismiss as false positive", and
  "supplement settings then re-validate" (add missing world/character
  settings and re-run validation for that flag right there).

Design principles for this area:
- Pre-entering character/location settings is optional — an
  unregistered character/location appearing in a manuscript is
  auto-created the first time it appears.
- New information that doesn't contradict anything is auto-merged into
  settings; anything that *does* contradict existing settings is never
  auto-corrected — always "surface it, let the author decide" (see §7.4).
- A contradiction flag can be resolved by supplementing settings and
  re-validating **just that flag**, not the whole pipeline (see §7.5).
- Flags are sorted by confidence; clicking the evidence sentence jumps to
  its location in the manuscript.

### 2.5 My Page screen

```
+--------------------------------------------------+
|  My Page                                          |
+--------------------------------------------------+
|  Account info                                      |
|   Nickname: NightShadow                  [Change]  |
|   Email: writer@email.com   Linked: Google         |
+--------------------------------------------------+
|  My novels                             [+ New]     |
|   Otherworldly Swordsman   Ep.42   updated 2d ago   |
|                     [Open] [Graph/Timeline] [Delete]|
|   Legacy of the Throne     Ep.12   updated 1w ago   |
|                     [Open] [Graph/Timeline] [Delete]|
+--------------------------------------------------+
|  Danger zone                                        |
|                                     [Delete account]|
+--------------------------------------------------+
```

- **Nickname change**: inline edit from the [Change] button (constraints in
  §3.6).
- **Novel management**: rename, open (episode list -> selecting an episode
  goes to the §2.2 editor; new episodes also start here), delete.
- **Novel delete**: confirmation modal, then soft-delete (kept 30 days,
  recoverable in that window) -> after that a batch job permanently deletes
  everything under that `novel_id`. The multi-tenancy design (all child data
  hangs off `novel_id`) makes the deletion scope unambiguous.
- **Account deletion**: kept in a separate "danger zone" to prevent
  accidental clicks; full procedure in §3.5 below.

### 2.6 Per-novel relationship graph / timeline screen

```
+--------------------------------------------------+
|  Otherworldly Swordsman — Graph/Timeline  [Graph][Timeline] |
+--------------------------------------------------+
|                                                    |
|      (render the §6 graph here)                    |
|                                                    |
+--------------------------------------------------+
```

- Only reachable from the novel list in My Page — even a direct URL hit is
  blocked unless the requester's `user_id` owns that novel (DB-level
  isolation, §8.1).
- A top tab switches between the character relationship graph (§6.2) and the
  story timeline graph (§6.3) — same graph component, different data
  binding (§6.4).

---

## 3. Auth & account

### 3.1 Login methods

| Method | Provider | Notes |
|---|---|---|
| Native login | Email + password | Password hashed (bcrypt or similar). Signup form includes a nickname (pen name) field. Before signup, a 6-digit code emailed to the address proves the author owns it. |
| Social login | Google | OAuth 2.0 (authorization code + PKCE). On first login the account is created once a nickname is chosen (§3.2). |

### 3.2 Social login flow

```
User clicks the Google login button
  -> Frontend sends the browser to Google (state + PKCE code challenge)
  -> Google returns an authorization code to the frontend's callback page
  -> Frontend sends the code + PKCE verifier to the API server
  -> API exchanges the code with Google (client secret stays on the server)
     for an ID token: Google account id + verified email
  -> API looks up the user by Google account id
  -> Existing account: API issues an auth token (JWE-encrypted)
  -> New account: API returns a short-lived signup token; frontend shows a
     nickname-setup screen; the nickname + signup token create the account,
     and API issues an auth token
```

An email already registered with a password is refused rather than linked:
accounts created before signup email verification existed never proved they own
the address, so linking by email would let whoever registered someone else's
Gmail address first into that person's account.

Key rule: **social login never auto-fills the nickname from the provider
profile name.** It is always entered directly by the user, so authors can
use a pen name instead of their real name.

### 3.3 Token encryption (JWE)

Issued auth tokens are not plain JWTs — they are **JWE-encrypted** so that
claims (user ID, novel access rights) aren't exposed in the token itself.

- Structure (nested JWT): claims are signed as a JWT (JWS, integrity) → the
  signed token is then encrypted as JWE (confidentiality).
- Example algorithms: signing RS256 / key management RSA-OAEP-256 / content
  encryption A256GCM.
- Only the server holds the decryption key; the client only stores/forwards
  the encrypted token.
- Request flow: frontend sends `Authorization: <JWE token>` -> API decrypts
  JWE -> verifies JWT signature -> uses claims (user_id, novel permissions).

### 3.4 Account structure

- One account can register and manage multiple novels.
- All data is isolated **per novel**, not per account — see the Data Model
  section below.

### 3.5 Account deletion (withdrawal)

```
My Page -> request withdrawal
  -> identity confirmation (re-enter password, or social re-auth)
  -> account marked "pending deletion" (users.deletion_requested_at set)
  -> 30-day grace period
     -> if user logs back in within the grace period: deletion is cancelled, account restored
     -> if grace period elapses: a batch job permanently deletes the account and all its novel data
```

- **Identity confirmation**: never delete immediately — require password
  re-entry (native login) or social re-auth first.
- **Grace period**: 30 days; logging back in during this window
  auto-cancels the deletion (protects against accidental withdrawal).
- **Deletion scope**: after the grace period, a batch job (reusing the
  queue/worker infra from §8.2 below) deletes every `novels` row owned by
  that `user_id`, plus everything hanging off those `novel_id`s (characters,
  locations, episodes, claims, flags, event graph, etc). The
  `user_id -> novels -> novel_id` chain from the multi-tenancy design makes
  the deletion scope unambiguous.
- **Irreversibility notice**: must be communicated clearly both at the time
  of the withdrawal request and during the grace period — after the grace
  period there is no recovery.

### 3.6 Nickname (pen name) rules

- **Initial setup**: native signup collects it on the signup form; social
  login collects it on a dedicated first-login screen (§3.2).
- **Change**: editable any time from My Page's account info section.
- **Constraints**: length 2–20 characters (counted after Unicode NFC
  normalization and stripping surrounding whitespace), and only letters,
  numbers and the ordinary space (combining marks allowed, at most 3 in a row
  and never leading a name). Emoji, punctuation, symbols, other kinds of
  whitespace and invisible / control characters (zero-width joiner, NUL, ...)
  are rejected, as are characters outside the Basic Multilingual Plane. Backend
  (`auth/schemas.py`) and frontend (`utils/nickname.ts`) apply the same rule.
  Duplicates are allowed — the real identifier is email/`user_id`, so nickname
  uniqueness is not enforced.

---

## 4. Data model

### 4.1 Multi-tenancy shape

```
users -> novels -> characters
                 -> locations
                 -> episodes
                 -> claims
                 -> contradiction_flags
```

Every entity table below carries a `novel_id` FK, and **every query must be
filtered by `novel_id`** (enforced at the application layer, and see §8.1 for
the RLS backstop).

- **users**: id, email, `nickname`, provider, provider_id, password_hash,
  created_at, `deletion_requested_at` (§3.5).
- **novels**: id, user_id FK, title, created_at, `deleted_at` (soft delete,
  §2.5) — one account can own many novels.

### 4.2 Dual time axes

Publication order and in-story time are different and can diverge (e.g. in
flashback episodes) — keep them separate:

| Axis | Meaning | Used for |
|---|---|---|
| `episode_index` | Publication order (which episode number) | The author's accumulated-facts order — basis for appearance/setting contradiction checks |
| `story_timestamp` | In-story time (day N in-story) | Basis for physical plausibility checks: travel distance, age, season |

### 4.3 Full table list

(all carry `novel_id` FK)

- **characters**: fixed attrs (name, age, eye color, hair color, height,
  scars, origin) + mutable attrs (hairstyle, outfit, injury/health status,
  belongings) + personality/speech (for OOC judgment). `source`
  (`manual`/`auto_detected`) distinguishes author-entered vs.
  auto-created-from-manuscript.
- **character_state_history**: state-change log keyed by `episode_index` and
  `story_timestamp`.
- **locations**: geography, distance/connections to other locations, same
  `source` field as characters.
- **world_settings**: category (era/setting, magic-or-martial-arts system,
  faction/organization, history, other rules), title, free-text content.
- **location_state_history**: location state-change log.
- **relations**: character-to-character relationships, and
  location-to-location distance/connection info.
- **episodes**: full manuscript text + embedding. `status`
  (`draft`/`submitted`) tracks writing-in-progress vs. submitted-for-
  validation; `updated_at` tracks the last **Save** button press (§2.2).
  Editing a `submitted` episode flips it back to `draft` (§2.2).
- **claims**: extracted validation-target assertions from a manuscript.
- **contradiction_flags**: error type, confidence, evidence sentence(s),
  `status` (`open`/`resolved_by_revalidation`/`accepted`/`dismissed`).
- **story_events**: event nodes — id, episode_index, story_timestamp,
  title/summary. Nodes of the story timeline graph.
- **event_participants**: characters participating in an event (event_id,
  character_id).
- **event_locations**: locations where an event occurs (event_id,
  location_id).
- **event_links**: connections between events (from_event_id, to_event_id,
  `link_type`: sequential/branch/merge, `branch_reason`: which
  character/location caused the branch).

### 4.4 Indexes

- Composite `(novel_id, entity_id, episode_index)`
- Composite `(novel_id, entity_id, story_timestamp)`
- Composite `(novel_id, from_event_id)`, `(novel_id, to_event_id)` — for
  event-graph traversal
- `novel_id` should be the leading column everywhere, so lookups are always
  scoped to one novel.

---

## 5. AI / tech stack

| Component | Choice | Notes |
|---|---|---|
| Embedding | KURE-v1 + BM25 hybrid | Combines semantic search with keyword matching |
| Cross-encoder reranker | bge-reranker-v2-m3-ko family | Extracts top-K relevant past setting sentences |
| NLI | klue-roberta + KorNLI base | Needs re-finetuning for novel narrative/dialogue register |
| LLM (external API) | model TBD | OOC judgment, ambiguous-contradiction final check, claim extraction |
| DB | PostgreSQL + pgvector | Vector search and structured data in one DB |

---

## 6. Code structure

### 6.1 Architecture

```
Frontend -> API server -> Auth module
                        -> Validation pipeline -> Embedding/reranker
                                                -> NLI module
                                                -> LLM integration
                                                -> PostgreSQL + pgvector
API server -> PostgreSQL + pgvector
```

### 6.2 Folder layout

```
retcona/
├── frontend/     # login, preset cards, upload, validation result screens
├── backend/
│   ├── api/       # REST endpoints
│   ├── auth/        # login, social login (OAuth), token issuance
│   ├── pipeline/       # extract_claims, context_bundle, 3 judgment modules, merge
│   ├── models/           # DB models (users, novels, characters, locations, ...)
│   ├── ai/                 # embedding / reranker / NLI / LLM client wrappers
│   ├── workers/              # cpu_worker / gpu_worker entrypoints (branch on WORKER_TYPE)
│   └── infra/                  # QueueClient / StorageClient etc. cloud abstraction layer
└── db/                            # migrations · schema
```

- The 3 judgment modules under `pipeline/` share one interface
  (`claims + context_bundle` in -> `flags` out) so they can run in parallel
  and be swapped independently.
- Every `models/` and `pipeline/` function should require `novel_id` as a
  mandatory argument, so isolation gaps are caught at the code level.
- `pipeline/` and `ai/` hold business logic only — queue/storage access
  always goes through the `infra/` interfaces (see §8.4).

---

## 7. Pipeline design

### 7.1 Processing flow

```
Manuscript input -> extract_claims (claim extraction)
  -> entity matching
     -> unregistered character/location: auto-create new entity
     -> known entity: -> get_context_bundle (shared context lookup)
  -> [appearance/behavior module, location module, spacetime module]
     (all three read from the same context bundle)
  -> merge_and_dedupe (merge results)
     -> non-contradicting claims: auto-merge into settings
     -> -> validation result screen
```

### 7.2 Judgment modules

| Module | Key input fields | Judgment method |
|---|---|---|
| Appearance/behavior violation | `fixed_attrs`, `latest_mutable_state`, `personality`, `world_settings` | Appearance: NLI. Behavior (OOC): LLM + personality/speech profile + world-rule-based reasoning |
| Location error | `fixed_attrs` (geography), `relations` (distance) | NLI + rule-based distance calculation |
| Spacetime contradiction | `last_known_position`, `state_history`, `relations` | Rule-based time/distance checks + LLM assist |

### 7.3 Parallelization notes

- Avoid context silos: all three modules must be able to reach whatever they
  need through the shared context bundle.
- Result merge is required: dedupe multiple flags pointing at the same root
  cause.
- Resource contention: external LLM API rate limits; local models should use
  batch serving (e.g. vLLM).

### 7.4 Auto entity registration & auto setting merge

- **Entity matching**: match a claim's character/location name against
  existing `characters`/`locations` by name/alias (string match + embedding
  similarity for aliases).
- **New registration**: no match -> auto-create a new record with
  `source: auto_detected`, storing the first mention as the initial fixed
  attributes — so characters/locations the author never pre-entered still
  get a setting card from the manuscript alone.
- **Auto merge**: claims that aren't flagged as contradictions are
  automatically appended to `character_state_history` /
  `location_state_history`, so setting cards fill themselves in as the
  story progresses.
- Only contradiction-flagged claims require author confirmation before being
  applied (§2.4 principle) — auto-merge is limited strictly to "adding new
  information"; "modifying existing settings" always requires author
  confirmation.

### 7.5 Re-validation after supplementing settings

An author may look at a flag and decide "actually this is correct because of
a world rule I hadn't entered yet" — in that case they add the missing
setting and re-validate just that flag.

```
Validation result screen -> supplement world/character settings
  -> re-validation request (enqueued on the job queue)
  -> only the judgment module that raised that flag re-runs
     -> contradiction resolved: flag auto-transitions to resolved_by_revalidation
     -> still contradicts: flag stays open, evidence refreshed
  -> back to validation result screen
```

- Never re-run the whole pipeline — only the judgment module that produced
  the flag, against a fresh context bundle. Saves cost.
- Also goes through the job queue (§8.2), processed asynchronously.
- A flag resolved via re-validation keeps a record of which setting resolved
  it, to help reduce similar false positives later.

---

## 8. Concurrency, multi-tenancy & deployment

### 8.1 DB-level isolation

- Every read/write is forced through a `novel_id` filter (repository
  functions require `novel_id` as a mandatory argument).
- Consider PostgreSQL **Row-Level Security (RLS)** as a defense-in-depth
  layer — set `novel_id` on the session and enforce via policy, so an
  application-code mistake still can't leak across novels.
- pgvector similarity search must also always be scoped by `novel_id` —
  otherwise another user's setting sentences could leak into results.

### 8.2 Job queue for concurrent requests

Validation requests are not processed synchronously — they're enqueued as
async jobs:

```
API server -> job queue -> worker 1, worker 2 (parallel) -> DB
Frontend polls the API for job status
```

- New episode validation request -> enqueue -> workers process in parallel
  -> results saved to DB -> client polls/websockets for completion.
- The editor's (§2.2) "Run validation" button is the entry point that
  enqueues onto this queue.
- API responses stay fast under load since processing is decoupled.

### 8.3 AI resource contention

- Local models (NLI, reranker): batch-serving framework (e.g. vLLM) to
  batch multiple users' requests together.
- External LLM API: concurrency limit (semaphore) + retry backoff on rate
  limit.
- DB connections: connection pooling (e.g. PgBouncer) to avoid exhaustion
  under concurrent load.

### 8.4 GCP-oriented worker scaling design

#### Worker types

| Worker type | Role | Characteristics | Scaling |
|---|---|---|---|
| CPU worker | Claim extraction orchestration, rule-based checks, LLM API calls | I/O-bound, throughput scales linearly with count | Horizontal autoscaling on queue depth |
| GPU worker | Embedding, reranker, NLI inference | Needs batching for efficiency, adding instances alone doesn't help | Batch serving (vLLM) + limited scaling |

#### GCP service mapping

| Component | GCP service |
|---|---|
| Job queue | Pub/Sub |
| CPU worker runtime | Cloud Run |
| GPU worker runtime | Compute Engine GPU + MIG (or Cloud Run GPU) |
| DB | Cloud SQL for PostgreSQL (+pgvector) |
| DB connection management | Cloud SQL Auth Proxy + PgBouncer |
| Object storage | Cloud Storage |

#### Interface abstraction

To support local-dev ↔ GCP switching and the staged backend transition
(CPU↔GPU, external API↔self-hosted) with zero code changes, queue / storage /
inference / LLM access all sit behind interfaces:

```
pipeline & worker code
  -> QueueClient interface -> PubSubQueueClient (prod) / local Redis-based impl (dev)
  -> StorageClient interface -> GCSStorageClient
  -> InferenceClient interface -> CPU impl / GPU impl
  -> LLMClient interface -> external-API impl / self-hosted impl
```

- `QueueClient` exposes only `enqueue(job)` / `dequeue()` / `ack(job_id)` —
  business logic never knows the concrete implementation.
- `InferenceClient` and `LLMClient` pick their implementation via
  `INFERENCE_BACKEND=cpu|gpu` and `LLM_PROVIDER=external|self_hosted` env
  vars. The judgment modules (§7.2) call only the interface, so staged
  transitions (§8.5) require zero business-logic changes.

#### Worker code requirements

- **Stateless**: a worker must complete a job using only the job payload and
  DB reads — no local disk/memory state, since autoscaling can start/stop
  instances at any time.
- **Idempotent**: every job gets a unique ID and completion is recorded in
  DB, so at-least-once queue delivery can't cause duplicate side effects.
- **Graceful shutdown**: on SIGTERM, finish the in-flight job or return it to
  the queue (ack deadline) before exiting — avoid losing work on scale-in.
- **Role branching**: one image, entrypoint chosen by `WORKER_TYPE=cpu|gpu`
  env var, so the same code is reused for both instance types.

#### Autoscaling triggers

- CPU/LLM workers: scale on queue depth — Cloud Run autoscaling by
  concurrency.
- GPU workers: queue depth + GPU utilization combined signal; consider a
  warm pool (min instances) since cold starts are expensive.

### 8.5 Cost-minimized staged rollout

Start with zero standing infra cost wherever possible, pay only for usage.

#### Initial cost-minimized config (GCP)

| Component | Initial choice | Note |
|---|---|---|
| LLM | External API | Avoids standing GPU hosting cost |
| NLI / reranker | CPU-based Cloud Run | Lower accuracy, but no GPU cost |
| CPU worker | Cloud Run, `min-instances=0` | $0 when idle |
| Job queue | Pub/Sub | Within free tier |
| Frontend / storage | Cloud Storage | Within free tier |
| Illustration generation | Deferred | Matches its low-priority roadmap stage |

DB is the one exception with a standing cost: Cloud SQL bills even at rest.
Early on, replace it with PostgreSQL + pgvector self-hosted on GCP's
always-free e2-micro VM — low-spec, so migrate to Cloud SQL once traffic
grows.

#### Staged transition

```
Stage 1 (validate): fully serverless + external API, DB on self-hosted e2-micro
  -> Stage 2 (user growth): move NLI/reranker to Cloud Run GPU
  -> Stage 3 (predictable traffic): move DB to Cloud SQL, consider self-hosted LLM
```

#### Making the transition code-free

- **Backend choice is entirely config**: flipping `INFERENCE_BACKEND`,
  `LLM_PROVIDER`, `QUEUE_PROVIDER` env vars (§8.4) is the entire 1→2→3
  transition. Judgment modules (§7.2) and pipeline code never need to know
  which backend is active.
- **DB connection is one config value (`DATABASE_URL`)**: code always
  connects via a local socket/port; whether that's e2-micro Postgres or a
  Cloud SQL Auth Proxy is purely an infra concern. Moving DBs only changes a
  connection string.
- **Autoscaling params live in deploy config (IaC), not code**: e.g.
  Terraform, not app code — bumping `min-instances` or worker count doesn't
  require redeploying the app.
- **DB migration path decided up front**: e2-micro -> Cloud SQL via standard
  `pg_dump`/`pg_restore` (or logical replication); use Alembic from day one
  so schema state is reproducible in both environments.
- **Both implementations tested per interface**: run the same test suite
  against both the cpu/gpu and external/self-hosted implementations of
  `InferenceClient`/`LLMClient`, so the transition isn't the first time
  they're validated.

---

## 9. Character relationship graph & story timeline

### 9.1 Data sources

- **Character relationship graph**: rendered from the `relations` table.
  Needs `relation_type` (family/romantic/rival/etc.) and `direction` columns
  to express relationship type and directionality.
- **Story timeline graph**: rendered from `story_events` +
  `event_participants` + `event_locations` + `event_links`. Events are nodes
  and connections between events are edges — this is necessary (rather than
  per-character/location state logs alone) to represent branching and
  merging storylines.
- `event_links` are generated semi-automatically: either the author
  explicitly points to the next event, or `extract_claims` proposes links by
  extracting event claims (participating characters/locations/episode) —
  same "surface it, author confirms" principle as elsewhere.

### 9.2 Character relationship graph

Characters as nodes, `relations` as edges. Edge label = relationship type,
directional relationships shown with arrows.

Example: protagonist —romantic→ heroine; protagonist —rival→ antagonist;
heroine —sibling→ supporting character; antagonist —mentor-disciple→ mentor.

### 9.3 Story timeline graph

`story_events` as nodes, `event_links` as edges. When characters/locations
from one event later diverge, that's a branch; when separate event chains
converge into the same event, that's a merge.

Example: "Ep.10 protagonist & heroine depart together" branches into
"Ep.12 protagonist arrives at the castle" (protagonist -> castle) and
"Ep.12 stays in the village" (heroine -> village); these separately lead to
"Ep.18 duel with rival at the castle" and "Ep.20 village raid", which then
both merge into "Ep.22 reunion".

### 9.4 Implementation approach

- Both graphs are node/edge structures, so reuse the same force-graph /
  D3.js-family component on the frontend for both.
- On screen entry, the server queries relation/event/link data scoped to
  that `novel_id` and returns node/edge JSON for the graph.
- Entry point is the My Page per-novel screen (§2.6) — not a separate
  dashboard menu, always reached via "my novels" -> pick a novel.

---

## 10. Character illustration generation (optional / low priority)

- Independent module, separate from the core plausibility engine.
- Flow: character setting card's fixed appearance attributes -> prompt
  conversion -> text-to-image API call.
- Core challenge: visual consistency across generations for the same
  character (reference-image-based generation, character LoRA training,
  etc. need evaluation).
- Deliberately lowest development priority.

---

## 11. MVP roadmap

| Stage | Content |
|---|---|
| 1 | Login/social login + My Page (novel mgmt, account deletion) + manuscript editor (local draft/save) + per-episode entity extraction, multi-tenancy-aware setting card schema |
| 2 | Appearance mismatch + location contradiction detection (NLI-based) |
| 3 | Re-validation after supplementing settings (per-flag re-judgment) |
| 4 | Event timeline cross-check (state-history accumulation logic) |
| 5 | OOC behavior detection (LLM-based) |
| 6 | Concurrency handling (job queue, RLS, etc.) fully adopted + cloud deployment, worker autoscaling |
| 7 | Character relationship graph / story timeline visualization |
| 8 (optional) | Character illustration generation |
