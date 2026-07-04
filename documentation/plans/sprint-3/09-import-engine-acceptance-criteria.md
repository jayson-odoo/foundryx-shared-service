# Sprint 3 · Plan 09 — Import Engine · User Acceptance Criteria

**Plan:** `09-import-engine.md` · **Foundation:** F8 (the 6th core engine)
**Gate role:** MERGE green after 08, before 10. Consumed by F4 participant bulk-reg (plan 11).

Format: **Given / When / Then**, traced to a locked decision (Dn) + pillars 🟢📈🧭✅.
A criterion is MET only when its named test is green (and UI verified at 375/1280 where relevant).

---

## 1. Functional SaaS — the import flow works end-to-end 🟢

- **AC-09-01 (demo/D4) Full wizard round-trips.**
  *Given* `/users` with the importer, *when* the user runs Import → download template → fill →
  Upload → Map → Validate → Review → Commit, *then* valid rows land in `/users` and the job shows
  `done`. The four-step wizard (Upload modal → Map → Review/Test → Commit) is the only path.

- **AC-09-02 (D3) Configurable xlsx template with enum dropdowns.**
  *Given* the download dialog, *when* the user toggles optional columns (required always in) and
  downloads xlsx, *then* the file has a styled header row + in-cell data-validation dropdowns for
  enum/bounded reference columns, and the column selection persists per-user-per-view.

- **AC-09-03 (D4) Odoo-style mapping, auto-mapped + overridable.**
  *Given* an uploaded file, *when* the Map step opens, *then* file headers auto-map to catalog
  columns by normalized string (a clean template round-trip = 100% pre-selected), each row has a
  `SearchSelect` (+ "Don't import"), a multi-sheet workbook shows a sheet picker (default first),
  and the mapping is persisted on the job.

- **AC-09-04 (D4) Header detection is positional.**
  *Given* a file with leading empty rows, *when* parsed, *then* the first row with content =
  headers, data follows — no bold/color/`*` sniffing.

- **AC-09-05 (D5) Three explicit modes, `id`-only matching.**
  *Given* a chosen mode, *then*: Create-only rejects a present `id` (row error); Update-only
  requires `id` that must exist; Upsert: blank `id` → create, filled+exists → update,
  filled+not-found → row error. No natural-key matching; partial update (absent cols untouched).

- **AC-09-06 (D8) Results page + fix-reupload loop.**
  *Given* a validated job with bad rows, *when* the user opens `/imports/{jobId}`, *then* they see
  summary counts, failed rows only with offending cells + per-cell messages (capped ~1000 with a
  "showing first 1000 of M" banner), and can download the complete annotated error file; fixing +
  reuploading creates a NEW job (old never mutated).

- **AC-09-07 (D9) Imports drawer + history list.**
  *Given* a running job, *when* the user opens the top-right Imports drawer, *then* recent jobs show
  live status (poll ~4s, intelligent stop) and click → results page; `/imports` is the full
  Resource-list history (filter by entity/status/actor), title via Terminology.

## 2. Scalable, server-authoritative, safe at volume 📈

- **AC-09-08 (D7) Two-phase, job-backed, server-authoritative.**
  *Given* any file size, *when* imported, *then* the path is Validate (dry-run, zero writes) →
  Commit, both via Celery (eager-inline in dev), `import_jobs` is the source of truth, and the
  client does only trivial pre-flight (no cell-by-cell validation mirror).

- **AC-09-09 (D7) Commit is all-or-nothing.**
  *Given* a validated set, *when* Commit runs and a re-validation/integrity error occurs, *then*
  the entire transaction rolls back (nothing imported), job = `failed`, clean retry — no partial
  landing, no per-row savepoint skipping during commit.

- **AC-09-10 (D7) Set-based queries / bulk DML — no per-row explosion.**
  *Given* an import, *when* validated/committed, *then* resolvers run one batched `IN (…)` query
  each, match-existence is one query, DML is bulk (`bulk_insert_mappings` / `ON CONFLICT DO UPDATE`)
  — a test asserts the query count does not scale per row.

- **AC-09-11 (D7) Double-commit guard.**
  *Given* a job already claimed, *when* Commit fires twice, *then* the atomic status claim
  (`UPDATE … WHERE status='validated'`) makes the second a no-op.

- **AC-09-12 (D11) Per-tenant caps, fail-fast at upload.**
  *Given* `import_settings` (max_rows 10k, max_file_mb 10), *when* an over-cap file is uploaded,
  *then* it is rejected in the modal (capped read + sniff), no job created.

- **AC-09-13 (D10) Multi-format behind one adapter.**
  *Given* xlsx/xlsm/xls/csv, *when* uploaded, *then* a magic-byte-sniffing reader yields uniform
  `list[dict]`; `.xlsm` macros never execute (cell-read only); extension/content-type are hints only.

- **AC-09-14 (D16) Retention.** *Given* a job older than 30 days, *when* the beat prune runs,
  *then* heavy files (source + error) are purged + `files_purged=true`, the row + counts +
  `errors_json` + created/updated ids are kept forever.

- **AC-09-15 (D1/D2/D6) Opt-in per-entity registry, whitelist-bounded.**
  *Given* a new entity, *when* it registers an `ImporterDef`, *then* the Import button appears only
  for it + only to users with the entity write perm; importable columns ⊆ the server-writable
  whitelist (drift-guard test asserts `ImportColumn` ⊆ `WorkflowEntity.writable`). Email/Audit/Run/
  Tenant lists are NOT importable.

## 3. Guided UX 🧭

- **AC-09-16 (D4) Mapping issues degrade with a warning, never silently.**
  *Given* unmapped/colliding columns, *then*: file-col→nothing = warning+ignored; optional
  system-col←nothing = warning+proceed; required system-col←nothing = proceed + per-row error;
  2 file-cols→1 system-col = blank+warning; duplicate file headers = auto-suffix "Email (2)"+warning.
  Every degradation is surfaced to the user.

- **AC-09-17 (D8) Safe commit default + explicit opt-in.**
  *Given* invalid rows present, *then* Commit default reads "Import N valid rows (M skipped)";
  an opt-in "Abort if any row is invalid" checkbox (resolved at validate) blocks commit when on.

- **AC-09-18 (D13) Trigger-automations toggle, default OFF.**
  *Given* a bulk import, *then* workflow events are suppressed by default (no 10k welcome mails);
  toggling ON emits per-row `entity.created`/`entity.updated` after commit via the failure-isolated
  drain. The `import_jobs` row is the audit trail regardless of the toggle.

- **AC-09-19 (house mandate) Responsive.** Modal + mapping (two-column → stacks) + results render
  cleanly at 375px and 1280px.

## 4. Validated quality ✅

- **AC-09-20 (D14) Security: formula-injection sanitized.**
  *Given* generated cells (template + annotated error file), *when* a value leads with `= + - @`/
  tab/CR, *then* it is prefixed `'`/stripped (both client `lib/csv.ts` + server equivalent).

- **AC-09-21 (D14/D15) Parser hardening + quarantine.**
  *Given* an upload, *then* openpyxl runs `read_only=True, data_only=True` and stops at `max_rows+1`,
  cell values are stored as strings (never evaluated), the file-size cap bounds the xls/xlrd path,
  and the job row is created first → sniff → store via `storage_for_tenant` (`imports/{job_id}/…`).

- **AC-09-22 (D6) Type coercion + tenant-scoped resolvers correct.**
  *Given* typed columns, *then* coercion matches spec (ISO-8601 strict dates, naive datetimes →
  importing user's tz → UTC with `assumed_tz` recorded, Decimal-exponent decimals, boolean set,
  enum trim+case-insensitive); resolvers are tenant-scoped, set-based, option-list capped ≤25.

- **AC-09-23 (D17/D18) F4-enabling extensions present.**
  *Given* an embedded-list import, *then* a parent `context_json` (e.g. `{project_id}`) stamps every
  row; a `find_or_create` resolver links an existing match or creates the referenced record in the
  same all-or-nothing txn, **never updating** an existing shared record.

- **AC-09-24 (D12) Permissions + symmetry.**
  *Given* import, *then* it is gated by the entity write perm (no new per-entity key);
  `imports.read_all` gates the cross-actor history (else own jobs only); export includes `id` so
  export → edit → reimport(update) round-trips.

- **AC-09-25 Backend tests green** (`tests/test_import_engine.py`) covering every D-clause above
  incl. all-or-nothing rollback, set-based assertion, sanitization, caps, drift guard, isolation.

- **AC-09-26 Frontend tests green** (vitest): mapping auto-map · column-toggle persistence ·
  results error rendering (capped + banner).

- **AC-09-27 E2E green** (`e2e/import-engine.spec.ts`, real clicks, both viewports, **dedicated
  provisioned tenant**): template → bad-row upload → map → validate → results → fix → reupload →
  commit → user appears; drawer reflects status. Report `09-import-engine-test-report.md`.

- **AC-09-28 House rules:** no DB/raw SQL in router · Service-Repository · tenant-scoped queries ·
  reviewer approved before merge.

---

## Definition of Done (plan 09)
All AC-09-* MET · suites green · E2E report filed · reviewer approved · merged to `main`.
**Continuity gate:** plan 11's participant bulk-reg depends on D17 (context) + D18 (find-or-create)
— AC-09-23 must be green before EMS slice 3 is built. Start plan 10 only after 09 is merged.
