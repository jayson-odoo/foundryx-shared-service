# Sprint 3 · Plan 09 — Import Engine (generic bulk import for every Resource list)

**Branch:** `sprint-3/09-import-engine`
**Advances:** F8 (roadmap `sprint-3/00`; grill record `F4-foundations-grill-decisions.md` §1). Second F4 prerequisite (after F10 Terminology). The **6th cross-cutting core engine** — same shape as the form/status/rule/template/workflow engines. **Consumed by** participant bulk-registration (F4 slice 3) and every opt-in Resource list thereafter.
**Spawns:** BL-1xx inline cell-edit on the results page · BL-1xx full undo (before-image capture + revert) · BL-1xx custom-field import columns (needs a custom-field/EAV engine) · BL-1xx Redis-backed import progress stream (poll → push).
**Depends on:** Resource shell list toolbar + `ResourceListConfig` (sprint-1/02), `exportColumns`/`exporter` (the symmetric sibling), `view_preferences` (per-user-per-view persistence), `download_jobs` + Celery (the job-table + async precedent, sprint-3/04), `app/uploads.py detect_*` capped-read sniff (sprint-2/04/06), F3 `ActivityTriggers` universal-drawer (the Imports drawer pattern), the code-side registry pattern (StatusEntity/TriggerDef/ImporterDef), `workflow_engine/entities.py attr_for` + writable whitelist (the importable-column source), Terminology (F10 — history-list title), `import_settings` follows the `workflow_settings` per-tenant-row precedent.

---

## Context

There is an **Export** path on every Resource list but no **Import**. Bulk data entry (50 participants, a price list, a contact dump) has no home, and F4's "ala-carte + bulk register" requirement (BRD §3.2 Excel upload) needs it. This is the generic engine: a 4th toolbar button (**Filters · Export · Columns · Import**) on any *opt-in* list, backed by a per-entity declarative config — so a new entity gets bulk import for free by declaring an `ImporterDef`, exactly as it gets workflow-triggerability by registering a `WorkflowEntity` today.

It is **core** (horizontal — every vertical imports) and **server-authoritative** (the client preview is convenience; the server is the boundary — same discipline as the form engine). The whole flow is a **two-phase, job-backed, Celery-decoupled** pipeline with a **persistent history** and an **Odoo-style column-mapping step**.

**Net demo at end of plan 09:** on `/users` (the first opt-in target), click **Import** → modal: download an **xlsx template** (with enum dropdowns) configured to my chosen optional columns, pick mode **Create or update**, drag the filled file in → routed to a **mapping page** (file headers auto-mapped to system columns) → **Validate** → a results page shows "320 valid / 5 invalid" with the 5 bad rows + offending cells + an annotated-error-file download → fix + reupload (new job) → **Commit** imports the valid rows (skips/reports invalid); the **Imports drawer** (top-right, beside notifications) shows the job's live status; `/imports` lists the full history.

---

## Locked design decisions (from grill record §1)

1. **D1 — Core engine + per-entity `ImporterDef` registry, opt-in.** `app/import_engine/` (mirrors `form_engine/`); a **separate registry** of `ImporterDef` keyed by `entity_type` (house parallel-registry style — sibling of WorkflowEntity/StatusEntity/FactSource). Frontend `ResourceListConfig.importer` — the Import button renders only when present + the user holds the entity write perm. **Declared per module** (a module ships its importer config in its own code, like its `permissions.csv`; core entities in core). Many lists must NOT be importable (Email log, Audit log, Workflow runs, Tenants) — opt-in, never opt-out.

2. **D2 — Importable columns = the server-writable whitelist only.** Reuse the `entity.update` writable discipline (`workflow_engine/entities.py attr_for` + the writable frozenset). The template can never offer a column the server will reject. `ImporterDef` declares a **column catalog** = a subset of (or identical to) that whitelist.

3. **D3 — Configurable template = pick-from-catalog.** Catalog columns are tagged **required** or **optional**. The download dialog toggles which **optional** columns to include (required always in) — like the Columns visibility chooser. **No invented columns** (a column the server can't map = guaranteed reject; truly-custom fields wait for a custom-field engine). The selection is **persisted per-user-per-view** via `view_preferences`. Template = **xlsx** with a styled header row + **data-validation dropdowns** for enum / small reference sets; CSV offered secondarily.

4. **D4 — Reupload mapping (Odoo-style step).** Wizard: **Upload (modal) → Map → Review/Test → Commit**. Map = left: detected file headers; right: `SearchSelect` of catalog columns (+ "Don't import"). **Auto-mapped by normalized header string** (a clean template round-trip = 100% pre-selected); the user overrides freely. Mapping **persisted on the job**. Multi-sheet workbook → a **sheet picker** at Map (default = first sheet). **Header detection = positional: skip leading fully-empty rows, the first row with content = headers, data follows** (NO bold/color/`*` sniffing — a user file won't carry our styling). Unmapped semantics:
   - file-col → nothing ("Don't import"/no target) = **warning**, ignored.
   - optional system-col ← nothing = **warning**, proceed (field empty on create / untouched on update).
   - required system-col ← nothing = **proceed + per-row error** (every row fails that field; *not* a hard block — user's chosen model).
   - **Map collisions DEGRADE, never block:** two file-cols → one system-col = target left **blank + warning** (ambiguous, engine won't guess; required-target then hits the per-row error path); **duplicate file headers** = **auto-suffix** ("Email", "Email (2)") so each maps independently + warning.

5. **D5 — Three explicit modes; `match_on = id` only.** **Create-only (default) · Update-only · Create-or-update (upsert)** — chosen in the modal, never guessed. **Matching is by system `id` only** (no natural-key matching — kills the rename-vs-match ambiguity). Update: `id` required → must exist → update, else row error. Upsert: `id` blank → create; `id` filled+exists → update; `id` filled+not-found → row error (never fabricate at a chosen id). Create-only: a present `id` → row error. **All columns writable on an id-matched update** (incl. natural keys). **Updating existing rows requires Export-first** (Export populates `id`; the D12 round-trip). **Partial update** (only present columns written, absent untouched); **required enforced create-only**. Natural keys stay `unique` (validated against dup, in-file + table) but are **not** match keys. **In-file duplicate ids / unique-violations = error.**

6. **D6 — Declarative `ImportColumn`, derived from the writable whitelist + one escape hatch.** An **`infer_import_columns(model, writable)`** helper seeds column defaults (type from the SQLAlchemy column, required from nullable) — mirroring `rule_engine.infer_facts`; the `ImporterDef` **overrides only the special bits**. Each column: `type` (string/integer/decimal/boolean/date/datetime/enum — coerced; bad parse = cell error w/ expected format), `required`, `unique`, **`resolver`** (FK/reference, **tenant-scoped** name→id; unresolvable = cell error; option-list capped ≤25 else "no match") + optional **`options`** (tenant-scoped callable, like `FactDef.options`, drives the in-xlsx dropdown when bounded), **`multiValue`** (delimited cell, per-item resolve), `validators` (regex/min/max/length — reuse existing helpers), `transform` (trim/normalize). Imperative escape hatch **`ImporterDef.validate_row(row, ctx)`** for cross-column rules. **Drift guard:** a test asserts every `ImportColumn` ⊆ that entity's `WorkflowEntity.writable` when the entity is workflow-registered (the import + `entity.update` whitelists can't diverge). Reuse `attr_for` for the camel↔snake boundary. Coercion specifics: dates = Excel typed-date cell used directly / strict ISO 8601 for strings (ambiguous DD-MM rejected, column may declare a format); **naive datetimes interpreted in the importing user's tz → UTC** (offset respected if present; the job records the assumed tz); decimals honor `decimals` (Decimal-exponent check); booleans `{true,false,yes,no,y,n,1,0}` case-insensitive, empty=null; enum trim+case-insensitive→canonical; empty-after-trim = null/absent.

7. **D7 — Two-phase, job-backed, server-authoritative; all-or-nothing commit; set-based queries.** **Validate (dry-run, zero writes / Test) → Commit.** Validate IS a backend round-trip (the Test button); the client does **only trivial pre-flight** (empty file, format/size, headers present) — **no client validation mirror** (no cell-by-cell typing in the browser → a mirror only risks drift). **`import_jobs` table** = source of truth (mirrors `download_jobs`). **Celery** (decoupled; eager-inline in dev via `celery_task_always_eager`) — uniform path even for small files. **Commit = ONE transaction over the entire valid set: all succeed or NOTHING is imported** (a system/integrity error *or* a commit-time re-validation failure → rollback everything → job `failed`, clean retry; NO per-row savepoint skipping during commit). `abort_on_invalid` is resolved **at validate** (ON → any invalid row blocks commit; OFF → commit the valid set only). **Double-commit guard = atomic status claim** (`UPDATE … WHERE status='validated'` → 0 rows = already claimed). **Crash → fail + record partial-nothing** (single txn means nothing landed); created/updated ids recorded on success. **Efficiency = strictly set-based: one batched query per resolver (`… IN (…)` → map), one batched match-existence query, bulk DML (`bulk_insert_mappings` / Postgres `ON CONFLICT DO UPDATE` with `RETURNING`) — NEVER per-row queries.** **Persistent history.**

8. **D8 — Results page + fix-reupload loop.** Dedicated route `/imports/{jobId}` (too much for a modal): summary counts, **failed rows only** with offending cells highlighted + per-cell message, **capped on-page (~1000)** with a "showing first 1000 of M — download the error file for all" banner (never render 50k rows); **downloadable annotated error file** = the **complete** set (original + appended `_error` column). **Reupload = a NEW job** (never mutate the old — audit honesty). **Commit default = import the valid set, report skipped** (Commit reads "Import 320 valid rows (5 skipped)"); opt-in checkbox **"Abort if any row is invalid"** (resolved at validate, per D7). Inline cell-edit = backlog.

9. **D9 — Imports drawer + history list.** A top-right **Imports drawer** (reuse the F3 `ActivityTriggers` universal-drawer pattern, beside notifications) — recent jobs, status, timestamp, polls like Downloads (4s, intelligent stop), click → results page. `/imports` = the full **Resource list** history (filter by entity / status / actor), title via Terminology.

10. **D10 — Multi-format behind one adapter.** Accept **xlsx, xlsm, xls, csv**. A single magic-byte-sniffing `readers.py` → uniform `list[dict]`; format-blind downstream. Libs: **openpyxl** (xlsx+xlsm), **xlrd** (xls only — fragile legacy path), stdlib **csv** + **charset-normalizer**. `.xlsm` macros never execute server-side (cell-read only). Extension is a hint; the declared content-type lies (house rule).

11. **D11 — Caps, per-tenant from day one.** `import_settings` table (tenant_id PK: `max_rows` default 10k, `max_file_mb` default 10) — mirrors `workflow_settings`. Enforced **fail-fast at upload** (capped read + sniff; over → rejected in the modal, no job).

12. **D12 — Permissions + undo + symmetry.** Import gated by the entity's **write perm** (no new per-entity key — bulk import is create/update at scale). **No field-level perms** (none exist in the codebase — the writable catalog IS the boundary). One core key **`imports.read_all`** for the cross-actor history view (else own jobs only). **No auto-undo** (updates destructive) — the job records **created + updated ids** for trace; full undo = backlog. **Export↔import symmetry:** export includes the `id` column so *export → edit → reimport (update)* round-trips.

13. **D13 — "Trigger automations" toggle, default OFF.** Bulk import default-suppresses workflow events (a backfill must not fire 10k welcome mails / status cascades). **Audit is independent** — the `import_jobs` row (entity/mode/actor/created+updated ids/timestamps, in `/imports`) is the audit trail regardless. Toggle **ON** → the service explicitly emits per-row `entity.created` (inserts) / `entity.updated`-with-changes (upsert-updates) after commit, via the failure-isolated after-commit drain (fans to workflow matching + the BL-084 audit subscriber). The safer domain path = import → bulk-select → "Send invitation" (an EMS/Cluster-D action, not F8). Batched/throttled dispatch for huge opt-in imports = backlog.

14. **D14 — Security.** **Formula-injection sanitization on every generated cell** (annotated error file + template) — values leading with `= + - @`/tab/CR get prefixed `'`/stripped (reuse/extend `lib/csv.ts` + a server equivalent); **the existing Export path has the same gap → BL it.** **Parser hardening:** openpyxl **`read_only=True, data_only=True`** (streams rows, reads values not formulas, stops at `max_rows+1`); the **file-size cap bounds the `.xls`/xlrd whole-file-in-RAM path**; store literal cell values as strings, **never evaluate**; magic-byte sniff is the format gate. **Antivirus scan on upload = BL** (consistent with documents BL-099).

15. **D15 — File storage via `storage_for_tenant`.** Uploaded source + annotated error file ride the standard tenant→platform→local-disk resolution (sprint-2/06) — **storage provider if configured, else server disk**. Keys `imports/{job_id}/source.<ext>` + `imports/{job_id}/errors.xlsx` (carry their writing connection per `conn:<id>:<raw>`). **Quarantine order:** create the job row first (need `job_id` for the key), **sniff before store**.

16. **D16 — Retention.** Keep the `import_jobs` **row forever** (small audit/history). **Prune the heavy files** (source + error) after a **global 30-day** window via the scheduler beat (same pattern as workflow-run / email retention), mark purged; the row keeps counts + `errors_json` summary + ids. Per-tenant retention = later (as `workflow_settings` retention evolved).

17. **D17 — Embedded-list import context (added for F4 participant bulk-reg).** An importer may run **scoped to a parent record** — launched from an embedded list (e.g. a Project's participants tab). The import carries an optional **`context` (parent FK, e.g. `{project_id}`)** stamped on every row + used for scoping. `import_jobs` gains a `context_json` column; the launching list passes it; the `ImporterDef` declares which context keys it accepts.

18. **D18 — Find-or-create resolver mode (added for F4 participant bulk-reg).** A column `resolver` may be **find-only** (default; unresolvable = cell error) **or `find_or_create`** — existing match → link; no match → **create the referenced record** from the row's creation fields, in the same all-or-nothing transaction; **never update** an existing referenced record (it may be shared — e.g. a profile across events). Used by the EMS participant importer's `profile`-by-email column for one-step bulk registration.

---

## Data model (core `public`)

```
import_jobs
  id, tenant_id, actor_user_id
  entity_type        str          # the ImporterDef key
  mode               enum(create_only|update_only|upsert)   # default create_only
  abort_on_invalid   bool         # resolved at validate (any invalid → block commit)
  context_json       JSON | null  # embedded-list parent scope, e.g. {project_id} (D17)
  trigger_automations bool        # default FALSE — emit per-row workflow events (D13)
  assumed_tz         str | null   # tz used for naive datetimes (D6 transparency)
  file_storage_key   str | null   # quarantined upload via storage_for_tenant; pruned at 30d
  files_purged       bool         # retention dropped the heavy files, row kept (D16)
  sheet_name         str | null
  mapping_json       JSON         # {fileHeader: columnKey | null}
  status             enum(pending|validating|validated|importing|done|failed)
  total_rows         int
  valid_rows         int
  invalid_rows       int
  error_report_key   str | null   # annotated error file (storage); pruned at 30d
  errors_json        JSON | null  # [{row, column, message}] (capped ~1000; full in the file)
  created_ids      JSON | null  # forensic trace
  updated_ids      JSON | null
  created_at, validated_at, committed_at, finished_at  (UTCDateTime)

import_settings
  tenant_id PK, max_rows int, max_file_mb int, updated_at
```

`ImporterDef` / `ImportColumn` (code, not tables): see D2/D5/D6. **`match_on` is universally `id`** (not declared per entity). `infer_import_columns(model, writable)` seeds defaults; `ImporterDef` overrides resolver/options/validators/multiValue/transform + `validate_row`. Registered via `register_importer(ImporterDef)` at `lazy_once` (core) / module install.

## API (`app/api/v1/imports.py`)

- `GET /imports/config/{entity_type}` — the catalog (columns, required/optional, modes, enum/bounded-FK options) for the modal + template builder. Gated by entity write perm.
- `GET /imports/template/{entity_type}?columns=&format=xlsx|csv` — streams the configured template (xlsx w/ in-cell data-validation dropdowns + styled required headers; sanitized cells).
- `POST /imports` (multipart) — upload file + `{entity_type, mode, abort_on_invalid, trigger_automations}`; caps enforced (fail-fast); creates an `import_jobs` row (`pending`) + stores the sniffed file via `storage_for_tenant`; returns `{jobId}`. Gated entity write perm.
- `PUT /imports/{jobId}/mapping` — `{mapping, sheetName}`; enqueues **validate** (Celery). → `validating`.
- `GET /imports/{jobId}` — job status + summary + errors (results page + drawer poll).
- `GET /imports/{jobId}/errors-file` — annotated error file download.
- `POST /imports/{jobId}/commit` — enqueues **import** (re-validate per row). → `importing`.
- `GET /imports` — paginated history (own jobs; all if `imports.read_all`). Resource list.

Service `ImportService` (+ `ImportRepository`, tenant-scoped) owns: validate, commit, template build, annotated-error build. Celery tasks `import_validate(job_id)` / `import_commit(job_id)`. No raw SQL / no DB in the router (house rule). New perms: `imports.read_all` → `permissions.csv` (tenant Admin).

## Frontend

- `services/import-service.{ts,mock,real}` + `hooks/use-import.ts` + `hooks/use-import-jobs.ts` (drawer feed, poll).
- `components/platform/import-wizard/` — `ImportModal` (download template w/ column toggles, mode, abort toggle, drop-zone) → `import-mapping` page → `import-results` page. Reuse `SearchSelect`, dnd file drop, `ConfirmActionDialog`.
- `providers/import-activity-provider.tsx` + the **Imports drawer** trigger in the protected-layout header `ActivityTriggers` (alongside Uploads/Downloads from F3).
- `ResourceList` toolbar: render the **Import** button when `config.importer` is set and the user holds the entity write perm.
- `/imports` Resource list (history) + `/imports/[jobId]` results route.
- **First opt-in target = Users** (`ImporterDef` for `user`) to prove the engine end-to-end before F4 consumes it.

## Phase A — Frontend-first (mock)
Wizard (modal → mapping → results) + Imports drawer + `/imports` list, all on the mock service; tune loading/validating/error/partial states. Template download stubbed. Responsive at 375/1280 (mapping two-column stacks on mobile).

## Phase B — Backend (swap mock → real)
Migrations (`import_jobs`, `import_settings`). `app/import_engine/` (registry, `readers.py` adapter, `validators`, `service`, Celery tasks). `user` `ImporterDef`. Template builder (openpyxl w/ data-validation). Swap service boundary. Wire `imports.read_all` + `tenant_admin_grant`.

## Phase C — TDD + E2E
**Backend (`tests/test_import_engine.py`):** adapter sniffs each of xlsx/xlsm/xls/csv → uniform rows · header = first non-empty row · per-type coercion + cell errors · naive-datetime→user-tz→UTC · tenant-scoped resolver (set-based, capped option list) · 3 modes, id-only matching (update needs id, create-only rejects id, upsert create/update) · partial update + required-create-only · natural-key still unique · in-file dup = error · map collisions degrade (2→1 blank+warn, dup header suffix) · **commit all-or-nothing** (re-validate failure rolls back everything) · double-commit status-claim guard · **set-based queries / bulk DML** (assert no per-row query explosion) · `trigger_automations` OFF emits nothing / ON emits per-row events · **formula-injection sanitized** in template + error file · openpyxl read-only stops at cap · caps fail-fast · created ids recorded · `imports.read_all` perm gate + tenant isolation · drift guard (import cols ⊆ writable).
**Frontend (vitest):** mapping auto-map by header · column-toggle persistence · results error rendering (capped + banner).
**E2E (`e2e/import-engine.spec.ts`, real clicks, both viewports):** download template → upload w/ one bad row → map → validate → results shows the bad row → fix → reupload → commit → user appears in `/users`; drawer reflects status. Report `09-import-engine-test-report.md`. **Spec isolation:** import into a **dedicated provisioned tenant** (mutates shared list state).

---

## Out of scope / backlog
Inline results cell-edit · full undo (before-image revert) · auto-resume of a crashed import (idempotent) · custom-field columns (needs custom-field/EAV engine) · push (vs poll) progress · async chunked streaming for >10k rows · **batched/throttled workflow dispatch for huge opt-in imports** · **sanitize the existing Export path against formula injection** · **antivirus scan on upload** (cf. documents BL-099) · field-level RBAC · per-tenant import retention.
