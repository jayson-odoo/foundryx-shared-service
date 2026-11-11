# Plan 62 Test Execution Report: AutoCount PO link batch, retry rule, unlink merge, over-link index

Lane PO-LINK-BATCH, branch `crew/po-link-batch`. UAC: `62-autocount-po-link-batch-acceptance-criteria.md`.
Backend only, no screen: browser / agent-browser runs are N/A (no UI surface, nothing at 375px or 1280px).

## Final run (12 Nov 2026, after review rounds 1-4)

Command (every `tests/test_autocount_write_back_*.py` plus `test_module_migrations_engine_url.py`,
`test_s12_mapping_reset_route.py`, `test_autocount_line_linkage.py`, `test_deploy_module_bootstrap_wiring.py`,
`test_deploy_lock_holder_report.py`; 43 files):

    cd service_backend && xargs .venv/bin/python -m pytest -q -n 2 --dist loadfile < files.txt

Result: **1448 passed, 0 failed, 0 skipped.** The full 3 minute suite was not run by the tester.

Plan 62 test files (each written red first): `test_autocount_write_back_retry_rule.py`,
`test_autocount_write_back_link_batch.py`, `test_autocount_write_back_unlink_merge.py`,
`test_autocount_write_back_link_index.py`, `test_module_migrations_engine_url.py`, and the review round files
listed below. Existing tests adapted, no assertion weakened: `World` in `test_autocount_write_back_operations.py`
(linked row price 5.5 so the old unlink tests stay on the plain path) and an autouse fixture in
`test_autocount_write_back_runner.py` (merge off there; the merge is proven in the merge file and by db3).

## Review rounds (tests written red first, then fixed by the coder)

| Round | Test file | Covers |
|---|---|---|
| 1 | `test_autocount_write_back_review_round1.py` | pending batch reconcile (landed / nothing landed / partial = needs attention), create resend lookup seam, index follows a landed write, re-key collision |
| 2 | `test_autocount_write_back_review_round2.py` | unknown outcome never released, batch answer carries `links` / `freeLine` on every outcome, index after a cancelled delete intent, pending merge reconcile, resume-settled not-applied is released |
| create lookup | `test_autocount_write_back_create_lookup.py` | the real `find_created_doc` against a fake vendor that stamps `CreatedTimeStamp` / `LastModified` (MYT): found / none / ambiguous, window (30 min off is not ours, 8 min skew is ours), MYT midnight, numbered body, call log |
| 3 | `test_autocount_write_back_review_round3.py` | lookup only for stored create rows, lock connection failure = busy refusal, lookup reach and ownership, lookup logged under the stored operation, pending links count against the guard, resume of a create row |
| 4 | `test_autocount_write_back_review_round4.py` | backfill honours a live delete intent and ignores a discarded one, needs-attention notice from batch and merge reconcile, bounded ownership check |

## AC matrix

Test names are `test_ac_62_<nn>_*` in the file shown. "db3" = the runner suite `--suite batch`
(`documentation/integrations/autocount/test-report-2026-11-11-po-link-batch.md`, tag 1111C, PASS 7 / FAIL 0).

| AC | Status | Evidence |
|---|---|---|
| AC-62-01 | PASS | link_batch: `test_ac_62_01_three_links_below_the_row_qty_is_one_put_1_and_one_put_2`, `..._put_2_restores_price_and_date_on_all_new_rows_and_the_links_stay`, `..._route_answer_carries_each_new_po_dtl_key_and_the_free_line` |
| AC-62-02 | PASS | link_batch: `test_ac_62_02_sum_equal_to_the_row_qty_deletes_the_row_and_has_no_free_line` |
| AC-62-03 | PASS | link_batch: `test_ac_62_03_links_across_two_sos_each_row_carries_its_own_doc_no` |
| AC-62-04 | PASS | link_batch: `test_ac_62_04_every_pre_check_refusal_sends_zero_puts` (15 cases: unknown SO row, item, UOM, SO cancelled, PO cancelled, linked, transferred onward, received, sum above free, above outstanding, duplicate, empty, over 20, qty 0, qty negative), `..._qty_above_outstanding_names_the_so_dtl_key`, `..._an_so_row_linked_from_another_po_by_the_index_counts_against_outstanding`, `..._route_refusal_is_a_4xx_with_the_code_and_zero_puts`, `..._route_requires_the_idempotency_key` (422), `..._route_bad_links_shape_is_rejected_with_zero_puts`; db3 B07 (line above outstanding, within the PO row's free quantity: `ALL_LINKS_SKIPPED` naming `QTY_ABOVE_OUTSTANDING`, 0 PUTs) and B11 (2 good + 1 over outstanding: 2 linked, 1 skipped, 2 PUTs) |
| AC-62-05 | PASS | link_batch: `test_ac_62_05_vendor_refusal_is_vendor_error_with_no_put_2_and_nothing_linked`, `..._route_vendor_error_reports_no_linked_row`, `..._the_fake_vendor_refuses_a_put_with_one_bad_linked_row_and_lands_nothing` |
| AC-62-06 | PASS | link_batch: `test_ac_62_06_put_2_failure_is_done_with_the_warnings_and_the_links_kept` |
| AC-62-07 | PASS | link_batch: `test_ac_62_07_done_replay_is_the_stored_answer_with_no_vendor_call`, `..._done_key_with_another_body_is_an_idempotency_conflict`, `..._route_replay_and_conflict` |
| AC-62-08 | PASS | link_batch: `test_ac_62_08_no_key_is_401_and_nothing_is_sent`, `..._a_pull_only_key_is_403_scope_required`, `..._another_tenants_company_is_never_resolved`, `..._body_tenant_and_company_ids_are_ignored`; `test_ac_62_every_vendor_call_of_a_batch_is_in_the_api_call_log` covers the call-log line of the UAC preamble |
| AC-62-09 | PASS [db3] | runner B01 (batch of 1), B02 (3), B03 (5), B04 (today's 3 calls): 2 PUTs per batch whatever the size, 6 PUTs for today's flow; timings 2.0 / 1.7 / 2.1 s vs 5.6 s (tag 1112D at b9d21b12, SO row lock live, 0 advisory locks after; db3 latency varies 2 to 3 times between runs). Runner unit tests: `test_autocount_write_back_runner_batch.py` |
| AC-62-20 | PASS | retry_rule: `test_ac_62_20_vendor_error_resend_same_key_runs_fresh[unlink_row,link_row]`, `..._with_a_corrected_body_runs_the_corrected_body`, `..._the_old_row_is_kept_re_keyed_for_history`, `..._refused_resend_same_key_runs_fresh`, `..._gateway_unlink_route_resend_after_vendor_error_runs_fresh`, `..._run_primitive_resend_after_refused_or_vendor_error_runs_fresh[2]`, `..._run_primitive_with_a_corrected_body_is_not_a_conflict`; db3 B06 (refused batch then the fixed batch under the same key runs fresh); db3 B08 to B10 (create resend: found, 0 second POST; nothing sent: 1 POST). Review rounds: create resend looks the document up first (`test_autocount_write_back_create_lookup.py`, round1 `test_rr2_*`, round3 `test_r3_1_*`, `test_r3_3_*`), an unknown outcome is never released (round2 `test_r2a_*`), a resume-settled not-applied operation is released (round2 `test_r2e_*`), re-key never collides (round1 `test_rr4_*`) |
| AC-62-21 | PASS | retry_rule: `test_ac_62_21_pending_resend_that_had_landed_is_done_with_no_second_replace_put[unlink_row,link_row]`, `..._that_had_not_landed_sends_the_put_once[unlink_row,link_row]`. Review rounds extend it to the batch (round1 `test_rr1_*`: landed = done, nothing landed = one fresh PUT 1, any partial match = needs attention with zero PUTs) and to the unlink merge (round2 `test_r2d_*`), both with the needs-attention notice (round4 `test_r4_3_*`) |
| AC-62-22 | PASS | retry_rule: `test_ac_62_22_done_resend_is_the_stored_answer_with_no_vendor_call`, `..._changed_body_is_an_idempotency_conflict`, `..._gateway_done_resend_answers_the_stored_result_without_the_vendor`. The kill test (release `done` too, a test must fail) was not run in this pass |
| AC-62-23 | PASS | retry_rule: `test_ac_62_23_needs_attention_resend_is_the_stored_answer_not_a_rerun` |
| AC-62-30 | PASS | unlink_merge: `test_ac_62_30_unlink_merges_into_the_first_matching_free_row_with_one_put`, `..._leaves_the_other_free_row_and_the_spo_row_alone`, `..._with_several_matches_the_first_by_row_order_wins_and_an_spo_target_is_skipped`, `..._the_unlinked_qty_leaves_the_so_row`, `..._route_answer_names_the_free_rows_dtl_key`, `..._relink_is_unchanged_it_still_replaces_with_a_new_linked_row` |
| AC-62-31 | PASS | unlink_merge: `test_ac_62_31_a_field_that_differs_on_every_candidate_means_no_merge[ItemCode,UOM,Location,UnitPrice,DeliveryDate]`, `..._a_linked_free_row_candidate_is_never_merged_into`, `..._a_row_an_spo_points_at_is_never_merged_into`, `..._a_received_free_row_the_receipt_reader_reports_received_is_never_merged_into`, `..._route_without_a_match_answers_the_new_free_row_key`. Plan D7 was amended by the coder: an UNKNOWN receipt allows the merge (commit 8ed77585); the test pins the known-received case |
| AC-62-32 | PASS [db3] | runner B05 (unlink merge, 1 PUT, raises the B01 free row) and the S0 proof case (c) in `crew/state/files/autocount-api/db3-requests-11nov-po-link-batch.json` |
| AC-62-40 | PASS | link_index: `test_ac_62_40_service_sum_is_fresh_rows_plus_the_index_of_other_pos`, `..._primitives_sum_is_the_index_and_never_scans_staged_pos` (spy: `for_entity` raises for the PO entity), `..._the_fresh_po_replaces_its_own_index_rows`, `..._other_tenants_index_rows_never_count`, `..._double_count_regression_two_staged_copies_of_one_other_po_count_once`; pending links count against the guard (round3 `test_r3_5_*`) |
| AC-62-41 | PASS | link_index: `test_ac_62_41_write_back_staging_writes_the_pos_rows_and_replaces_them_on_a_newer_copy`, `..._a_cancelled_po_leaves_no_rows`, `..._sync_pull_writes_and_rewrites_the_pos_rows`; the index follows a verified write even when the staged copy is left alone (round1 `test_rr3_*`) and a cancelled delete intent restores the rows (round2 `test_r2c_a_cancelled_*`) |
| AC-62-42 | PASS | pytest: `test_ac_62_42_migration_0045_exists_with_a_short_revision_id`, `test_s12_mapping_reset_route.py::test_ac_12_32` (bumped), backfill selection (round2 `test_r2c_the_backfill_reads_the_newest_non_delete_copy`, round4 `test_r4_1_*`: newest non-discarded row, skipped when it is a live delete). Live Postgres (coder, scratch copy `foundryx_service_plb` of the db3 write DB, `DATABASE_URL` exported in the same command): `run_module_migrations(engine, "autocount")` -> `0045_autocount_po_so_link`, table + 3 indexes (pkey, `ix_ac_po_so_link_so_dtl`, `ix_ac_po_so_link_po_ref`); backfill 7 rows over 3 POs = an independent SQL count over the newest non-cancelled staged copies; cancelled PO gave none. Re-checked by the captain after the S5 db3 runs: still 0045, 31 rows (runner staging writes), same 3 indexes; shared `foundryx_service` stays at 0044 (crew reverted the accidental upgrade) |
| AC-62-50 | PASS (doc check) | `55-autocount-write-link-contract.md` carries section 4.1a (`po-links/batch`), the retry rule, the unlink merge and the create resend rule (commits 123d10d6, 209766f9); the batch answer wire is machine-checked for every outcome by round2 `test_r2b_*`; the rest was read by the tester |

## Found in the lane (not an AC)

- `run_module_migrations(engine, name)` ignored the passed engine for Alembic's URL: red tests in
  `test_module_migrations_engine_url.py`, fixed in d082d60b.
- The batch tests were written before the code; 37 of 39 and 3 of 16 were red for the right reason
  (`UNKNOWN_OPERATION`, 404, missing model) before the coder started.

## Deferred / open

- AC-62-22 kill test (release `done` on resend, see a test fail) and mutation checks for the retry rule: not run.
- No agent-browser evidence: backend only.
