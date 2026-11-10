# 07 - AutoCount SO `Ref` on the Sorento feed + "Re-push all" task action

UAC: `07-autocount-so-ref-repush-acceptance-criteria.md` (the contract; this file is the design
that fulfils it). Lane `sprint-5/07-autocount-so-ref-repush`, worktree `.claude/worktrees/s36`
off `origin/main` 72a3e125. Lane stack: backend :8006, frontend :3006, DB
`foundryx_service_s36` (cloned from the user's dump, so it holds the real production task
shapes), Redis db 0 shared, `CELERY_TASK_ALWAYS_EAGER=true`.

## 1. Why

1. **Project label.** Sorento wants AutoCount `SO.Ref` on every sales order: sales staff stamp
   the project name into it (`THE MET KL`) alongside agent stamps (`JF- 9/9 3.50`). Sorento's
   `feat/so-project-label` derives `sales_orders.project_label` from a new optional wire field
   `ref` (`label_from_ref` drops the stamps). The ESB sends the raw value; Sorento owns the rule.
2. **Notes looked unmapped, but were not.** `Note -> internal_note` has flowed since 2026-09-05.
   Two things hid it: AutoCount stores `SO.Note` as RTF (166,868 of 234,480 staged SOs carry
   `{\rtf1...}`), which Sorento's #809 now strips at its ingest edge; and reconcile only re-pushes
   rows whose SOURCE hash changed (123 of 149,075 on 2026-09-10 was correct). There is no way for
   an operator to re-push an unchanged population after a mapping or a consumer-side change.
   The user chose (grill 2026-09-10) to build that action now rather than run SQL by hand.
3. Dropped from scope after inspection: an `internal_note` drift exclusion. `sync.compute_diff`
   compares the new canonical against the LAST PUSHED staged copy (both RTF), and
   `SorentoSink.read_back` has no production caller, so nothing drifts.

## 2. Design

### 2.1 Preset + canonical + wire (AC-07-01..06)

- `presets._SO_HEADER_QUERY`: `h.Note AS Note, h.Ref AS Ref,` (one new select item; the OUTER
  APPLY, line query and fingerprint query untouched). `SO_PRESET.header` += `PresetField("Ref",
  "ref", "string")` right after the `Note` row.
- `canonical/documents.py` `CanonicalSalesOrder`: `ref: Optional[str] = Field(None,
  max_length=255)`; add `"ref"` to `FALLBACK_FIELDS` (contract >= 2, the connection's
  `sorento_contract_version` is already 2.x in production) and to `OMIT_WHEN_EMPTY_FIELDS`
  (Sorento: "never cleared", absent means leave alone; the `container_number` rule generalised).
  PO / SPO: no attribute, pinned by test (AC-07-03).
- `mapping_catalog.py`: verify the header accepted set for `sales_order` is derived from the
  class (SINK + FALLBACK) and therefore picks up `ref`; if it is a hand-typed tuple, add `ref`
  there and pin `purchase_order`/`shipping_order` exclusion (AC-07-04).
- Docs: SQL pack section 1 (query + mapping table), section 3 "do not map `ref`", sprint-5/02
  Sorento addendum change log (two dated lines: `ref`; RTF ownership) (AC-07-06).

### 2.2 Backfill (`backfill.py`, module Alembic `0019_autocount_so_ref`, `update_tenant`)

`backfill_sales_order_ref(bind, *, schema)` - a copy of the
`backfill_shipping_order_container_number` shape (0016) narrowed to `sales_order`:

1. `existing_columns` guard on `ac_entity_config` / `ac_company` / `ac_field_mapping` -> 0.
2. For every `sales_order` config (frozen `sa.table`): resolve its company WITH the config's
   `tenant_id`; substitute `database_name` into the pinned `_OLD_SO_HEADER_QUERY` literal.
   - byte-identical to OLD -> write NEW text, append `"Ref"` to `result_columns`, row ENABLED;
   - identical to NEW -> nothing;
   - anything else -> query untouched; row enabled iff `"Ref" in result_columns` else DISABLED;
     one WARNING naming the config id (AC-07-09). This is the production `AED_SORENTO` case.
3. Row creation only when no `canonical_field == 'ref'` header row exists in ANY state
   (AC-07-10). `sort_order = MAX(sort_order)+1` within (config, scope header).
4. No commit; Alembic / `update_tenant` own the transaction. Manifest version bump.

Why not patch the customised query in place: splicing SQL text an operator authored is exactly
the kind of silent edit the 0016 review rejected; the operator step is one line and the
"Re-push all" action makes the timing irrelevant.

### 2.3 "Re-push all" backend (AC-07-13..19)

- Route: `POST /autocount/companies/{company_id}/entities/{entity_type}/etl-task/repush`,
  `require_permission("autocount.companies.manage")` (the configure bucket; `refetch-history`
  is the analog). Router = HTTP + Pydantic only.
- `EtlService.repush_task(tenant_id, company_id, entity_type) -> EtlRepushView`:
  1. load company + config under tenant (404 path as every sibling);
  2. `source_impl != sql_db` -> `EtlStateError`; `etl_status == draft` -> `EtlStateError`;
  3. `SyncJobRepository.first_unfinished(...)` -> `EtlStateError(running_run_id=...)`
     (closes the gap `refetch_entity` has: it resets state under a running job);
  4. `cleared = RowHashRepository.clear_all(...)`; if `active`: `config.next_reconcile_at =
     now(utc)` (scheduler claims a `reconcile` on its next sweep, existing path; incremental
     untouched); if `paused`: leave `None`;
  5. re-check `first_unfinished` (review finding: a job claimed between the first check and
     the commit could re-write hashes for a page it decided not to push); a job now present ->
     rollback + the same 409;
  6. ONE `commit()`; THEN `record_activity(kind=REPUSH..., ok)` with `clearedCount`,
     `entityType`, `actorUserId` (route takes `get_actor_user_id`) - the activity service commits
     the session it is handed, so it sits after the mutation's commit like every other call site
     in the module; plus one structured info log line for traceability when the activity row is
     volume-dropped.
- Fingerprints (`ac_doc_fingerprint`) and the watermark are NOT touched: the reconcile is a
  full extract, so neither gates what it pushes; the fingerprint sweep re-baselines itself on
  its next pass. Watermark reset would also re-read every page incrementally for nothing.
- Schema `EtlRepushResponse(ApiModel)`: `clearedCount: int`, `nextReconcileAt: datetime | None`,
  `status: str`.
- The follow-up reconcile: hashes empty -> every row `added` -> pushed -> Sorento upsert says
  `updated` -> counted delivered (`_OUTCOME_DELIVERED`), hashes repopulated (AC-07-19). The Runs
  row will read `Added = N, Updated = 0` for that run - documented in the tab copy and report.

### 2.4 Operator steps (production, after Sorento is live)

1. Sorento task, Query tab: add `h.Ref AS Ref,` under `h.Note AS Note,`; Test; Save. Saving a
   query with a new result column re-hashes every SO whose `Ref` is non-empty, so those re-push
   on the next run by themselves (the 0016 mechanism).
2. Mapping tab: enable the `Ref -> ref` row the backfill created disabled.
3. Re-push all is NOT needed for the notes: Sorento's #809 migration 510 rewrites the stored RTF
   notes to plain text, and their ingest treats an identical record as a no-op (no `updated_at`
   churn, verified by the Sorento owner session 2026-09-10). Step 1 alone re-pushes every SO with
   a non-empty `Ref`. Keep Re-push all for the generic case (a mapping or consumer-side change
   that must reach documents whose source did not move). When it is run: off-hours, one company
   first, typed confirm; expect a single long reconcile (150k headers + lines, Sorento ingest is
   synchronous with a batch cap of 1000). Sorento ranks `ref` below a note `PROJECT :` line and
   below an inquiry-sheet label, so a re-push only fills labels that are empty or lower-ranked.

### 2.5 Frontend (AC-07-20..25)

- Trio + hook: `repushEtlTask` in `autocount-service.{ts,mock.ts,real.ts}`, `repush()` on
  `useEtlTaskLifecycle` (same `perform()` busy/error pattern as `runNow`). Mock first (Phase 1),
  swapped at the service boundary in Phase 2.
- `activate-tab.tsx`: a destructive "Re-push all" `DeferredActionButton` (`useDeferredAction`,
  the D2/D13 grace-window undo model). Amended 2026-09-10 after review: the first cut composed an
  `AlertDialog` typed-confirm, which is a named PRINCIPLES.md design hard-fail (only four
  typed-confirm carve-outs exist) and contradicts the T5 ruling that dropped confirms on this
  tab's re-sync actions. Visibility = `active|paused` AND database task AND
  `useCan(AC_COMPANIES_MANAGE)`. Success toast: "Change tracking cleared for N documents. The
  full re-push starts on the next scheduler tick." Paused variant adds "Nothing moves until the
  task is resumed." No hint text elsewhere (foolproof-UI).
- Success `lib/toast`: "Change tracking cleared for 148,068 documents. The full re-push starts on
  the next scheduler tick." Runs list refetch. 409 in flight: toast error with the server text and
  a link to `running_run_id`.
- No new primitive, no motion added (existing button/dialog/toast springs). Verified 375 + 1280.

### 2.6 Deploy order (hard) and merge

Sorento `extra="forbid"` rejects every SO record carrying `ref` until their project-label PR is
deployed. Sequence: (1) this PR merges on review pass (merge != deploy: `deploy.yml` is
`workflow_dispatch`); (2) the `autocount-crm` session pings `foundryx-shared-service-1a` when
#809 + project-label are merged AND deployed; (3) `workflow_dispatch` Foundryx deploy
(`bootstrap_db` runs 0019: `ac_sim` swaps automatically, `Sorento` gets a disabled row + warning);
(4) operator steps 2.4. If Foundryx must deploy earlier for another reason, the backfill is
still safe: the production task's row lands DISABLED, so no `ref` leaves the ESB until step 2.4.
`ac_sim` (`SIM`) pushes `ref` immediately after deploy - it is a simulation company; if Sorento
is not live yet its SOs quarantine with a 422 and clear on the next run after Sorento deploys.

## 3. Files

Backend (`service_backend/modules/autocount/`): `presets.py`, `canonical/documents.py`,
`mapping_catalog.py` (verify), `backfill.py` (+ `_OLD_SO_HEADER_QUERY` literal), `alembic/
versions/0019_autocount_so_ref.py`, `bootstrap.py`/`__init__.py` (`update_tenant` call),
`manifest.json`, `services/etl_service.py` (`repush_task`, `EtlRepushView`), `schemas.py`
(`EtlRepushResponse`), `routers/companies.py` (route), `activity.py` (kind constant).
Tests (`service_backend/tests/`): `test_autocount_so_ref.py` (Group A + B), extend
`test_autocount_etl_task_routes.py` (Group C routes/guards/atomicity) and
`test_autocount_reconcile_push.py` (AC-07-19).
Frontend (`service_frontend/`): `services/autocount-service.{ts,mock.ts,real.ts}`,
`hooks/use-autocount-etl.ts`, `app/(protected)/autocount/companies/[id]/entities/[entityType]/
components/activate-tab.tsx` (+ `.test.tsx`).
Docs: SQL pack, sprint-5/02 addendum, this pair, test report, `documentation/backlogs/backlog.md`.

## 4. Slices and order

| Slice | Content | Executor | Gate |
|---|---|---|---|
| S1 | Group A + B backend, tests first (tester writes red tests from AC-07-01..11, coder greens), migration replayed on the lane DB (AC-07-12), docs (AC-07-06) | tester -> coder (Sonnet) | pytest green, replay log |
| S2a | Phase 1 FE mock: trio + hook + tab action + dialog + toast against the mock, agent-browser look at 375/1280 | coder | browser check |
| S2b | Phase 2 BE: red tests AC-07-13..19, service/route/schema, swap mock -> real | tester -> coder | pytest + vitest green |
| S3 | Evidence run AC-07-25, test report AC-07-28, reviewer (Opus) + security review (tenant scoping on the new route, 409 guard), codex second opinion if credits | tester, reviewer | DoD gate |

## 5. Risks and answers

- **Production task query is customised** -> backfill cannot add `Ref`; disabled row + warning +
  documented one-line operator step; no silent SQL splicing.
- **Sorento not live when we deploy** -> `Sorento` task sends no `ref` (row disabled); `ac_sim`
  may quarantine briefly; documented, acceptable for a simulation company.
- **Re-push on a paused task** -> hashes cleared, nothing scheduled; resume re-arms; the dialog
  says so.
- **Re-push while a run is in flight** -> 409 with the run id; nothing cleared (the gap
  `refetch_entity` still has is registered in the backlog, not fixed here).
- **150k documents in one reconcile** -> existing paged extraction + rate-limited sink; run
  off-hours, one company first (2.4). The scheduler's overlap guard keeps ticks from stacking.
- **Runs tab reads `Added = 149k`** after a re-push although Sorento answered `updated` -> copy
  in the dialog + report; a `Re-pushed` column is backlog, not this slice.

## 6. Backlog

- BL: `refetch_entity` (API entities) resets watermark state without the in-flight guard.
- BL: Runs tab distinguishes re-baselined adds from genuine adds.
- BL: typed-confirm shows the tracked row count before confirming (needs a count on the task view).

## 7. Decision log

- D1 (2026-09-10, user): merge on review pass, deploy after the Sorento ping. Deploy is manual.
- D2 (2026-09-10, user): build "Re-push all" now, not a one-off SQL.
- D3: `ref` in `FALLBACK_FIELDS` + `OMIT_WHEN_EMPTY_FIELDS`, never sent null; Sorento "never
  cleared" semantics; SO only.
- D4: no SQL splicing of customised queries; disabled row + warning + operator step.
- D5: re-push clears `ac_row_hash` only; watermark and fingerprints untouched.
- D6: re-push permission = `autocount.companies.manage` (configure bucket, `refetch-history`
  analog); no new key, no grant sweep.
- D7: drift exclusion dropped: `compute_diff` is pushed-vs-pushed; `read_back` has no caller.
- D8 (2026-09-10, review): Re-push all is a `DeferredActionButton`, not a typed-confirm dialog.
  PRINCIPLES.md's design hard-fail (no new destructive confirm outside the four named carve-outs)
  and the T5 ruling on this tab override the grill default; the grace-window undo is the guard.
- D9 (2026-09-10, review): activity row is written AFTER the mutation's commit (the activity
  service commits the session it is handed), carries `actorUserId` from `get_actor_user_id`,
  and the in-flight guard is re-checked after `clear_all` before the commit. The structural fix
  (stamp `repush_requested_at`, let the reconcile clear hashes inside its own run transaction,
  which also removes the "Added = N" reporting artefact) is BL-SS-197, not this slice.
- D10 (2026-09-10, review round 2): the deferred action is the SERVER-PARKED engine
  (`useDeferredAction` + `pendingActionsService` on the client, a `DeferredActionDef`
  `autocount_etl_task.repush` in `modules/autocount/deferred_actions.py` whose executor calls
  `EtlService.repush_task`), not a client-side countdown timer. D2 names the model explicitly
  (server-deferred, tenant-configurable window), the registry already serves omnichannel and
  ideation, and the task has a per-row id (`ac_entity_config`). The POST route stays as the API
  path; the tab never calls it.
