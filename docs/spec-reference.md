# Spec Reference

English working reference for the Retcona design doc (`README.md`, written in
Korean). This covers the full product + implementation spec, written as if
no part of the project has been built yet, so that during implementation you
can read this file instead of the full README each time.

---

## 0. Product summary

Retcona ("Recording Every Timeline Change: Oversight Network, Assistant") is
a free, open-source Windows desktop app for web-novel authors: manuscripts
and settings stay on the author's PC. While an author serializes a long-form
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

1. **Novel management** — no sign-up or login: the app opens on the list of
   novels; manage several novels; view each one's relationship graph/
   timeline. Everything is stored on the author's PC.
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
And since it runs on the author's PC, an unpublished manuscript never goes to
a server — the only thing that sends any of it out is an LLM connection the
author turns on (§3).

---

## 1. System overview

- **Purpose**: when a new episode's manuscript is submitted, automatically
  cross-check it against accumulated settings/records and surface
  plausibility-error candidates.
- **Three validation perspectives**: appearance/behavior violations,
  location errors, spacetime (timeline) contradictions.
- **Design principle**: split module boundaries by **judgment perspective**,
  not by data type (character vs. location) — data lookups happen in one
  shared layer. One author uses the app on their own PC, but all data is
  still grouped per novel so one novel's settings never leak into another's
  validation.

---

## 2. UX design

### 2.1 Overall screen flow

```
Novel list (home) -> Preset management (optional): characters · locations
Novel list -> Manuscript editor
  editor --(save)--> editor
  editor --(run validation)--> automatic validation run (includes auto-registering new characters/locations)
    -> Validation result screen
       --(accept)--> setting history updated
       --(dismiss as false positive)--> flag dismissed
       --(supplement settings)--> add world/character settings -> re-run validation -> back to validation result screen
Novel list -> pre-writing brief / checklist
Novel list -> per-novel relationship graph · timeline (scoped to that novel_id only)
Novel list -> Settings: LLM connection · inference device · data folder
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
  the app's WebView storage (debounced, on a short delay) — not yet to the
  database. It's a safety net against a crash or a closed window: the text
  since the last **Save** is still recoverable, and reopening the episode
  offers it back if the saved copy is older. It's flushed one last time when the tab
  is hidden or the editor is left, and dropped once a save confirms the
  database has the same text. A confirmation is shown before leaving with changes this
  draft failed to capture (storage blocked, full, or otherwise unavailable) —
  the only case leaving the editor can actually lose text.
- **Save**: the only thing that writes the database. Manual, immediate save
  button; does not trigger the AI pipeline.
- **Run validation**: enqueues the saved manuscript onto the local job queue
  (§8.2) to run the pipeline. Saving (write) and validating (AI processing)
  are intentionally separate so every keystroke doesn't trigger an AI call.
- **Reopening an existing episode**: selecting an episode from the novel
  list (§2.5) loads its raw text into this same editor for continued editing,
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

### 2.5 Novel list & settings screens

```
+--------------------------------------------------+
|  My novels                    [+ New]  [Settings]  |
+--------------------------------------------------+
|   Otherworldly Swordsman   Ep.42   updated 2d ago   |
|                     [Open] [Graph/Timeline] [Delete]|
|   Legacy of the Throne     Ep.12   updated 1w ago   |
|                     [Open] [Graph/Timeline] [Delete]|
+--------------------------------------------------+
|   Trash (1)                                         |
+--------------------------------------------------+
```

```
+--------------------------------------------------+
|  Settings                                          |
+--------------------------------------------------+
|  LLM connection (OOC judgment, optional)           |
|   Connected: ChatGPT (Plus)     [Change] [Disconnect]|
+--------------------------------------------------+
|  Inference device  (o) Auto (GPU first)  ( ) CPU only |
|  Data folder  C:\Users\...\Retcona     [Open] [Back up] |
+--------------------------------------------------+
|  About · open-source licenses · model data sources |
+--------------------------------------------------+
```

- The app opens on the novel list — there are no accounts, so no login,
  sign-up or withdrawal screens.
- **Novel management**: rename, open (episode list -> selecting an episode
  goes to the §2.2 editor; new episodes also start here), delete.
- **Novel delete**: confirmation modal, then to the trash (kept 30 days,
  recoverable in that window) -> after that, while the app runs, a job
  permanently deletes everything under that `novel_id`. All child data hangs
  off `novel_id` (§4.1), so the deletion scope is unambiguous.
- **Settings**: the LLM connection (§3), the inference device (§8.3), opening
  and backing up the data folder (§8.1), and the app's licenses and the
  models' training-data sources (§8.5.2).

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

- Reached from the novel list (§2.5); every query is scoped to that novel's
  `novel_id` (§8.1).
- A top tab switches between the character relationship graph (§6.2) and the
  story timeline graph (§6.3) — same graph component, different data
  binding (§6.4).

---

## 3. LLM connection (OOC judgment, optional)

The LLM is used only for the hard OOC cases left after rules and NLI (§7.2).
The app neither bundles an LLM nor pays for one: the author connects the LLM
they already use. Without a connection, claim extraction and the appearance,
location and spacetime judgments all still run on the models on the PC; only
OOC's LLM step is off.

### 3.1 Ways to connect

| Way | For | Notes |
|---|---|---|
| Sign in with ChatGPT | ChatGPT Go / Plus / Pro subscribers | OpenAI's "Sign in with ChatGPT" plan-usage permission: no API key or separate billing, usage comes out of the plan. OpenAI allows it for open-source and locally run apps. Requests go to the Responses API |
| API key | Anthropic; OpenAI-compatible (OpenAI, Google Gemini, Groq, OpenRouter, ...) | The author creates the key in the provider's developer console; billed per use, separately from any chat subscription |
| Local server | Ollama, LM Studio, other OpenAI-compatible servers | The manuscript never leaves the PC; quality and speed depend on the GPU |

- Claude and Gemini chat subscriptions can't be used by other apps under
  those providers' terms (as of 2026): they connect by API key only.
- Two adapters: the Anthropic Messages API, and OpenAI-compatible (built on
  the Responses API, which Sign in with ChatGPT uses too).
- The author picks the model; the app only suggests one per connection.

### 3.2 Storing keys and tokens

- API keys and the ChatGPT sign-in token are kept in Windows Credential
  Manager — never in plain text in the database or a config file.
- A key is only ever sent to its own provider.

### 3.3 Notice and consent

- When an LLM connection is first turned on, the app says that OOC judgment
  sends parts of the manuscript (the passage, the character's personality/
  speech settings) to that provider, and asks for consent.
- A free tier that trains on its inputs (e.g. the Gemini API's free tier,
  whose inputs improve Google's models and may be read by human reviewers)
  gets its own warning.

### 3.4 Calling the LLM

- One episode's OOC candidates are batched into as few calls as possible; a
  concurrency limit and retry backoff keep it under per-minute limits.
- A failure (rate limit 429, expired sign-in, ...) marks only that judgment
  "OOC not judged" and shows the rest of the results; it can be retried
  later.
- Since any model may be on the other end, the response format is fixed
  JSON; a malformed response counts as no judgment.

---

## 4. Data model

### 4.1 Per-novel shape

A single-user app with no accounts: there is no `users` table, and the novel
is the top level. All data is grouped **per novel**, so one novel's settings
never mix into another's validation, and deletion or export is scoped by one
`novel_id`.

```
novels -> characters
       -> locations
       -> episodes
       -> claims
       -> contradiction_flags
```

Every entity table below carries a `novel_id` FK, and **every query must be
filtered by `novel_id`** (enforced at the application layer, §8.1).

- **novels**: id, title, created_at, `deleted_at` (moved to the trash,
  §2.5).

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
| App shell | Tauri 2 + the React frontend | Uses Windows' WebView2, so the installer stays small; also installs and updates |
| Local backend | FastAPI, bundled with PyInstaller and started by the shell | Listens on 127.0.0.1 only (§8.4.2) |
| Inference runtime | ONNX Runtime — GPU (DirectML), else CPU | NVIDIA, AMD and Intel GPUs alike. Training stays in `ml/` on PyTorch and exports to ONNX — the app ships no PyTorch |
| Morphological analysis | kiwipiepy | Part-of-speech tags for the extraction rules (§7.1.1) |
| Embedding | KURE-v1 + BM25 hybrid | Combines semantic search with keyword matching |
| Cross-encoder reranker | bge-reranker-v2-m3-ko family | Extracts top-K relevant past setting sentences |
| NLI | klue-roberta + KorNLI base | Needs re-finetuning for novel narrative/dialogue register |
| NER | klue-roberta, fine-tuned in-house | Claim extraction — finding character/location names (§7.1.1) |
| Extractive QA | klue-roberta, fine-tuned in-house | Claim extraction — pulling attribute values out of a sentence (§7.1.1) |
| LLM | The one the author connects (§3) | **OOC judgment only, optional** — the hard cases left after rules and NLI (§7.2) |
| DB | SQLite (vector search: sqlite-vec) | One file on the author's PC — no database server to install or run |

The embedding model and reranker are large (KURE-v1 is about 570M
parameters); whether the app ships them, or uses them only with a GPU, is
decided when they're implemented.

---

## 6. Code structure

### 6.1 Architecture

```
Desktop shell (Tauri) -> Frontend (React)
Frontend -> Local backend (FastAPI, 127.0.0.1) -> Job runner -> Validation pipeline -> Local models (ONNX Runtime)
                                                                                     -> LLM connection (the author's plan / API key)
                                                                                     -> SQLite
Local backend -> SQLite
```

### 6.2 Folder layout

```
retcona/
├── desktop/      # Tauri shell: starts the backend process, installer, updates
├── frontend/     # novel list, preset cards, editor, validation result screens
├── backend/
│   ├── api/       # REST endpoints (called only by the frontend in the shell)
│   ├── pipeline/       # extract_claims, context_bundle, 3 judgment modules, merge
│   ├── models/           # DB models (novels, characters, locations, ...)
│   ├── ai/                 # embedding / reranker / NLI / LLM client wrappers
│   ├── workers/              # local job runner (validation, re-validation, emptying the trash)
│   └── infra/                  # job queue / inference / LLM / storage interfaces and implementations
├── ml/           # model training and evaluation (PyTorch), ONNX export
└── db/           # migrations · schema
```

- The 3 judgment modules under `pipeline/` share one interface
  (`claims + context_bundle` in -> `flags` out) so they can run in parallel
  and be swapped independently.
- Every `models/` and `pipeline/` function should require `novel_id` as a
  mandatory argument, so cross-novel mix-ups are caught at the code level.
- `pipeline/` and `ai/` hold business logic only — queue, inference, LLM and
  storage access always goes through the `infra/` interfaces (see §8.4.3).

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

### 7.1.1 Claim extraction (no LLM)

The LLM is used for OOC judgment only (§7.2); claim extraction runs on small
in-house models and rules — it's most of the volume, so this removes its cost
and lets it run locally.

1. **Sentence split**: split the manuscript into sentences; mark dialogue
   (inside quotes).
2. **Names**: string-match registered names/aliases, plus an NER model for
   names not registered yet.
3. **Attribute cues**: only sentences with an attribute's cue words ("눈동자",
   "머리카락", "흉터", "살", "출신", ...) are candidates.
4. **Values**: an extractive QA model pulls the value out of the sentence
   (e.g. "레온의 눈 색깔은?" -> "푸른색").
5. **Pronouns / dropped subjects**: rules — among the characters named in the
   sentence and the 2-3 before it, link only when exactly **one** candidate
   fits (gender included), otherwise skip (missing a claim does less harm
   than holding it against the wrong card). Judgment passes the preceding
   named sentence along so NLI reads it in context. Character cards get a
   gender field for this.
6. **Namesakes**: not told apart by context — an alias in the text picks
   the card; a name alone that fits several cards stays unlinked (§7.4).

If pronoun handling proves too weak, a model trained on a coreference corpus
is the next step.

### 7.2 Judgment modules

| Module | Key input fields | Judgment method |
|---|---|---|
| Appearance/behavior violation | `fixed_attrs`, `latest_mutable_state`, `personality`, `world_settings` | Appearance: NLI. Behavior (OOC): speech level (honorifics etc.) by rules and contradictions of stated traits by NLI first; only the remaining hard cases go to the LLM + personality/speech profile + world-rule-based reasoning |
| Location error | `fixed_attrs` (geography), `relations` (distance) | NLI + rule-based distance calculation |
| Spacetime contradiction | `last_known_position`, `state_history`, `relations` | Rule-based time/distance checks |

There is no LLM re-check of contradictions NLI finds ambiguous — the author
makes the final call (accept / dismiss), and the dismissals collected over
time tune NLI's contradiction threshold.

### 7.3 Parallelization notes

- Avoid context silos: all three modules must be able to reach whatever they
  need through the shared context bundle.
- Result merge is required: dedupe multiple flags pointing at the same root
  cause.
- Resources: one validation job at a time so the author's GPU memory isn't
  exceeded, with sentences batched for inference (§8.3); the LLM within the
  author's own limits (§3.4).

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
- Also goes through the local job queue (§8.2), processed asynchronously.
- A flag resolved via re-validation keeps a record of which setting resolved
  it, to help reduce similar false positives later.

---

## 8. Runtime & distribution (Windows desktop app)

A free, open-source app one author runs on their own PC. There's no server,
so manuscripts and settings stay on the PC — except what the author's own LLM
connection sends (§3), and model downloads and update checks (§8.5).

### 8.1 Data storage & per-novel isolation

- Data lives in one SQLite file under `%LOCALAPPDATA%\Retcona`.
- Every read/write is forced through a `novel_id` filter (repository
  functions require `novel_id` as a mandatory argument), so one novel's
  settings never enter another's validation or search; vector similarity
  search is always scoped by `novel_id` too.
- Backup: the settings screen (§2.5) backs up the whole database file and
  exports/imports one novel as a file.

### 8.2 Local job queue

Validation requests are not processed synchronously — they're enqueued as
async jobs:

```
Frontend -> local backend -> job queue (an SQLite table) -> job runner (in the backend process) -> SQLite
Frontend polls the backend for job status
```

- Validation, re-validation and emptying the trash are enqueued and run one
  at a time by a job runner inside the backend process — a database table
  as the queue, no Redis, so pending jobs survive closing the app.
- The editor's (§2.2) "Run validation" button is the entry point that
  enqueues onto this queue.
- One job at a time keeps the GPU's memory in bounds.

### 8.3 Local resources

- **Inference device**: ONNX Runtime on the GPU (DirectML) where there is
  one, the CPU where there isn't or it fails; settings (§2.5) can force CPU
  only. NER, QA and NLI are ~110M-parameter models, practical on a CPU.
- **Models**: loaded on first use and kept while the app runs; sentences are
  batched.
- **LLM**: within the author's own limits (§3.4).

### 8.4 App layout

#### 8.4.1 Processes

| Part | Role |
|---|---|
| Desktop shell (Tauri) | Window, starting/stopping the local backend, install and update |
| Local backend (FastAPI) | API + job runner (§8.2) + model inference |
| Frontend (React) | Shown in the shell's WebView |

#### 8.4.2 Protecting the local backend

- Bound to a random port on 127.0.0.1 only; every request must carry a
  secret the shell generates at each launch, so other programs on the PC and
  web pages in a browser can't call the API. The Host header is checked too,
  against DNS rebinding.

#### 8.4.3 Interface abstraction

So that changing the inference device (GPU/CPU) or the LLM connection (§3.1)
never changes business logic, queue / storage / inference / LLM access all
sit behind interfaces:

```
pipeline & job runner code
  -> QueueClient interface -> local queue (SQLite)
  -> StorageClient interface -> local files
  -> InferenceClient interface -> ONNX Runtime GPU / ONNX Runtime CPU
  -> LLMClient interface -> Sign in with ChatGPT / Anthropic API / OpenAI-compatible API (local servers too)
```

- `QueueClient` exposes only `enqueue(job)` / `dequeue()` / `ack(job_id)`,
  plus `recover()` at startup (§8.4.4) — business logic never knows the
  concrete implementation. A job is enqueued in the same transaction as the
  row it works on (a validation run, ...), so neither exists without the other.
- `StorageClient` stores illustrations etc. in the data folder (§8.1).
- `InferenceClient` and `LLMClient` pick their implementation from the
  settings (§2.5); the judgment modules (§7.2) call only the interface.
- The same test suite runs against every implementation of an interface
  (GPU/CPU, each LLM adapter).

#### 8.4.4 Job requirements

- **Stateless**: a job completes using only its payload and DB reads.
- **Idempotent**: every job gets a unique ID and completion is recorded in
  the DB, so running one twice can't change the result.
- **Recoverable**: a job in progress when the app closes goes back on the
  queue at the next launch.

### 8.5 Distribution & updates

#### 8.5.1 Installer

- A Windows installer built by Tauri's bundler, published on GitHub
  Releases.
- It holds the app and the local backend only; the models are downloaded on
  first run (§8.5.2), keeping the installer small and letting the models be
  updated on their own.
- Without code signing, Windows SmartScreen warns on install — how to sign is
  decided in the pre-release checklist.

#### 8.5.2 Models & attribution

- The NER, QA and NLI models are exported to ONNX and published in a public
  Hugging Face repository; the app downloads them on first run and checks
  their SHA-256. Each app version pins the model versions it downloads.
- Their training data (KLUE, KorNLI) is CC BY-SA 4.0, so the models are
  released under CC BY-SA 4.0, credited in the model cards and in the app's
  About screen (§2.5).

#### 8.5.3 Updates & network use

- Tauri's updater checks GitHub Releases and installs signed updates only.
- Nothing else is sent by the app on its own (no usage statistics); tuning
  the NLI threshold from dismissals (§7.2) happens on the PC only.

#### 8.5.4 Schema migrations

- Alembic, as now; the app upgrades the schema at startup after backing up
  the database file, and restores it if the upgrade fails.
- SQLite's `ALTER TABLE` is limited, so migrations use Alembic's batch mode.

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
- On screen entry, the local backend queries relation/event/link data scoped
  to that `novel_id` and returns node/edge JSON for the graph.
- Entry point is the novel list (§2.5) — not a separate menu, always reached
  via "my novels" -> pick a novel.

---

## 10. Character illustration generation (optional / low priority)

- Independent module, separate from the core plausibility engine.
- Flow: character setting card's fixed appearance attributes -> prompt
  conversion -> a text-to-image API the author connects (like the LLM, §3).
- Core challenge: visual consistency across generations for the same
  character (reference-image-based generation, character LoRA training,
  etc. need evaluation).
- Deliberately lowest development priority.

---

## 11. MVP roadmap

| Stage | Content |
|---|---|
| 1 | Novel management + manuscript editor (local draft/save) + per-episode entity extraction, per-novel setting card schema (the web service's login and account deletion are removed in stage 6) |
| 2 | Appearance mismatch + location contradiction detection (NLI-based) |
| 3 | Re-validation after supplementing settings (per-flag re-judgment) |
| 4 | Event timeline cross-check (state-history accumulation logic) |
| 5 | OOC behavior detection (rules and NLI + the author's LLM connection, §3) |
| 6 | Desktop app: accounts removed, local job queue, SQLite, ONNX Runtime (GPU/CPU), first-run model download, installer and updates (§8) |
| 7 | Character relationship graph / story timeline visualization |
| 8 (optional) | Character illustration generation |

Stage 6 can come before stage 5: the LLM connection's key storage and settings
screen (§3) assume the single-user desktop app.
