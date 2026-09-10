# 07 - AutoCount SO `Ref` on the Sorento feed + "Re-push all" task action - User Acceptance Criteria

Plan: `07-autocount-so-ref-repush.md`. Lane `sprint-5/07-autocount-so-ref-repush`
(worktree `.claude/worktrees/s36`, off `origin/main` 72a3e125; lane DB `foundryx_service_s36`
cloned from the user's 2026-09-08 dump, backend :8006, frontend :3006).

Consumer: Sorento CRM. Wire shape agreed with the Sorento owner session (`autocount-crm`) on
2026-09-10: sales-order record gains an optional `ref` (string, max 255), sibling of
`internal_note`; AutoCount `SO.Ref` is sent VERBATIM (no cleaning on the ESB side); purchase
orders and shipping orders never carry `ref`. Sorento derives `sales_orders.project_label` from it
(`label_from_ref`, branch `feat/so-project-label`, stacked on PR #809 which strips the RTF that
AutoCount stores in `SO.Note`). Sorento declares `ref` under `extra="forbid"`: sending it before
their deploy rejects the whole record, so **Sorento deploys first** (plan section 2.6).

Live facts the criteria rest on (user's dump, read-only, 2026-09-10): the production `Sorento`
SO task (`AED_SORENTO`) runs the SQL-pack section 1 query (multi-line, NOT the preset text) with
23 result columns and no `Ref`; the `ac_sim` task runs the preset text verbatim; both carry an
enabled `Note -> internal_note` row since 2026-09-05; `ac_row_hash` holds 148,068 rows for the
production task; a reconcile on 2026-09-10 scanned 149,075 and updated 123 (correct: only rows
whose SOURCE hash moved re-push, an unchanged note is not a change); 166,868 of 234,480 staged
SOs carry an RTF `internal_note`.

Tags: `[BE]` backend pytest, `[FE]` frontend vitest, `[E2E]` recorded agent-browser run,
`[T]` tester-owned proof (mutation / live replay / docs).

## Definitions

- **preset text** - `presets._SO_HEADER_QUERY` with `{database}` substituted from the task's
  own company (`ac_company.database_name`), the exact text `list_mapping_presets` hands the
  "Use preset" picker.
- **OLD preset text / NEW preset text** - the SO header query before / after this plan adds
  `h.Ref AS Ref`. The OLD text is pinned as a literal in `backfill.py`, independent of any
  future preset edit (the 0016 / 0018 precedent).
- **tracked rows** - the `ac_row_hash` rows for ONE (tenant, company, entity_type): the
  reconcile diff baseline. Clearing them makes the next reconcile classify every source row as
  an add and push it; Sorento's upsert answers `updated` for a known `source_ref`.
- **in flight** - `SyncJobRepository.first_unfinished(tenant, AUTOCOUNT_SYNC, company, entity)`
  returns a job (the same guard `run_task_now` and the scheduler tick use).

## Group A - preset, canonical model, wire (`[BE]`)

- **AC-07-01 [BE]** `presets._SO_HEADER_QUERY` selects `h.Ref AS Ref` (after `h.Note AS Note`);
  `SO_PRESET.header` carries `PresetField("Ref", "ref", "string")` (not required); the
  `list_mapping_presets("sales_order", db)` payload's `headerQuery` contains `h.Ref AS Ref`.
  `_PO_HEADER_QUERY`, `PO_PRESET`, `SPO_PRESET`, `_SO_LINE_QUERY`, `_SO_FINGERPRINT_QUERY` are
  byte-unchanged (pinned by test).
- **AC-07-02 [BE]** `CanonicalSalesOrder.ref: Optional[str]` (max_length 255, default None);
  `ref` is in `CanonicalSalesOrder.FALLBACK_FIELDS` (contract >= 2 only) AND in
  `OMIT_WHEN_EMPTY_FIELDS`: `sink_payload(contract_version=2)` carries `"ref": "THE MET KL"`
  when set; carries NO `ref` key when `None` or `""`; `sink_payload(contract_version=1)` never
  carries `ref`.
- **AC-07-03 [BE]** `CanonicalPurchaseOrder` and `CanonicalShippingOrder` have no `ref`
  attribute; their `sink_payload` at any contract version never contains a `ref` key (pinned so
  a future copy-paste cannot leak it onto the PO/SPO wire).
- **AC-07-04 [BE]** The mapping catalog's accepted header fields for `sales_order` include `ref`
  (string transform only); for `purchase_order` and `shipping_order` they do not. Saving a
  `sales_order` mapping row `Ref -> ref` through `PUT .../mapping` succeeds; the same row on a
  `purchase_order` task is rejected 422 naming the field.
- **AC-07-05 [BE]** End to end through `MappingEngine.map_document` with the NEW preset rows and a
  header row carrying `Ref = "  THE MET KL "`: the canonical record's `ref == "THE MET KL"`
  (string transform strips), and the Sorento sink payload (contract 2) carries it verbatim
  otherwise (no upper-casing, no agent-stamp filtering: Sorento owns that).
- **AC-07-06 [T]** `documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md` section 1
  query gains `h.Ref AS Ref` and the section 1 mapping table gains `| Ref | ref | string |`;
  section 3 (PO) still says do not map `internal_note` and gains "do not map `ref`". The
  sprint-5/02 Sorento addendum change log gains one dated line for `ref` (SO only, verbatim,
  omitted when empty) and one for "Sorento strips RTF from `internal_note` at its edge (their
  #809); the ESB keeps sending the raw value".

## Group B - backfill for existing tasks (`[BE]`)

- **AC-07-07 [BE]** `backfill.backfill_sales_order_ref(bind, schema=...)` exists, is called from
  module Alembic `0019_autocount_so_ref` AND from `update_tenant`, uses frozen `sa.table`
  snapshots only, returns the number of changes, and returns 0 (no error) against a schema that
  lacks any of the tables/columns it touches (`existing_columns` first). Manifest version bumps.
- **AC-07-08 [BE]** For a `sales_order` `ac_entity_config` whose `source_config.query` is
  byte-identical to the OLD preset text (its own company's `database_name` substituted): the
  query becomes the NEW preset text, `"Ref"` is appended to `result_columns`, and a header
  mapping row `Ref -> ref` (transform `string`, enabled, not required, source-owned, next
  `sort_order`) is created. A config already at the NEW text is skipped silently.
- **AC-07-09 [BE]** For a `sales_order` config whose query is NEITHER the OLD nor the NEW preset
  text (the production `AED_SORENTO` shape): the query and `result_columns` are left byte-
  untouched; a `Ref -> ref` header row is created DISABLED when `"Ref"` is not in
  `result_columns` (the `_seed_rows` posture), enabled when it is; ONE `WARNING` log names the
  config id and says to add `h.Ref AS Ref` in the Query tab and enable the row.
- **AC-07-10 [BE]** Idempotent: a second call makes 0 changes and logs no repeat warning for a
  config already carrying a `ref` row in ANY state (an operator's own row, enabled or disabled,
  is never duplicated or modified). A sibling company's substituted text pasted into another
  company's task is treated as customised (AC-07-09), never swapped.
- **AC-07-11 [BE]** Tenant scoping: the company row is resolved WITH the config's own `tenant_id`
  before its `database_name` is trusted for the byte-identity check; a config whose company is
  missing under that tenant is skipped with a warning, never matched against another tenant's
  company.
- **AC-07-12 [T]** Live replay on the lane DB (`foundryx_service_s36`, cloned from the user's
  dump): after the module migration runs to head, the `Sorento` SO task's query is byte-identical
  to before, its `result_columns` are unchanged, it has a DISABLED `Ref -> ref` row, and the
  migration log shows exactly one warning naming its config id. The PO / SPO tasks are untouched
  (row counts and query hashes equal before/after). A second run touches 0 rows and logs no
  warning. Amended 2026-09-10 after the replay: the lane's `ac_sim` task is a hand-authored
  Postgres-dialect translation of the preset (`LEFT JOIN LATERAL`), never byte-identical to the
  MSSQL preset text, so it takes the same customised branch as `Sorento` (disabled row + one
  warning; BL-SS-196). The auto-swap branch (AC-07-08) is proven by unit test, not by lane data.

## Group C - "Re-push all" backend (`[BE]`)

- **AC-07-13 [BE]** `POST /autocount/companies/{company_id}/entities/{entity_type}/etl-task/repush`
  requires `autocount.companies.manage` (the "configure the task" bucket, same as pause /
  activate / refetch-history; no new permission key). A caller without it gets 403; an
  unauthenticated caller 401. Company and task are resolved under the caller's JWT tenant only:
  another tenant's company id is 404.
- **AC-07-14 [BE]** Happy path on an `active` or `paused` `sql_db` task with no run in flight:
  every tracked row for that (tenant, company, entity_type) is deleted via
  `RowHashRepository.clear_all`; other entities' and other companies' `ac_row_hash` rows are
  untouched (pinned by test with three neighbouring populations); `ac_doc_fingerprint` and
  `ac_watermark` rows are NOT touched; response `200 EtlRepushResponse
  {clearedCount, nextReconcileAt, status}` with `clearedCount` equal to the rows deleted.
- **AC-07-15 [BE]** On an `active` task the service sets `next_reconcile_at = now(utc)` so the
  very next scheduler sweep claims a `reconcile` run (existing claim path, no new mode); the
  incremental schedule is not changed. On a `paused` task hashes are cleared, `next_reconcile_at`
  stays `None`, and the response `nextReconcileAt` is `null`; resuming later re-arms the
  schedule as today and the first reconcile after resume re-pushes everything.
- **AC-07-16 [BE]** Guards, all `EtlStateError` -> 409 with the message on the wire, nothing
  deleted: a run in flight (`running_run_id` in the body, same as `run_task_now`); a `draft`
  task ("Activate the task first - a draft has nothing to re-push."); a task whose `source_impl`
  is not `sql_db` ("Re-push applies to database tasks only.").
- **AC-07-17 [BE]** Atomicity: clear + `next_reconcile_at` land in ONE commit; a failure of that
  commit (simulated by making the session commit raise) leaves every hash row in place (pair with
  a control test proving the same fixture does see a committed delete). Amended 2026-09-10 after
  review: the in-flight guard is re-checked AFTER `clear_all` and BEFORE the commit; a job that
  appeared in between rolls the deletion back and answers 409 (pinned by a test that injects the
  job between the two checks).
- **AC-07-18 [BE]** `record_activity(...)` writes one activity row for the action (kind names the
  re-push; payload carries `clearedCount`, `entityType` and `actorUserId` from
  `get_actor_user_id`, i.e. the real admin under impersonation) IMMEDIATELY AFTER the commit
  (the activity service commits the session it is handed, so it must never sit inside the
  mutation's transaction); a 409 writes no activity row. A failing activity insert never undoes
  the wipe: pinned by a test that makes the activity repository raise and asserts 200 with the
  hashes still cleared. One structured `logger.info` line records tenant, company, entity, actor
  and cleared count on success.
- **AC-07-19 [BE]** The reconcile that follows a re-push classifies every fetched row as an add
  and pushes it; the Sorento sink's `updated` outcome for an existing `source_ref` counts as
  delivered (existing `_OUTCOME_DELIVERED`), the run's `Added` reflects the staged adds, and
  `ac_row_hash` is repopulated to the fetched population. (Extend
  `test_autocount_reconcile_push.py`: clear_all then reconcile stages every row once.)

## Group D - "Re-push all" frontend (`[FE]`, `[E2E]`)

- **AC-07-20 [FE]** Service trio: `autocountService.repushEtlTask(companyId, entityType)` in
  `autocount-service.ts` (JSDoc contract at the top), `.mock.ts` (resolves
  `{clearedCount: 148068, nextReconcileAt: <now+60s>, status: 'active'}`; a mock flag simulates
  the 409 in-flight case), `.real.ts` (POST to AC-07-13). `useEtlTaskLifecycle` gains
  `repush()` under the same one-at-a-time `busy`/`error` pattern as `runNow`.
- **AC-07-21 [FE]** Review & Activate tab (`activate-tab.tsx`): a destructive-styled
  "Re-push all" action, rendered ONLY when the task is `active` or `paused`, its source is a
  database task, and `useCan(AC_COMPANIES_MANAGE)`; hidden otherwise (foolproof-UI: never an
  option that cannot work). Draft tasks never show it.
- **AC-07-22 [FE]** (amended 2026-09-10 after review, PRINCIPLES.md design hard-fail: no new
  destructive confirm dialog outside the four named typed-confirm carve-outs; the T5 ruling on
  this very tab drops confirms on re-sync actions.) The action is a `DeferredActionButton` /
  `useDeferredAction` (the app's D2/D13 grace-window model): clicking arms the action with a
  visible undo window; undo within the window makes NO call; when the window lapses the service
  is called once. No dialog, no typed input. The button copy is "Re-push all"; the success toast
  states that change tracking is cleared and the next reconcile pushes every document of this
  task to Sorento again, and for a paused task that nothing moves until the task is resumed.
- **AC-07-23 [FE]** Success: `lib/toast` success naming the cleared count and, for an active
  task, that the full re-push starts on the next scheduler tick; the Runs tab data refreshes
  (`SWR` / list refetch) so the reconcile appears once claimed. 409 in flight: toast error with
  the server message and a link to the running run (`running_run_id`), dialog closes, nothing
  else changes. Other errors: existing `lifecycle.error` surface.
- **AC-07-24 [FE]** Vitest: renders/hides per AC-07-21 (four permission x status cases), the
  deferred action fires the service exactly once with the right ids when its window lapses and
  never when undone, 409 path renders the message and the Runs link, task reload fires on success
  and not on 409, a loading state disables the trigger while `busy`; hook tests for
  `useEtlTaskLifecycle.repush` (success / 409 with `runningRunId` / other error) and a
  `readRunningRunId` test against the exact backend 409 `detail` shape `{message, runningRunId}`. No `any`, no raw CSS, no bare Select /
  table / sonner imports (eslint guardrails).
- **AC-07-25 [E2E]** Recorded agent-browser run on the lane stack (fresh prod build,
  :3006 / :8006, `--session s36`), real clicks from `/` via the sidebar: Services -> AutoCount ->
  company -> the SO entity task -> Review & Activate -> Re-push all -> typed confirm -> success
  toast; DB proof in the README: `ac_row_hash` count for that (company, entity) is 0 after the
  click and `next_reconcile_at <= now`; the Runs tab shows the claimed reconcile once the
  sweep ticks (or the README states the sweep was not running and shows the DB row instead).
  Screenshots at 375px AND 1280px for the tab with the action, the dialog, and the toast.
  Evidence under `documentation/plans/sprint-5/07-evidence/repush/`. A second run against a
  draft task proves the action is absent.

## Group E - deploy order, operator steps, report (`[T]`)

- **AC-07-26 [T]** Plan section 2.6 and the PR description state the deploy order: Sorento
  (#809 + project-label PR) merged AND deployed first, confirmed by the `autocount-crm` session's
  ping; only then `workflow_dispatch` the FoundryX deploy (bootstrap_db runs 0019). Merging to
  `main` does NOT deploy (deploy is manual), so the PR may merge on review pass.
- **AC-07-27 [T]** The production operator step for the customised `Sorento` SO task is written
  in the plan (section 2.4) and the test report: open the Query tab, add the line
  `h.Ref AS Ref,` under `h.Note AS Note,`, Test, Save (this alone re-hashes every SO with a
  non-empty `Ref` and re-pushes them on the next run), then enable the `Ref -> ref` row on the
  Mapping tab. The full note re-push is the "Re-push all" action, run off-hours, one company
  first, after Sorento #809 is live.
- **AC-07-28 [T]** Test Execution Report `07-autocount-so-ref-repush-test-report.md` keyed to
  every AC id above (PASS / FAIL / DEFERRED), citing the pytest files, the vitest files, the
  migration replay log (AC-07-12) and the agent-browser evidence run (AC-07-25). Deferred items
  are registered in `documentation/backlogs/backlog.md`.
