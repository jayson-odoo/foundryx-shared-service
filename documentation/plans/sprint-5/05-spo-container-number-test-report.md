# SPO `container_number` from AutoCount `PO.Ref` - test execution report

Lane `feat/spo-container-number` (off `fix/push-marks-per-chunk` 369b1fe4). Coder commits: `3f3eb72d` (query + preset + canonical), `35507735` (backfill + module Alembic 0016 + `update_tenant` + manifest 0.6.1), `4f135a59` (addendum section 3 + BL-SS-144), `5f250a66` (one-time re-stage note). Tester commits: `c5f884a0` (red tests, written before the coder), this commit (PO-untouched pin + this report).

**Backend-only lane: there is no browser flow.** Nothing in this lane adds or changes a screen; the operator-visible effect is a new mapping row that the existing mapping editor already renders (`Ref -> container_number`, header scope, enabled) and a rewritten header query on tasks that still carried the preset text verbatim. No `agent-browser` run was recorded and no 375/1280 evidence exists for this lane by design; the DoD's "verified from the user's perspective" clause is met by the live-Postgres replay (section 3) and by the Sorento prod contract check (section 4), which is the user-visible outcome here.

Verified 2026-09-07 by the tester seat on the lane worktree (`.claude/worktrees/spo-container`), suite = pytest on the in-memory SQLite rig (`service_backend/.venv/bin/python -m pytest`), plus the coder's live-Postgres migration replay as reported in `35507735`.

## 1. Verdicts (one line per contract line of the brief)

Test file: `service_backend/tests/test_autocount_spo_container_number.py` (28 tests). On the base tree 369b1fe4: 19 red / 8 guard-green; on the coder's HEAD `5f250a66`: 28 / 28 green.

| # | Contract line | Verdict | Evidence |
|---|---|---|---|
| AC-SPO-01 | `presets._PO_HEADER_QUERY` selects `h.Ref AS Ref`; no UDF column in the generic query; SPO and PO presets keep sharing it | PASS | `test_po_header_query_selects_ref_and_no_udf_column` |
| AC-SPO-02a | `CanonicalShippingOrder.container_number: Optional[str] = Field(None, max_length=100)`; 101 chars is a `ValidationError` | PASS | `test_shipping_order_declares_container_number_optional_str_max_100` |
| AC-SPO-02b | Sent to Sorento only at contract major >= 2 (same gate as `FALLBACK_FIELDS`): v1 payload omits it | PASS | `test_v1_payload_omits_container_number_even_when_set`; `test_sorento_sink_projects_container_number_through_the_contract_gate[1-False]` (the sink's own `_to_records` projection) |
| AC-SPO-02c | v2 payload carries it when present | PASS | `test_v2_payload_carries_container_number_when_present`; sink gate `[2-True]`, `[3-True]` |
| AC-SPO-02d | v2 payload omits it when None (addendum section 11: absent = leave alone, null = clear) | PASS | `test_v2_payload_omits_container_number_when_none`. Note: this pin was RED under the pre-lane header `sink_payload` builder even once the field existed (it emitted `"container_number": null`); the coder's `3f3eb72d` drops the None key |
| AC-SPO-02e | `CanonicalPurchaseOrder` has no such field; a PO payload never carries it at any version; the mapping profile offers it as a `shipping_order` header target only | PASS | `test_purchase_order_has_no_container_number_field`, `test_purchase_order_payload_never_carries_container_number[1/2/3]`, `test_mapping_profile_offers_container_number_as_a_shipping_order_header_target` |
| AC-SPO-03 | `SPO_PRESET.header` gains `PresetField("Ref", "container_number", "string")` (not required, no formula); `PO_PRESET.header` maps neither `Ref` nor `container_number` | PASS | `test_spo_preset_header_maps_ref_to_container_number_not_required`, `test_po_preset_header_maps_neither_ref_nor_container_number` |
| AC-SPO-04a | Backfill adds an enabled `Ref -> container_number` header row to every existing `shipping_order` task, across tenants, idempotent, never on a PO task | PASS | `test_backfill_adds_an_enabled_ref_row_to_every_shipping_order_task_across_tenants` (two tenants, second pass adds nothing) |
| AC-SPO-04b | An operator's own `Ref` row (disabled, custom formula) is neither duplicated nor flipped | PASS | `test_backfill_leaves_an_existing_ref_row_alone` |
| AC-SPO-04c | A stored header query byte-identical to the OLD preset text with the company's OWN `database_name` substituted is replaced by the new text; every other `source_config` key is untouched; `Ref` enters `result_columns` | PASS | `test_backfill_replaces_a_byte_identical_old_preset_query_with_the_new_text` |
| AC-SPO-04d | A customised query is left alone (no `Ref` in `result_columns`) and a WARNING naming the config id is logged; the mapping row still lands (a) independent of (b) | PASS | `test_backfill_leaves_a_customised_query_alone_and_warns_naming_the_config_id` |
| AC-SPO-04e | A query matching a SIBLING company's substitution counts as customised | PASS | `test_backfill_ignores_a_query_that_matches_another_companys_database` |
| AC-SPO-04f | An existing `purchase_order` task is left completely alone even when its stored query byte-matches the old preset text: query, `source_config`, `result_columns` unchanged, no mapping row, helper returns 0, nothing logged about it | PASS | `test_backfill_leaves_an_existing_purchase_order_task_completely_alone` (added this round at the coordinator's request; kill-tested, section 2) |
| AC-SPO-04g | Schema-tolerant: a bind without `ac_field_mapping` / without `source_config`, or with no module tables at all, is a clean 0 | PASS | `test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables` |
| AC-SPO-04h | Same helper on the `update_tenant` path (App Store update of an installed tenant): row added, query rewritten, `Ref` in `result_columns` | PASS | `test_update_tenant_runs_the_container_number_backfill` |
| AC-SPO-04i | Module Alembic `0016_*` exists, chains onto `0015_autocount_run_requests`, revision id <= 32 chars, single head, calls the helper; manifest bumped past 0.6.0 (now 0.6.1) | PASS | `test_revision_0016_chains_onto_0015_and_calls_the_helper`, `test_manifest_version_is_bumped_past_0_6_0`; live Postgres: section 3 |
| AC-SPO-05 | Re-offer: a document whose ONLY change is a newly selected `Ref` value is re-staged as an update (`op = upsert`, `updated_count >= 1`, `added_count == 0`) and its canonical carries `container_number` | PASS | `test_a_document_whose_only_change_is_a_newly_selected_ref_is_restaged_as_an_update` (SQLite source table gains the column between two runs; `last_modified` untouched; reconcile run) |
| AC-SPO-06a | Addendum section 3 documents `container_number` (AutoCount `PO.Ref`, `shipping_orders` only, contract 2.1+) | PASS | `test_addendum_section_3_documents_container_number_from_po_ref`; addendum lines 79-80 |
| AC-SPO-06b | Backlog entry for the `PO.UDF_ShipOrder` per-company routing follow-up | PASS | `test_backlog_carries_the_udf_shiporder_routing_follow_up`; BL-SS-144 (P3, open; count in AED_SORENTO today reported as 0 by the coder, pending the operator's own count) |

Stored-vs-referenced finding (pinned by the 04c/04e/04f tests): the header query is STORED per task in `AcEntityConfig.source_config["query"]` (`EtlService` `clean` dict). `DocumentPreset.header_query` has exactly one reader, `list_mapping_presets` (the mapping editor's "Use preset" picker), which substitutes `{database}` with the company's `database_name`. Nothing at run time references the preset text, so an existing task keeps the old query until the backfill rewrites it; the byte-identity check is therefore against the old text with the task's own company database substituted.

Regression run on the coder's HEAD over the neighbouring autocount surface (document mapping, documents, bulk load + rounds 4/6b/review, contract 2.1 delivery + masters, Sorento sink, backfill schema tolerance + session transaction, DB-company seed source, pipeline, entity parity, push marks per chunk): **499 passed, 0 failed** (194 s).

## 2. Mutation proof (tests fail for the right reason)

All mutations were applied in a detached scratch `git worktree` and reverted; the coder's tree was never touched.

| Mutation | Expected | Observed |
|---|---|---|
| Base tree 369b1fe4, no product change | 19 red, 8 guard-green | 19 red / 8 green. The re-offer test is red on the missing canonical field, not on a run failure (the mapping engine silently ignores an unknown target) |
| Phase A: `h.Ref AS Ref` in the query + the SPO preset row + `container_number` on the SPO model inside `FALLBACK_FIELDS` (pre-lane payload builder) | preset/canonical/sink/re-offer green; v2-None pin still red | 14 green incl. the end-to-end re-offer; `test_v2_payload_omits_container_number_when_none` red (`null` emitted) |
| Phase B: the same leak into `PO_PRESET.header` and `CanonicalPurchaseOrder` | the PO pins go red | `test_po_preset_header_maps_neither_ref_nor_container_number`, `test_purchase_order_has_no_container_number_field`, `test_purchase_order_payload_never_carries_container_number[2]`, `[3]` red (`[1]` stays green: v1 omits fallbacks by construction) |
| Coder HEAD + helper filter widened to `entity_type IN ('shipping_order', 'purchase_order')` | the new AC-SPO-04f pin goes red | `test_backfill_leaves_an_existing_purchase_order_task_completely_alone` red; `..._across_tenants` also red (unique-constraint trip on the PO config's row) |

Backfill absence/migration/docs tests fail on absence only (no helper, no 0016 file, no docs line); the kill above covers the one behaviour the coder could get wrong silently (sweeping PO tasks).

## 3. Live-Postgres evidence (coder's replay, as reported in `35507735`)

The suite cannot see migrations (conftest = `create_all`). The coder reports, against live local Postgres: `alembic upgrade head` on the module history reaches `0016_autocount_spo_container` as the single head (29-char revision id), and the backfill end to end on a real `shipping_order` task rewrites a byte-identical old-preset query, appends `Ref` to `result_columns` and inserts the enabled `Ref -> container_number` mapping row. The tester did not re-run the replay (the shared local Postgres is in use by other lanes and the tester never reseeds or migrates it in a lane); the unit tests in section 1 cover the same helper on both the Alembic connection and the `update_tenant` session paths.

## 4. Sequencing for production (operator-supplied check pending)

Order matters here, because a v2 SPO payload that names a field Sorento has not declared trips their `extra="forbid"` guard and quarantines every shipping order in the batch.

1. **Sorento prod contract check - operator to supply.** `GET /api/v1/external/contract` on Sorento prod must list `container_number` under `fields_added.shipping_orders` before the ESB deploy. Placeholder for the operator's capture:

   ```
   GET https://<sorento-prod>/api/v1/external/contract
   version: ____
   fields_added.shipping_orders: ____   (must include "container_number")
   captured by: ____   at: ____ (UTC)
   ```

   If it is absent, hold the ESB deploy (or keep the SORENTO connection at contract major 1, where the field is never sent) until Sorento ships it.
2. **ESB deploy**: `bootstrap_db` / module Alembic to 0016 (the backfill runs inside the migration; existing tenants that update through the App Store get the same helper from `update_tenant` at 0.6.0 -> 0.6.1). Post-deploy, confirm the operator Update step per the 2026-09-06 module-migration incident lesson (BL-SS-101/103) so no host is left stamped before 0016.
3. **Expect a one-time full SPO re-stage** on the first run after the backfill: `Ref` enters the compared set, every SPO header hash changes, and every existing SPO document re-stages once as an UPDATE (coder note `5f250a66`; plan 03's live load counted 3,287 SPO documents). This is intended - it is how the 68,519 already-pushed allocations receive their container numbers - and is the same mechanism as the `LineCount` fingerprint guard. Size the run window accordingly; it is not a regression.
4. **Verify from Sorento**: one SPO whose AutoCount `PO.Ref` is populated shows that value as the container number after the push; one with an empty `Ref` is unchanged (absent key = untouched, never cleared).

## 5. Notes for review

- Two tests read repo documents (`02-autocount-document-mapping-sorento-addendum.md` section 3 and `backlog.md`). They pin the cross-repo contract line and the follow-up register; if the crew prefers docs to stay guide-writer-owned rather than suite-enforced, they are the last two tests in the file and drop cleanly.
- The SPO staging run of a draft task ends `needs_review` (awaiting approval), not `done`; the re-offer test accepts either.
- The mapping engine ignores an unknown canonical target silently (a `Ref -> container_number` row on a model without the field produced no error and no field). Not a defect for this lane, but worth knowing when reading a "row present, value missing" report.
- At the time of this report the coder had further uncommitted edits in flight on `backfill.py`, `0016_autocount_spo_container.py`, the addendum and the backlog; the verdicts above were taken on committed HEAD `5f250a66` and will need a re-run once those land.

## Residue

None on the shared Postgres (no seed, no migration run by the tester). Scratch worktrees `wt-spo` / `wt-spo2` removed and pruned.
