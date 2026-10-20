# 32 - Billing documents + AR outstanding: test execution report

Lane SS-BILLING-FEED, PR #127. Fixture rows only; no AutoCount access exists before 25 Oct, so no live
extract was possible. Backend: `tests/test_autocount_billing_feed.py` (113), `tests/test_autocount_contract_version_compare.py` (25);
every autocount/sorento/doc-feed suite 3159 passed. Frontend: autocount vitest 937 passed.

| AC | Result | Evidence |
|---|---|---|
| AC-32-01 | PASS | `test_2_10_is_above_every_2_x_float_threshold`, `test_every_existing_gate_stays_open_on_2_10` |
| AC-32-02 | PASS | `test_parse_keeps_minor_as_integer`, `test_parse_rejects_non_versions` (incl. hostile input) |
| AC-32-10 | PASS | `test_billing_preset_shape`, `test_each_new_entity_is_registered_in_every_catalogue` |
| AC-32-11 | PASS | `test_billing_preset_shape`, `test_only_credit_and_debit_notes_select_our_invoice_no` |
| AC-32-12 | PASS | `test_billing_line_cut_is_the_same_in_all_three_queries`, `test_a_charge_line_without_an_item_is_kept_with_no_product` |
| AC-32-13 | PASS | `test_billing_fingerprint_columns`, `test_every_fingerprint_query_keys_its_rows_on_doc_key` |
| AC-32-14 | PASS | `test_billing_header_ref_is_database_type_code_doc_key`, golden record line refs |
| AC-32-15 | PASS | `test_the_invoice_preset_maps_a_fake_row_to_the_exact_contract_record`, `test_the_wire_is_json_numbers_and_every_key_every_time` |
| AC-32-16 | PASS | `test_against_doc_no_is_the_first_non_blank_entry`, `test_a_credit_note_line_links_to_its_invoice_line` |
| AC-32-17 | PASS | DO / CN / unlinkable line tests |
| AC-32-18 | PASS (book half) / DEFERRED (grant half) | `test_a_do_line_without_a_do_feed_book_is_a_named_error_never_unlinked`; the DODTL-grant failure needs a live book |
| AC-32-19 | PASS | sink door / deletions / gate / `auto_push` refusal tests |
| AC-32-20 | PASS (best effort) | `test_the_sweep_fires_notes_after_invoices` (kill test: removing the sort goes red) |
| AC-32-30 | PASS | `test_ar_outstanding_preset_shape`, `test_the_ar_fingerprint_sweep_finds_a_debtor` |
| AC-32-31 | PASS | `test_the_ar_preset_maps_a_fake_debtor_to_the_exact_contract_record` |
| AC-32-32 | PASS | `test_the_ar_match_is_one_to_one_both_ways`, CN negative in golden record |
| AC-32-33 | PASS | `test_as_of_survives_the_staged_round_trip_and_is_not_restamped`, no read-time SQL column |
| AC-32-34 | PASS | `test_a_paid_off_debtor_sends_zero_and_an_empty_list`, `test_only_ar_outstanding_has_no_deletions_door` |
| AC-32-35 | PASS | AR gate + `auto_push` refusal at 2.9 |
| AC-32-40 | PASS (picker, prerequisite) / DEFERRED (banner, BL-SS-307) | vitest add-entity + meta tests; `test_an_invoice_without_a_delivery_orders_book_warns_up_front` |
| AC-32-41 | PASS | full autocount suites green, wire tests of SO/PO/SPO/linked untouched |

Browser evidence at 375px / 1280px: DEFERRED to the owner's hand test (crew test copy). The only UI change is
five entries in the existing Add-entity picker and the existing prerequisite card. Live end-to-end against
AutoCount: DEFERRED to the RUNBOOK first run (S4, owner, after 25 Oct).
