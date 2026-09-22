# 12 - AutoCount mapping: master formula variables + Reset to preset - Test Execution Report

Keyed to `12-autocount-mapping-preset-reset-acceptance-criteria.md` (AC-12-01..07, 10..15,
20..27, 30..35 - **28 ids**). Plan: `12-autocount-mapping-preset-reset.md`. Format:
`documentation/development_process/AI_Agent_Orchestration_Guide.md` section 6.

## Environment

- Worktree `.claude/worktrees/s50`, branch `sprint-5/12-mapping-master-formula-variables`,
  HEAD **`e1857aac`** at the time every verdict below was taken.
- Lane: backend `:8012` (uvicorn `app.main:app`, **no** `--reload`, ad hoc lane env, port
  ownership confirmed by `lsof` = this worktree), frontend `:3012` (fresh
  `rm -rf .next && npm run build`, `npx next start -p 3012`, `lsof` cwd = this worktree),
  DB `foundryx_service_s50` (native Postgres), Redis db 12, `CELERY_TASK_ALWAYS_EAGER=true`.
- Auth is real (`demo@example.com` / `demo1234`, tenant `default`). No mock mode; the frontend
  service trio is bound to `realAutocountService` and the S1 `withPhase1MappingResetMock`
  overlay is deleted, not merely unbound.
- Browser evidence: `agent-browser` CLI only, `--session s50t`, headless, widths 1280x900 and
  375x812. **No Playwright** anywhere.
- Evidence dirs under `documentation/plans/sprint-5/12-evidence/`: `s1-mock/` (S1, mock phase),
  `s2-real/` (S2, real backend, recorded at `aa7f3080`), `s3-final/` (AC-12-24 re-run at
  `e1857aac`), `s3-documents/` (AC-12-27, this pass).

## Summary

Of 28 AC ids: **25 PASS**, **1 FAIL** (AC-12-27), **2 DEFERRED** (AC-12-33 is PASS with one
carve-out noted inside AC-12-27's scope; the genuine deferrals are AC-12-35 and the
`[E2E]` half of AC-12-27's line-scope UI proof - see the rows). No id is recorded green on
"the test suite covers it" alone where the AC says `[E2E]`.

**The one FAIL, AC-12-27:** "Reset to preset" is not reachable by clicking on ANY document
entity. The backend half is correct (`hasPreset: true`, header-only diff, 14 line rows
byte-identical across a real apply), and the Vitest fixture pins the component. But
`company-detail-view.tsx` routes a `sql_db` task's "Configure mapping" to the TASK editor's
Mapping tab, which embeds `MappingEditorBody` without the `ActionMenu` item or the dialog; the
standalone mapping page that carries them has exactly one link in the whole frontend and
`sql_db` never takes it. Since `HTTP_PRESETS` carries no document entity, "document" always
means `sql_db`, so the gap is total for this class. Back to the coder; details and the exact
code in `12-evidence/s3-documents/README.md`.

## Suites

Run by this pass, at HEAD `e1857aac`, on the lane's own interpreters.

| Suite | Command | Result |
|---|---|---|
| Backend, this plan | `.venv/bin/python -m pytest -q tests/test_s12_*.py` | **23 passed**, 0 failed (3 deprecation warnings, all pre-existing Starlette/httpx notices) |
| Backend, targeted sweep | `.venv/bin/python -m pytest -q -k "autocount or mapping or preset or s08 or s10 or s11 or s12"` | **2203 passed**, 0 failed, 3265 deselected, 128 s |
| Frontend, autocount | `npx vitest run autocount` | **907 passed** in 73 files, 0 failed |
| Frontend, the 7 changed test files (+1) | `npx vitest run <the 8 lane test files>` | **84 passed** in 8 files, 0 failed |
| Lint | `npx eslint` on all 19 changed frontend `.ts`/`.tsx` files (`git diff --name-only 60b21d75...HEAD`) | clean, exit 0 |
| Build | `rm -rf .next && npm run build` (before the evidence runs) | clean; `:3012` served by this worktree |

Not re-run by this pass: the FULL backend suite and the FULL `npx vitest run` (CI gate).

## Review round 1

**Verdict: approved with findings**, all of which were resolved before this report:

| Finding | Resolution | Commit |
|---|---|---|
| B1 - the product preset seeds `is_discontinued`, which is never delivered to Sorento | Owner ruling R4: the row is dropped from `PRODUCT_HTTP_PRESET` (AC-12-06). Closes BL-SS-260 | docs `34abbc24`, code `82c8ebde` |
| B2 - seed wrote `PresetField.required`, Save wrote the catalog flag, so the diff reported phantom `changed` rows forever | Ruling R5: `plan_rows` derives `is_required` from the mapping catalog (AC-12-07); kill test documented in `test_seed_then_save_then_dry_run_reports_no_change` | docs `34abbc24`, code `82c8ebde` |
| B3 - the mapping table never rendered `isEnabled`, and Save silently re-enabled the withheld `uom_code` | Ruling R6: a per-row Enabled `Switch` plus removal of the sprint-5/02 save-time revive (AC-12-25/26) | docs `ab430666`, code `aa7f3080` |
| S1 - the Vitest document fixture did not exercise the document UI path | `documentMappingView` carries `hasPreset: true`; a `sales_order` gating test added | `e1857aac` |
| S2 - `resolve_preset_rows` did not state why `autocount_read` `DEFAULT_MAPPINGS` is not a preset | Resolver docstring now states the safe direction explicitly | `e1857aac` |
| S3 - only one disabled reason was pinned by a test | Both causes pinned, including "withholding wins when the column is ALSO missing" | `e1857aac` |
| nit - the apply refetched the mapping | Hydration moved to `applyView` (the POST's own returned view); re-verified live in this pass, network log shows no second GET | `e1857aac` |

Earlier UAC amendment from the S2 tester (a single disabled-reason string) is folded into
AC-12-12/15 and shipped.

## Definition of Done gate

1. **Mock swapped to real and verified with real data** - PASS. `autocountService = realAutocountService`;
   the S1 overlay is deleted; every shot in `s2-real/`, `s3-final/` and `s3-documents/` is a
   real backend round trip against `foundryx_service_s50`.
2. **Backfill / schema** - N/A, stated: **this plan ships no schema change and no migration**
   (`git diff 60b21d75...HEAD` touches no `alembic/` path; pinned by
   `test_ac_12_32_no_new_autocount_migration_added`). `hasPreset` is derived at read time.
3. **No hardcoded editable-key lookup** - PASS. The resolver keys off `source_impl` and
   `entity_type`, both system constants; no tenant-editable name is looked up.
4. **Permission grant sweep** - N/A, stated: **no new permission**. The route reuses
   `autocount.companies.manage`; pinned by `test_ac_12_30_permissions_parity_no_new_key_added`.
5. **Real clicks at 375 AND 1280 on a fresh build on correctly-owned lane ports** - PASS for the
   master/HTTP path (`s3-final/`), **FAIL for the document path** (`s3-documents/`) - see
   AC-12-27.

## Test execution

| User Story | Scenario | Precondition | Steps | Expected Result | Actual Result | QA Remarks |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **AC-12-01** `[FE]` | The formula builder offers previewed source columns on a master entity | Product HTTP task with a non-empty `acFields` | 1. Mapping tab 2. Open the Description row's formula builder 3. Read the variable panel 4. Type the Desc2 join | ONE group "Source columns" listing every `acFields` entry; the client validator accepts the join; document groups byte-identical | Group present with `ItemCode`, `Description`, `Desc2`, ... and the lookup alias `BaseUOMPrice`; formula reads "Valid formula" | **PASS**. Live: `s2-real/10-1280-builder-source-columns.png`, `11-375-...`. Unit: `mapping-editor-body.test.tsx` "AC-12-01: a master row with a non-empty acFields gets ONE Source columns group" + the validator case + the document byte-identity case |
| **AC-12-02** `[FE]` | No previewed columns, no group, no hint copy | Master entity with empty `acFields` | 1. Open the builder | No "Source columns" group, no instructional text, single-`value` model, "Unknown name" unchanged | As expected | **PASS**. `mapping-editor-body.test.tsx` "AC-12-02: ... falls back to the single-value model, no group, no hint copy". Not separately live-reproduced (no lane task with an empty `acFields`); unit-pinned, stated plainly |
| **AC-12-03** `[BE]` | Save gate accepts a master formula naming a previewed column or lookup alias | Product HTTP task, `result_columns` incl. `Description`/`Desc2`, `uom` lookup exposing `BaseUOMPrice` | 1. PUT the mapping with the join and the clamp 2. PUT one naming `Desc3` | 200; then 422 naming the row and the unknown name | As expected | **PASS**. `test_s12_master_formula_facts.py::test_ac_12_03_put_accepts_a_master_formula_naming_previewed_columns_and_a_lookup_alias` and `..._422s_naming_the_row_and_the_unknown_column` |
| **AC-12-04** `[BE]` | Simulate evaluates a master multi-column formula against the raw row | Same task, a row with `Desc2` and one without | 1. `simulate_mapping` 2. The route's happy path | Raw join for a row with `Desc2`, `Description` alone for a blank one, inner double space preserved | As expected | **PASS**. `test_ac_12_04_simulate_service_returns_the_raw_desc2_join` + `..._simulate_route_happy_path_...`. Live corroboration `s2-real/12-1280-simulate-desc2-join.png` |
| **AC-12-05** `[FE]` | The client-side sample Test hides when variables are present | Master entity with / without `acFields` | 1. Open the builder in both states | Sample Test absent with variables, present without | As expected | **PASS**. `mapping-editor-body.test.tsx` "AC-12-05: the sample Test tab is hidden once Source columns are offered, shown otherwise"; live in `s2-real/10-1280-builder-source-columns.png` (no Testing tab) |
| **AC-12-06** `[BE]` | The product preset no longer seeds `is_discontinued` (R4) | Empty product mapping | 1. First clean save 2. Count rows 3. PUT the same rows back | 8 rows, no `("Discontinued","is_discontinued")`, post-reset PUT 200 | As expected | **PASS**. `test_s10_product_preset_seeding.py::test_first_clean_save_seeds_eight_mapping_rows_for_product`. Live: the lane's product mapping is 8 rows after a real reset (`s3-final/README.md` "DB after the run") |
| **AC-12-07** `[BE]` | A seeded row's `is_required` comes from the mapping catalog (R5) | Fresh product seed | 1. Seed 2. Save the same rows 3. Dry run | Dry run reports no change; seed == save == reset | As expected; the kill test (revert to `spec.required`) is documented in the test body | **PASS**. `test_s12_mapping_reset_service.py::test_seed_then_save_then_dry_run_reports_no_change`. Live: `s2-real/08-1280-after-save-only-uom-differs.png` shows `Name`/`Is active` reading Unchanged after a Save |
| **AC-12-10** `[BE]` | One route, one permission; 404 and 422 shapes | - | 1. Call without `autocount.companies.manage` 2. Cross-tenant company id 3. An entity with no registered preset | 403; uniform 404; 422 `{"detail": "No preset is registered for this entity."}` | As expected | **PASS**. `test_s12_mapping_reset_route.py`: `..._route_requires_companies_manage_permission`, `..._cross_tenant_company_404s_both_dry_run_values`, `..._no_preset_registered_422s_with_exact_detail` |
| **AC-12-11** `[BE]` | The preset resolved is the one first-save seeding would create | Empty mapping | 1. Reset 2. Compare row for row with `seed_http_preset_mapping` | Identical rows; one resolver, no second registry | As expected | **PASS**. `..._resolve_preset_rows_returns_the_http_preset_for_a_product_task`, `..._returns_none_for_an_entity_with_no_preset`, `..._reset_on_empty_mapping_equals_seed_http_preset_mapping_rows`. Live idempotence: `s3-final/04-1280-after-save-already-matches.png` |
| **AC-12-12** `[BE]` | Dry run returns the exact diff and writes nothing; both disabled reasons | A mapping with one row of each kind | 1. `dryRun: true` 2. Count `ac_field_mapping` statements | `added`/`changed`/`unchanged`/`removed`, `disabledReason` naming the ACTUAL cause; zero INSERT/UPDATE/DELETE | As expected | **PASS**. `..._dry_run_returns_the_exact_diff_classification`, `..._dry_run_issues_zero_ac_field_mapping_statements_apply_writes_control` (the control proves the absence test can fail). Live: `s3-final/02-1280-reset-dialog-diff.png` shows "Disabled - withheld by the preset" on `Uom code` while `BaseUOM` IS previewed |
| **AC-12-13** `[BE]` | Apply replaces the header rows in one transaction; line rows untouched | Document entity with header + line rows | 1. `dryRun: false` 2. Force a failure after the delete 3. Compare line rows | Fresh `MappingViewResponse`; a mid-way failure leaves the previous rows; line rows before == after | As expected | **PASS**. `..._apply_replaces_header_rows_with_the_preset_shape`, `..._a_forced_failure_after_delete_leaves_the_previous_rows_intact`, `..._line_scope_rows_are_untouched_by_a_document_reset`. Live on a REAL DB-source `sales_order`: 14 line rows, `diff` of `s3-documents/06-line-rows-before.txt` vs `07-line-rows-after.txt` is EMPTY, and the deliberate operator customisation `SubTotal -> unit_price` survives |
| **AC-12-14** `[BE]` | Same side effects as saving the mapping, no more | Task with preview/activation state | 1. Snapshot `ac_entity_config` 2. Reset 3. Compare; also compare deltas vs a PUT | Byte-identical row; identical deltas | As expected | **PASS**. `..._reset_leaves_ac_entity_config_byte_identical`, `..._reset_and_put_produce_identical_ac_entity_config_deltas`. Live corroboration: `s2-real/README.md` "`ac_entity_config` was not written at all" |
| **AC-12-15** `[BE]` | Un-previewed columns land disabled, never dropped (AC-02-16 preserved) | (a) `result_columns` lacking `BaseUOMPrice` (b) `result_columns` NULL | 1. Reset each 2. Read the rows and the dry run | (a) `list_price` disabled, reason "column not returned by the source" (b) every row enabled except the preset's own withhold | As expected, plus the precedence case | **PASS**. `..._unpreviewed_column_lands_disabled_never_dropped`, `..._withholding_wins_the_reason_when_the_column_is_ALSO_missing`, `..._never_previewed_result_columns_null_every_row_enabled_except_the_preset_withhold`. Live: `s1-mock/08-1280-disabled-reason-missing-column.png` |
| **AC-12-20** `[FE]` | Mock first; every dialog state built against the mock; no mock reaches the evidence run | - | 1. Build the dialog against `autocount-service.mock.ts` 2. Swap at the service boundary | Every state tuned on the mock; the real service is bound for evidence | As expected | **PASS**. `s1-mock/` carries 13 shots covering loading, a full diff, disabled + removed, an empty diff, both widths. `services/autocount-service.mock.mapping-reset.test.ts` states the overlay is GONE; `autocountService = realAutocountService` |
| **AC-12-21** `[FE]` | The action lives on the Mapping tab's existing `ActionMenu`, gated by permission AND `hasPreset` | Product HTTP entity | 1. Mapping page 2. Open `Actions` | Exactly one item, `Reset to preset`; hidden without the permission or without a preset; dirty-guard defers to the shell | Menu enumerated live: `["Reset to preset"]` | **PASS for the master path**. Live `s3-final/01-1280-action-menu-reset-to-preset.png`; unit `mapping-editor-view.test.tsx` (5 gating cases incl. `autocount_read` supplier = no preset). **See AC-12-27**: the component is correct but unreachable for documents |
| **AC-12-22** `[FE]` | The preview dialog shows exactly what will change | Product mapping bent to the prod baseline | 1. Open the dialog 2. Read every row 3. Repeat at 375 | Preset label, `StatusBadge` per change, source column, transform/formula as a `ClampedText` chip, honest disabled line, Removed section, primary "Reset mapping" disabled while loading and on an empty diff | Exactly: `Code` unchanged, `Name` changed, `Description` changed (join chip), `Uom code` changed + "Disabled - withheld by the preset", `List price` changed; and "This mapping already matches the preset." with the primary disabled on the empty diff | **PASS**. `s3-final/02-1280-reset-dialog-diff.png`, `04-1280-after-save-already-matches.png`, `06-375-reset-dialog-diff.png`; `mapping-reset-dialog.test.tsx` (6 cases incl. the loading state and the 422) |
| **AC-12-23** `[FE]` | Apply, re-render from the RETURNED view, toast, close; failure keeps the dialog open | Same | 1. "Reset mapping" 2. Read the network log 3. Read the table | `dryRun:false`; the table re-renders from the response with no second `GET .../mapping`; toast "Mapping reset to preset."; dialog closes; not a `confirm`, not `deferred` | Network tail: `POST .../reset-preset` (dry run), `POST .../reset-preset` (apply), and **no** `GET .../mapping` afterwards. Toast and re-rendered table captured | **PASS** re-verified on the FINAL build (`applyView`, `e1857aac`). `s3-final/03-1280-after-apply-toast-no-reload.png` + the network log in `s3-final/README.md`; `use-mapping-reset.test.ts` + `mapping-reset-dialog.test.tsx` cover the failure path |
| **AC-12-24** `[E2E]` | The full master-entity flow, real clicks, both widths | Product HTTP entity bent to the prod baseline | Sidebar AutoCount -> Companies -> Mocha s50 -> Entities -> Product `Actions` -> Configure mapping -> `Actions` -> Reset to preset -> Reset mapping -> Save -> Reset to preset again | The listed diff; toast; rows match the preset; the builder's "Source columns" lists `Desc2`; Simulate joins; the second dialog says "already matches" | All observed. Re-run end to end on `e1857aac` | **PASS**. `s3-final/` (6 shots + run log, 1280 and 375) for the reset half on the final build; `s2-real/` (20 shots) for the builder/Simulate/Enabled-switch half at `aa7f3080`, unchanged by `e1857aac` except the hydration path this pass re-verified |
| **AC-12-25** `[FE]` | A disabled row is visible as disabled and enabled deliberately | Post-reset product mapping (`uom_code` disabled) | 1. Read mode 2. Edit mode 3. Toggle | Dimmed row + `StatusBadge` "Disabled" whether or not the column is previewed; a `Switch` per row only in edit mode; toggling changes only `isEnabled`; both badges may show | As expected | **PASS**. Live `s2-real/14..16, 18..20`; final build `s3-final/03-1280-after-apply-toast-no-reload.png` shows the dimmed `BaseUOM` + Disabled badge. Unit `mapping-table.test.tsx` "Enabled column (sprint-5/12, AC-12-25)", 6 cases |
| **AC-12-26** `[FE]` | Save never auto-enables a row | Post-reset mapping | 1. Edit 2. Save mapping 3. Re-open the dialog 4. Read the DB | "This mapping already matches the preset."; `uom_code` still `is_enabled=false` | Exactly: after a real Edit -> Save mapping on the final build the dialog reads "already matches", primary disabled, and the DB row is still `f` | **PASS**. `s3-final/04-1280-after-save-already-matches.png` + the DB dump in `s3-final/README.md`; `use-mapping-draft.test.ts` (4 AC-12-25/26 cases, incl. the updated sprint-5/02 revive test) |
| **AC-12-27** `[E2E]` | Document entities are resettable, header rows only | A `sales_order` task on a `sql_database` company | Sidebar AutoCount -> Companies -> the DB company -> Entities -> Sales order `Actions` -> Configure mapping -> expect `Actions` -> `Reset to preset` | "Reset to preset" is OFFERED; the dialog lists HEADER rows only; apply leaves every line-scope row untouched | Company + task + a product-seeded 11-header / 14-line mapping provisioned through the product's own routes. **The mapping editor an operator reaches offers NO reset at all**: `Configure mapping` sends a `sql_db` task to `/entities/sales_order?tab=mapping` (`task-editor-view.tsx`), which embeds `MappingEditorBody` without the `ActionMenu` item or `MappingResetDialog`; the standalone page that has them is linked only for non-`sql_db`. Controls present at both widths: `Edit`, the five tabs, `Simulate mapping` - nothing else. Every document entity is `sql_db` (no document in `HTTP_PRESETS`), so the gap is total | **FAIL**. Evidence `12-evidence/s3-documents/` (`02`, `03`, `04` + README). The BACKEND half is verified correct on that same live entity: `hasPreset: true`; dry run = 11 rows, all header, no line canonical field, `removed: []` (`05-dry-run-header-only.json`); a real apply leaves the 14 line rows byte-identical incl. an operator customisation (`06`/`07`). Vitest "a document view (sales_order) offers the action" passes because it renders `MappingEditorView` directly - the component is right, the route is not. Back to the coder |
| **AC-12-30** `[BE]` | No new permission | - | 1. Permissions parity test | Route reuses `autocount.companies.manage`; read stays on `...read` | As expected | **PASS**. `test_ac_12_30_permissions_parity_no_new_key_added` |
| **AC-12-31** `[BE]` | Tenant scoping | Company in another tenant | 1. Reset with `dryRun` true and false | Uniform 404 both times | As expected | **PASS**. `test_ac_12_10_31_cross_tenant_company_404s_both_dry_run_values` |
| **AC-12-32** `[BE]` | No migration | - | 1. Grep `alembic/versions` across the lane diff | Nothing new; `hasPreset` derived at read time | `git diff --name-only 60b21d75...HEAD` matches no alembic path | **PASS**. `test_ac_12_32_no_new_autocount_migration_added` |
| **AC-12-33** `[FE]` | Responsive and shell-compliant | Every surface touched | 1. 375 and 1280 on each 2. Measure overflow 3. Check the primitives | Non-clipped and usable at both widths; `Dialog`/`StatusBadge`/`ClampedText`/`lib/toast`; no raw CSS, no bare `<Select>`, no hint copy, no new motion | Measured: `document.documentElement.scrollWidth === innerWidth === 375` on the reset dialog (both the diff and the empty state) and on the document mapping editor; the dialog's own row list scrolls internally (`dialog.scrollWidth <= clientWidth`); the mapping table uses its existing container scroll; `npx eslint` clean on all 19 changed files (the roster guardrails are eslint-enforced) | **PASS**. `s3-final/05-375-...`, `06-375-...`; `s3-documents/04-375-...`; `s2-real/README.md` responsive note |
| **AC-12-34** `[T]` | Green suites | - | 1. Targeted pytest 2. `npx vitest run autocount` + the changed files 3. eslint 4. fresh build | All green | 23 / 2203 / 907 / 84 passed, 0 failed; eslint exit 0; build clean | **PASS** for the targeted gate. The FULL `python -m pytest -q` and FULL `npx vitest run` were NOT re-run by this pass (CI gate) - stated, not claimed |
| **AC-12-35** `[T]` | Production adoption of the `SRT` product task | Production Sorento + AutoCount | The plan's section 7 runbook: rename the lookup alias to `BaseUOMPrice` -> Test -> Reset to preset -> Reset mapping -> Simulate -> Review and Activate -> Run preview -> Sorento compare | 177 `Desc2` items match; the Excel "Desc 2" column reads as AutoCount's `Desc2`; before/after counts appended here | Not executed - production is the owner's to touch, and no lane can stand in for it | **DEFERRED to the owner.** The written runbook exists and is the deliverable this AC gates on (`12-autocount-mapping-preset-reset.md` section 7). Append the Sorento before/after counts to this report after the run. Note from the lane: runbook step 1 is PROD-ONLY - this lane's product task already carries the preset's own `uom` lookup (`Price as BaseUOMPrice`), so `list_price` lands enabled with no rename; the prod `SRT` task predates that seed and exposes it as `ListPrice` |

## Defects found by this pass

1. **AC-12-27 - "Reset to preset" unreachable for every document entity** (FAIL, above). Not a
   backend bug and not a component bug: a routing split in
   `service_frontend/app/(protected)/autocount/companies/components/company-detail-view.tsx`
   (`onConfigureMapping`). The unit suite could not catch it because it renders
   `MappingEditorView` directly; only a real-click run reaches the router. Fix belongs to the
   coder: either render the action on the task editor's Mapping tab, or stop routing `sql_db`
   away from the standalone page.
2. **Provisioning note, not a defect:** a `sql_database` AutoCount company cannot be created
   without a reachable server (`probe_current_database`, AC-01-02). This pass used the SQL
   provider's supported `postgresql` dialect against the lane's own Postgres, which let the
   company, the task and the mapping seed all come from the product's own code paths. Recorded
   in `s3-documents/README.md` so the next run does not re-derive it.

## Backlog rows filed

`documentation/backlogs/backlog.md`, appended this pass after confirming the highest existing id
was **BL-SS-255** (no higher id exists on `main`, whose register stops at BL-SS-044, so no
renumbering was needed): **BL-SS-256..262**, in the register's `ID | Title | Source plan |
Priority | Status` format. **BL-SS-260 is filed as Closed** per ruling R4.

## Residue left in the lane DB (deliberate, timestamped)

Connection `fbf94a72-95d1-4216-a131-e045247914b7` (`E2E SQL s50 20260922-044247`) and company
`7eab8612-86af-439f-a3e3-c404b9f4de9a` (`E2E Docs s50 20260922-044247`) with its `sales_order`
task - they ARE the AC-12-27 evidence. Delete them before a clean reseed of
`foundryx_service_s50`.
