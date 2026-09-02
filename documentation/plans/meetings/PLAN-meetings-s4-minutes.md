# PLAN - Meetings S4: Minutes (LLM, prompt registry + editor, action items)

**Status:** DONE 2026-09-02 - P1-P3 complete, opus review applied, live-verified on the pilot (3 real meetings ready, zh case proven). PR pending final full-suite run. Open volume gate: AC-S4-11 ten meetings (Sep 2-4 recordings).
**Branch:** stacks on `sprint-5/meetings-s3-codeswitch` (PR #38, CI green) or on main once #38 merges.

## Grill rulings (2026-09-01, captain)

- **R1** Platform default LLM = **gemini flash**, pinned `gemini-3.5-flash` (captain 2026-09-01: 2.5 flash is discontinued). Platform key = new env var on the pilot host, captain provides. Tenant override = `tenant_settings.llm_connection_id`
  pointing at a `type="llm"` connection (provider + key from the connection). Platform default keys
  live in env settings (`meetings_llm_provider` / `meetings_llm_model` / `meetings_llm_api_key`),
  mirroring the `meetings_stt_*` platform-setting precedent.
- **R2** Minutes job **auto-enqueues** on `meetings.transcribe` success. The `ready` hop moves here:
  transcribe still sets `transcribed` (jobs.py:396 unchanged); `meetings.minutes` success sets
  `ready`. Failure leaves the meeting at `transcribed` - retry by re-enqueueing the job.
- **R3** S4 is **API only** for minutes consumption/editing (GET, PUT new version, action-item
  toggle). The meetings UI surface is S5. Exception: the **prompt registry editor UI ships in S4**
  (captain: "we need UI for this"), platform admin only.
- **R4** Prompt registry = port of sorento's two-table mechanism (`ai_prompt_versions` immutable
  append-only + `ai_prompt_labels` publish-by-repoint), justification carried with it: prompts are
  runtime-editable without deploys, publishes are instant and reversible, history is auditable.
  Lives in shared-service **core** (`app/models/ai_prompt.py`) since it is platform infra, seeded
  with the minutes prompt v1.
- **R5a** Manual regenerate ships in S4: `POST /meetings/{id}/minutes/regenerate`
  (`meetings.manage`) enqueues the minutes job; result appends the next version.
- **R5b** Action-item owner: stored raw (`owner_email` as the LLM emitted it). The S5 UI
  resolves it against participants at render time - matched shows the participant chip,
  unmatched shows the raw text. No stored FK; trigger for one = assignment features (M16-style
  notify per owner).
- **R5** Platform admin only for the editor (`isPlatformTenant` + permission). Per-tenant prompt
  forks: not built; trigger = a second tenant asking for different minutes structure.

## 1. What S4 delivers

After S3 leaves a meeting `transcribed`, S4:

1. auto-runs `meetings.minutes`: renders the transcript + participants into the active minutes
   prompt, calls the configured LLM once (structured JSON), writes one `minutes` row (version 1,
   `created_by="llm"`) + `action_items` rows, sets the meeting `ready`;
2. exposes minutes over the API: read latest + version history, PUT creates a new user version
   (original kept), toggle an action item done;
3. ports the prompt registry (tables, resolver with TTL cache + hardcoded fallback, seed) and
   ships a platform-admin editor UI (list prompts, version history, create version, publish).

Not in S4: minutes UI surface (S5), notify-on-ready (M16), retention (M15), per-tenant prompt
forks (R5 trigger), anthropic/openai platform defaults (config-selectable, adapters exist, but
only gemini is exercised by the gate).

## 2. Measured facts (survey 2026-09-01, worktree meetings-s2)

- `minutes` + `action_items` tables and models EXIST (`modules/meetings/models.py:281,310`;
  DDL in `0001_meetings_init.py:127,175`). `Minutes`: `meeting_id, version, sections_json,
  created_by (default "llm"), prompt_version_id, llm_provider, llm_model`; unique
  `(meeting_id, version)`. **S4 needs no meetings-module DDL.**
- `tenant_settings` EXISTS with `minutes_language` (default "en") and `llm_connection_id`
  (`models.py:351`), service `services/settings.py`, API already exposes both.
- LLM adapters EXIST: `app/integrations/llm_base.py` (raw httpx by design, no vendor SDKs,
  `LLMError` normalization, 120s timeout) + `gemini_provider.py` / `anthropic_provider.py` /
  `openai_provider.py`. S4 wires them, it does not build them.
- `connections.type == "llm"` is legal and exempt from one-per-type (`connection.py:35`);
  credentials via `app/secrets.py` Fernet; the google_dwd read pattern (`jobs.py:62-105`)
  including InvalidToken -> connection ERROR + job FAILED is the shape to copy.
- Job registry: add `MINUTES = "meetings.minutes"` const, `JobHandlerDef`, `register_job_handler`
  in `modules/meetings/jobs.py` (defs at :515, registered at import). Enqueue slot: end of
  `run_transcribe` success path (mirror `bot_runner._enqueue_transcribe`, :673-682).
  **Celery workers import this module at worker boot - restart workers on deploy or the new job
  type stays Pending silently.**
- `integration_activity` already has `SOURCE_MEETINGS`; write via `ActivityLogService.record`
  (failure-isolated), example `calendar_sync.py:433-448`.
- Sorento registry to port: `app/models/ai_prompt.py` (two tables), resolver
  `app/services/ai_prompt_registry.py` (`get_prompt` TTL-cached + hardcoded fallback,
  `bust_cache`, `validate_template`), CRUD `app/services/ai_prompt_service.py`
  (LABELS production/staging, `save_version`, `set_label`), routes in
  `app/api/v1/system/ai_assistant.py:289-390`, FE `system-management/ai-assistant/prompts/`
  (`PromptsList`, `PromptDetail`, `DiffView`, `PublishDialog`, `VarChips`).
- Shared-service FE: Next.js App Router, page pattern = `app/(protected)/settings/meetings/`
  (thin page + view component + colocated test, `RequirePermission`); platform admin =
  `session.user.isPlatformTenant && can(...)`, menu items `platformOnly: true` filtered by
  `lib/menu-filter.ts`.

## 3. Design (simplest thing that works)

### 3.1 `meetings.minutes` job (`modules/meetings/jobs.py` + new `services/minutes.py`)

1. Load meeting (guard: has a transcript; idempotent - if minutes exist for the meeting, this run
   appends the next version, it never rewrites one).
2. Resolve LLM: `tenant_settings.llm_connection_id` set -> that connection (provider from
   `connection.provider`, creds decrypted; InvalidToken/-inactive handled like google_dwd) ->
   else platform env default (`meetings_llm_provider`/`_model`/`_api_key`). Neither -> job FAILED
   with a clear error, meeting stays `transcribed`.
3. Render prompt: registry `get_prompt("meetings_minutes", "production")` (hardcoded fallback
   keeps the job alive with an empty registry). Variables: meeting title/date, participants,
   `minutes_language`, transcript as `[start..end] Speaker (lang): text` lines.
4. One structured LLM call through the existing adapter. Output contract = JSON with exactly the
   M14 sections: `summary` (str), `decisions` (list[str]), `action_items`
   (list[{text, owner_email|null, due_on|null}]), `open_questions` (list[str]),
   `topic_notes` (list[{topic, notes}]). Non-JSON or shape-invalid response: ONE corrective
   retry (append the validation error), then FAILED.
5. Write `minutes` row (next version, `created_by="llm"`, `prompt_version_id`, `llm_provider`,
   `llm_model`) + `action_items` rows (owner_email stored raw; best-effort case-insensitive match
   against participant emails is display-time, not stored). Set meeting `ready`. Commit.
6. `ActivityLogService.record` per LLM call (operation `minutes_generate`, latency, status,
   request/response summaries truncated) - success and error paths both.

### 3.2 Minutes API (`modules/meetings/routers/minutes.py`)

- `GET /meetings/{id}/minutes` - latest version (sections + action items + version list header).
- `GET /meetings/{id}/minutes/versions/{v}` - a specific version.
- `PUT /meetings/{id}/minutes` - body = sections_json; creates the NEXT version with
  `created_by=<user_id>`, same action-item extraction from the submitted sections. Original kept.
- `POST /action-items/{id}/toggle` - sets/clears `done_at`.
- `POST /meetings/{id}/minutes/regenerate` - enqueues `meetings.minutes` (R5a); 409 while one
  is already pending/running for the meeting.
- Permission slugs follow the module's existing pattern (`meetings.view` read,
  `meetings.manage` write); camelCase responses; every field asserted in tests
  (`response_model` drops undeclared fields).

### 3.3 Prompt registry port (core)

- Tables `ai_prompt_versions` + `ai_prompt_labels`, sorento column shape minus the per-agent
  `provider`/`model` label override (meetings model selection lives in R1's resolution, not on
  the label - trigger to add: a second prompt consumer wanting its own model).
- Core alembic migration + seed of `meetings_minutes` v1 with `production` label.
- Resolver port: `get_prompt` (TTL cache), `bust_cache` on publish, `validate_template`,
  hardcoded fallback spec for `meetings_minutes`.
- Routes (platform-gated): list prompts, version history, create version, publish label.
  Labels: `production` + `staging` (ported as-is, costs nothing). No dry-run box, no diff view
  in v1 of the UI - triggers: first prompt regression that a diff would have caught.

### 3.4 Prompt editor UI (shared-service FE, platform admin only)

- `app/(protected)/settings/ai/prompts/` - list page (name, active version, updated) +
  `[name]/` detail (version history, body viewer, "New version" editor with variable chips,
  Publish with confirm). Mirrors `settings/meetings` page pattern; menu entry `platformOnly`.
- Gate: `RequirePermission` + `isPlatformTenant` (same expression as sidebar-menu.tsx:37).
- **Design (captain 2026-09-01):** the FE build loads the `apple-design` skill
  (sorento checkout `.claude/skills/apple-design`) before writing the editor, and uses
  sorento's prompt admin UI (`system-management/ai-assistant/prompts/` - `PromptsList`,
  `PromptDetail`, `VarChips`, `PublishDialog`) as the layout reference, adapted to the
  shared-service Metronic shell. Motion/feedback per the skill: interruptible transitions,
  reduced-motion respected, publish confirm as a proper dialog.

## 4. Phases

- **Phase 1 (FE mock first):** prompt editor pages against a mocked service; vitest colocated.
  Coder brief includes the apple-design skill + sorento prompts UI reference (3.4 Design note).
- **Phase 2 (BE, test-first):** registry port -> minutes service + job -> API -> wire enqueue +
  `ready` hop. pytest red/green per slice; FE service wired to real routes.
- **Phase 3:** `/code-review` (opus), gate evidence: minutes for 10 real meetings (Sep 3/4 gate
  recordings + re-runs of existing transcribed meetings), `minutes_language` honored (set a
  tenant to zh, verify minutes language vs verbatim transcript).

## 5. Deviations

- 2026-09-01 P1: browser evidence deferred into P2a step 0. The editor is gated on
  `ai_prompts.manage`, a permission that only exists once the backend catalog sync registers
  it; seeding the live pilot DB by hand was correctly refused. Vitest (5/5) stands in for the
  interaction surface until then. Also fixed in passing: the worktree FE `.env.local` pointed
  NEXTAUTH_URL/BASE_URL at a dead :3051 (stale lane port) - now :3001, dev server restarted.
- 2026-09-01 P1: permission slug invented as `ai_prompts.manage` (mirrors `ai_agents.manage`);
  P2a must register exactly this key and grant it to the seeded Platform Admin role.
- 2026-09-01 P2a: `ai_prompts.manage` is registered in `app/permissions/platform_permissions.csv`
  (module `platform`, not `core`) - it rides `PermissionService.sync_platform()`, which
  `seed_permissions`/`seed_platform_admin` run on every `scripts.bootstrap_db` call, which every
  container boot performs via `start.sh`. This is the existing, established mechanism for a
  platform-only key in this repo (confirmed by reading `start.sh` + `app/seed.py`); no bespoke
  grant migration was needed (unlike `ai_perms_s1b_grant_sweep.py`, which exists because CORE
  permissions must reach every independently-provisioned tenant's Admin role - a platform-only key
  only ever needs the one seeded Platform Admin role, which `seed_platform_admin` recomputes as
  the full catalog on every bootstrap run). Verified live on the pilot DB (`bootstrap_db` run +
  backend restart): `permissions` row + `role_permissions` grant to `Platform Admin` only present
  after the run, and `GET /ai-prompts` returns 200 for the platform admin / 403 for a tenant
  Admin / 401 unauthenticated.
- 2026-09-01 P2a: the two-table mechanism was ported as ONE merged module
  (`app/services/ai_prompt_registry.py`, resolver + admin CRUD together) rather than sorento's
  two files (`ai_prompt_registry.py` resolver + `ai_prompt_service.py` CRUD) - shared-service has
  a single consumer (`meetings_minutes`), not sorento's ~20-key `PROMPT_KEYS` registry; a second
  consumer is the trigger to split them back apart. The per-label `provider`/`model` override
  columns were dropped per R1/§3.3 (LLM resolution lives in `tenant_settings`/platform env).
- 2026-09-01 P2a: the worktree FE `.env.local` also had `NEXT_PUBLIC_BACKEND_API_URL` /
  `BACKEND_API_URL` pointing at a dead `:8051` (should be `:8001`, the pilot backend's actual
  port) and `NEXTAUTH_SECRET` not matching the backend's `JWT_SECRET` - both fixed, both required
  a one-time dev-server restart to take effect (`NEXT_PUBLIC_*` is inlined into the browser bundle
  at server-start, not read per-request). Without this fix every AI settings page, not just this
  one, was silently calling the wrong backend / flapping auth.
- 2026-09-02 P3 (S1): `generate_minutes` calls `provider.complete(...)` with no `output_schema` -
  free text + our own JSON parse/retry, not each adapter's native structured-output mode (§3.1
  step 4's "corrective retry, append the validation error" maps onto a textual response, not a
  vendor-specific schema mechanism). Consequence caught in review: none of the three adapters'
  own MAX_TOKENS truncation refusal runs on this path (that check lives inside each adapter's
  `output_schema is not None` branch only), so `generate_minutes` now carries its own
  `_TRUNCATION_FINISH_REASONS` check instead. No max-tokens override seam exists on
  `IntegrationProvider.complete()` today (`DEFAULT_MAX_TOKENS = 4096` is a module constant baked
  into each adapter, not a parameter) - not added here (no adapter edits in a review-fix pass).
  Trigger to move to `output_schema` (or add a max-tokens seam): the first real MAX_TOKENS
  failure on an actual meeting - until then this is theoretical (no meeting has hit it; the
  pilot's `gemini-3.5-flash` batch runs have stayed well under 4096 output tokens).
- 2026-09-02 P3 (S8): `prompts-list-view.tsx` stayed a hand-rolled hairline list rather than
  moving to the Resource shell / a `ClampedText` swap the review offered as an alternative -
  the file's own comment already states why (a handful of platform-seeded prompt rows, not a
  growing tenant collection), so `title=` on the two `truncate` spans was the matching-scope fix.
  Trigger to migrate to a real list shell: the registry gains tenant-facing rows or pagination -
  neither is true today (R5's per-tenant-fork trigger hasn't fired either).
