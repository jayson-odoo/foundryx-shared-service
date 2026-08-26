# Sprint 4 · Plan 13 - AutoCount ESB (slice 1) · Test Execution Report

**Feature branch:** `sprint-4/13-autocount-esb` @ `bb3ad0c` (+ the E2E spec added by this pass)
**Tester:** automated QA agent · **Date:** 2026-07-21
**Plan:** `13-autocount-esb.md` · **UAC:** `13-autocount-esb-acceptance-criteria.md`
**Scope of this report:** slice 1 = **AC-13-01 … AC-13-15**, plus cross-cutting **AC-13-41 … AC-13-46**.
Slices 2-6 (AC-13-16 … AC-13-40) are out of scope and are not verdicted here.

---

## Environment / stack bringup

- Backend FastAPI on **:8001** from `service_backend` (cwd confirmed via `lsof`), Postgres
  `foundryx_service`. `CELERY_TASK_ALWAYS_EAGER=true`, so the `autocount_sync` job runs INLINE on the
  request - the "Sync now" click returns a job already in `needs_review`.
- Frontend Next on **:3001**, **fresh production build** (`rm -rf .next && npm run build && npm start`);
  `:3001` cwd confirmed = `service_frontend`. First attempt ran against `npm run dev` and failed
  because the dev-overlay `<nextjs-portal>` intercepts pointer events on the sidebar - the prod build
  is the correct rig (Env Finding #1).
- `autocount` module present in the catalog at version `0.1.0`; `app_autocount` schema has 7 tables.
- Every E2E test provisions its **own** tenant and installs the module into it, so no shared tenant
  state is mutated and the spec is safe under `fullyParallel`.

### The vendor is scripted; the pipeline is not

There is **no reachable live AutoCount** from a test runner: the demo instance is customer-hosted and
IP-whitelisted to one workstation. The spec therefore stands a small Node HTTP server in front of the
only two endpoints slice 1 calls (`POST /api/Server/Login`,
`POST /api/GoodsReceivedNote/GetGoodsReceivedNote`) and points a **real `erp` connection** at it.

Only the vendor's socket is scripted. Everything downstream is the production code path: the real
provider `test()`, real company discovery from the login response, the real `autocount_sync` handler,
real watermark, real mapping + coercion, real `compute_diff`, real staged rows, the real atomic
approval claim. The scripted responses reproduce the live quirks recorded in plan §4a - bare-array
login carrying BOTH `Token` (GUID) and `JWTToken`, `"F"` string booleans, 8-dp decimal strings,
`YYYY/MM/DD` dates, `GRDTL` (not `GRNDTL`) nested lines.

---

## Suite results (regression gate)

| Suite | Command | Result |
|---|---|---|
| Backend (full) | `python -m pytest -q` | **1268 passed**, 182 warnings, 864s |
| Backend (this feature) | `pytest tests/test_autocount.py tests/test_autocount_pipeline.py -q` | **124 passed**, 64s |
| Frontend unit (full) | `npm test` | **820 passed** (104 files) |
| Frontend unit (this feature) | `vitest run lib/autocount-diff.test.ts services/autocount-service.test.ts components/platform/autocount/record-diff.test.tsx app/(protected)/autocount/companies/components/list-configs.test.tsx` | **44 passed** |
| E2E (this plan) | `npx playwright test e2e/autocount.spec.ts` | **2 passed** (12.0s) |
| E2E stability | `npx playwright test e2e/autocount.spec.ts --repeat-each=3` | **6 passed** (22.8s, 5 workers) |
| E2E stability (re-confirm) | `--repeat-each=2` after the Finding #4 fix | **4 passed** (13.3s) |
| Lint | `npx eslint e2e/autocount.spec.ts` | clean |

Status-engine + tenant-lifecycle suites are inside the 1268 and stayed green.

---

## E2E scenarios (real clicks, live stack)

Spec: `service_frontend/e2e/autocount.spec.ts`. Every tenant, connection and company name is
timestamped + randomised (`e2e-ac-<tag>-<base36>`); no fixed literals, so residue from an earlier run
cannot collide. After the single `goto` of the sign-in page, **every** navigation is a click on
something a real operator can see - no deep-link `page.goto`, no URL shortcuts.

### Scenario 1 - Test → Sync now → review → Approve, entirely by clicking (AC-13-14) · **PASS (click path)**

- **User story:** As a tenant Admin I connect an AutoCount company, pull changed GRNs, review what
  changed, and approve the batch - without ever typing a URL.
- **Precondition:** dedicated timestamped tenant with the `autocount` module installed (operator API,
  setup only); scripted AutoCount on an ephemeral loopback port; signed in through the real login form.
- **Steps (all clicks):**
  1. Sidebar → **Settings → Integrations** → **Connect integration** → Provider **AutoCount** → fill
     base URL / AppId / User ID / Password → **Create**.
  2. Form **Actions → Test connection**.
  3. Sidebar → **AutoCount → Companies** → **Connect company** → pick the connection → **Create**.
  4. Company detail → **Sync now** on the Goods received note row (sync 1: two new GRNs).
  5. On the review batch: **Approve**.
  6. **Back** → **Sync now** again (sync 2: GRN-0001 changed, GRN-0003 new).
  7. Review the diff → **Approve**.
  8. **Back** → **Runs** tab.
- **Expected:** the provider offers exactly four fields (no AppSecret, no company field); Test signs in
  ONCE and echoes the DISCOVERED company; the company database `AED_VSOFT` appears read-only; each sync
  sends `LastModifiedFrom`/`To` with a **list-valued** `DocNo`; the batch stops at **Needs review** with
  nothing pushed; Approve moves every record to `PUSHED` and the job to `done`; the run appears in Runs.
- **Actual:** exactly as expected. `vendor.logins() === 1` after Test; the first read filter carried
  `LastModifiedFrom`, `LastModifiedTo` and `Array.isArray(DocNo) === true`; the review header read
  "2 records · 2 awaiting approval"; the pre-approval read-back returned `job.status === 'needs_review'`
  with both rows `STAGED`; after Approve both rows were `PUSHED` and the job `done`;
  `vendor.reads() === 2` (two syncs, three documents with nested lines - no per-document fan-out).
- **Remarks:** "PUSHED" here means **handed to the slice-1 logging sink**, not delivered to a consumer.
  See the AC-13-14 verdict below and BL-133.

### Scenario 1b - the diff shows ONLY changed fields (AC-13-12) · **PASS**

- **Steps:** in sync 2, GRN-0001 changes `Description`, `NetTotal`, `FinalTotal` and the line `Qty`/
  `SubTotal`; everything else (supplier, currency, tax total, doc date, doc no, cancelled) is byte-identical.
- **Expected:** exactly **4** change rows - `description`, `net_total`, `total`, `lines` - and no row for
  any unchanged field, including `last_modified` (which changes on every re-fetch and is deliberately
  excluded as tautological noise).
- **Actual:** `expect(changeRows).toHaveCount(4)` passed, all four expected rows visible, and all eight
  asserted unchanged fields had **count 0**. Real before/after values rendered
  ("July delivery" → "July delivery (revised)"). GRN-0003 rendered the **New record** badge rather than
  a field-by-field diff against nothing.
- **Remarks:** the assertion is a **scoped count inside the record's own card**, so an over-rendering
  regression that dumps every canonical field fails here rather than passing on mere presence.

### Scenario 1c - approval is idempotent (AC-13-13) · **PASS**

- **Steps:** after a successful Approve, replay `POST /autocount/jobs/{id}/approve` at the boundary a
  real double-submit would reach (the UI itself disables the button once decided).
- **Expected:** HTTP 200, the ORIGINAL result returned, no second push, no error.
- **Actual:** 200 with `result.pushed === 2`; staged rows still exactly two, both `PUSHED`; and the
  activity log still carried exactly **one** `approve <jobId>` row before and after the replay - the
  replay ran no second push loop.
- **Remarks:** the activity count is the honest "pushed exactly once" evidence; a real approval always
  writes one masked activity row, an idempotent replay writes none.

### Scenario 2 - Discard closes the batch without pushing (AC-13-12) · **PASS**

- **Steps:** connect + Test + register company + **Sync now** (one GRN) → **Discard** → confirm.
- **Expected:** the job closes, the record is `DISCARDED` (never deleted - the raw payload stays for
  audit), nothing reaches the sink.
- **Actual:** job `done`, the single staged row `DISCARDED`, the review surface switched to the stated
  reason "This batch has already been reviewed."

### Responsive verification (AC-13-44) · **PASS for the slice-1 surfaces**

Asserted **in-spec**, not eyeballed: at each surface the viewport is set to **375×812** and **1280×900**,
the layout is allowed to settle, and the spec asserts (a) the anchor control is visible, (b) its box
starts inside the viewport, and (c) `documentElement.scrollWidth <= clientWidth` - i.e. no horizontal
**page** scroll, so wide content (a GRN's nested `lines` payload) scrolls inside its own block.

| Surface | 375px | 1280px |
|---|---|---|
| Company detail (Overview + Sync now) | PASS | PASS |
| Review batch - new records | PASS | PASS |
| Review batch - per-record diff | PASS | PASS |
| Company Runs tab | PASS | PASS |

The quarantine and reconciliation surfaces named in AC-13-44 **do not exist in slice 1** (slice 3) -
that portion is DEFERRED, see the verdict table.

---

## AC verdicts - slice 1

| AC | What | Evidence | Verdict |
|---|---|---|---|
| **AC-13-01** | `autocount` registers as an `erp` provider; 4 fields, no AppSecret, no company field; credentials Fernet-encrypted and never echoed; company DISCOVERED read-only | `test_provider_registers_as_an_erp_provider`, `test_provider_fields_have_no_appsecret_and_no_company`, `test_a_company_is_discovered_from_the_login_response`, `test_the_company_wire_shape_is_camel_case_and_leaks_no_credential`; E2E Scenario 1 steps 1-3 (four fields in the real form, Test echoes the discovered company, `AED_VSOFT` shown read-only) | **PASS** |
| **AC-13-02** | Several AutoCount companies per tenant; `erp` carved out of `uq_connection_tenant_type`; storage/email one-per-type unaffected | `test_uq_connection_tenant_type_no_longer_blocks_multiple_erp_rows`, `test_a_tenant_may_hold_several_active_autocount_connections`, `test_storage_still_allows_only_one_active_connection_per_type`, `test_email_still_allows_only_one_active_connection_per_type`, `test_a_second_company_for_the_same_tenant_is_accepted` | **PASS** (backend only - not exercised by E2E) |
| **AC-13-03** | Single-step `Server/Login`; bare `Authorization: <JWTToken>`; proactive age re-login; exactly one retry on `"Stream was not readable."` | `test_login_uses_jwt_token_not_the_guid_and_sends_it_bare`, `test_login_rejects_a_response_carrying_only_the_guid`, `test_token_is_proactively_refreshed_once_it_exceeds_max_age`, `test_a_fresh_token_is_not_re_logged_in`, `test_stream_not_readable_triggers_exactly_one_relogin_and_retry`, `test_the_retry_happens_at_most_once_then_the_error_propagates`, `test_a_non_expiry_relay_error_is_not_retried`; E2E: `vendor.logins() === 1` after Test | **PASS** |
| **AC-13-04** | Distinct, actionable failure messages; app-level vs relay-level shapes; success read from `Status == "Success"` | `test_test_reports_an_unreachable_host_distinctly`, `test_test_reports_a_timeout_distinctly_from_an_auth_rejection`, `test_test_names_the_appid_on_a_relay_error`, `test_status_fail_on_http_200_is_a_failure`, `test_relay_500_is_classified_separately_and_hides_the_stack_trace`, `test_empty_result_table_with_status_success_is_a_valid_empty_read` | **PASS** (E2E drives the success path only) |
| **AC-13-04a** | Malformed filter rejected before sending; returned window asserted | `test_a_non_list_identifier_filter_is_rejected_before_sending`, `test_read_rejects_a_bad_filter_without_making_a_request`, `test_window_assertion_fails_when_the_server_ignored_the_filter`, `test_window_assertion_is_day_granular_like_the_vendor_filter`, `test_window_assertion_fails_on_an_unparseable_timestamp`; E2E asserts the real request carried a **list** `DocNo` | **PASS** |
| **AC-13-05** | GRN delta honours the watermark; advances only on batch success | `test_the_fetch_sends_last_modified_from_and_to`, `test_a_missing_watermark_uses_a_bounded_lookback_never_everything`, `test_the_watermark_advances_on_a_clean_batch`, `test_the_watermark_holds_when_any_document_fails`, `test_the_watermark_holds_when_the_fetch_fails`, `test_a_later_sync_starts_from_the_watermark`; E2E asserts `LastModifiedFrom`/`To` on the live request and a job `result_json.watermarkAdvancedTo` after a clean batch | **PASS** |
| **AC-13-06** | Header + all lines in one call; lines nested | `test_header_and_all_lines_come_from_one_record`, `test_the_grn_detail_key_is_grdtl_not_grndtl`; E2E: 2 syncs → `vendor.reads() === 2` for 3 documents with nested `GRDTL` (no fan-out), and the diff renders `lines` as one nested field | **PASS** |
| **AC-13-07** | Raw payload retained beside the canonical record | `test_the_raw_payload_is_retained_with_the_canonical_record`, `test_the_canonical_record_round_trips_out_of_storage`; E2E Scenario 2 (discarded rows are marked, never deleted) | **PASS** |
| **AC-13-08** | Field mapping is data, not code | `test_adding_a_mapping_row_makes_a_udf_flow_with_no_code_change`, `test_removing_a_mapping_row_stops_a_field_flowing_with_no_code_change`, `test_seeded_mapping_rows_are_the_db_not_the_constant`, `test_udf_path_extraction_reads_a_per_customer_array` | **PASS** (backend). Remark: there is **no operator UI** for mapping rows in slice 1 - the "no code change" property is real but currently requires DB access. Not an AC requirement (`[BE]`), flagged for a future slice. |
| **AC-13-09** | Declarative coercion; unconvertible value ⇒ named per-field error | `test_string_booleans_become_real_bools`, `test_the_three_live_date_formats_all_parse`, `test_eight_dp_strings_and_mixed_numeric_types_both_become_decimal`, `test_decimal_conversion_does_not_go_through_float`, `test_an_unconvertible_value_produces_a_named_per_field_error`, `test_a_blank_value_is_none_not_an_error`; E2E scripts `"F"`, `120.00000000`, `2026/07/21` through the real mapper | **PASS** |
| **AC-13-10** | Strict all-or-nothing per document; failure names document, line, field | `test_a_failing_line_kills_only_its_own_document`, `test_a_line_level_error_names_the_document_the_line_and_the_field`, `test_a_failed_document_is_not_pushed_on_approval`, `test_a_mapping_row_pydantic_rejects_fails_one_document_not_the_batch` | **PASS** (backend only - E2E drives clean documents) |
| **AC-13-11** | `SCHEDULED_REVIEW` stops at `needs_review`; nothing pushed; never auto-pruned | `test_a_sync_stages_records_and_holds_for_review`, `test_a_needs_review_job_is_never_pruned`; **E2E explicit read-back before Approve: job `needs_review`, both rows `STAGED`, zero `PUSHED`** | **PASS** |
| **AC-13-12** | Per-record before → after, changed fields only; Approve pushes, Discard doesn't | `test_a_diff_reports_only_changed_fields`, `test_a_first_sight_record_is_marked_new_not_diffed_field_by_field`, `test_the_diff_hides_the_timestamp_that_changes_on_every_fetch`, `test_a_resynced_document_diffs_against_the_last_pushed_version`, `test_discard_closes_the_job_without_pushing`; FE unit `record-diff.test.tsx` (8) + `autocount-diff.test.ts` (20); **E2E Scenario 1b (scoped count of 4, eight unchanged fields absent) + Scenario 2 (Discard)** | **PASS** |
| **AC-13-13** | Approval idempotent; second call a no-op returning the original result | `test_approving_twice_pushes_exactly_once`, `test_the_second_approval_does_not_re_enter_the_sink`, `test_approving_a_job_that_is_not_in_review_is_a_clean_conflict`; **E2E Scenario 1c (replay → 200, same result, one activity row, two `PUSHED` rows)** | **PASS** |
| **AC-13-14** | Full read pipeline by real clicks; "the GRN appears in the consumer" | E2E Scenario 1 (whole journey by clicks) | **PARTIAL - see below** |
| **AC-13-15** | Suite green over the listed areas | Backend **1268 passed** (124 in the two autocount files, covering provider registration, auth + re-login, watermark advance/hold, mapping + coercion, per-document atomicity, `needs_review` gating, approval idempotency); frontend **820 passed** | **PASS** |

### AC-13-14 in detail - one half PASS, one half DEFERRED

> **Given** a configured AutoCount connection against the demo instance
> **When** the operator clicks Test → Sync now → reviews → Approve
> **Then** the GRN appears in the consumer with correct header and line values
> **And** the whole flow is driven by clicking, never by direct URL navigation.

| Clause | Verdict | Justification |
|---|---|---|
| "the whole flow is driven by clicking, never by direct URL navigation" | **PASS** | Scenario 1: one `goto` of `/signin`, every subsequent navigation a click. No deep links anywhere in the spec. |
| "clicks Test → Sync now → reviews → Approve" | **PASS** | All four are real clicks on the real surfaces; the pipeline runs the production code path end to end. |
| "against the demo instance" | **DEFERRED (environment)** | The demo AutoCount is IP-whitelisted to one workstation and unreachable from a test runner. The live facts (single-step login, `JWTToken` vs `Token`, discovered `AED_VSOFT`, `LastModifiedFrom`/`To` genuinely filtering, GRN carrying `LastModified`, the silently-ignored malformed filter) were confirmed by direct read-only probe on **2026-07-21** and are recorded in plan §4a; the E2E replays those exact shapes against a scripted vendor. **No automated re-verification against the live box is possible in this environment.** |
| "the GRN appears in the consumer with correct header and line values" | **DEFERRED → BL-133** | **NOT MET, by design.** The slice-1 sink is a deliberate tagged no-op (`sinks.LoggingSink`, `delivered=False` on every result, `sinkNote: "…no consumer is wired yet, so nothing left the ESB"`). A record reaching `PUSHED` means **handed to the sink**, not delivered. No consumer exists to assert against. |

**Overall AC-13-14: PARTIAL.** The operator-journey half is verified and green; the
consumer-delivery half is deferred to BL-133 (wire hop 2 to Sorento) and must not be read as passing.

---

## AC verdicts - cross-cutting

| AC | What | Evidence | Verdict |
|---|---|---|---|
| **AC-13-41** | Every query tenant- AND company-scoped | `test_another_tenants_company_is_invisible`, `test_staged_records_are_scoped_by_company_not_just_tenant`, `test_watermarks_are_per_company`, `test_every_module_table_carries_tenant_and_company`, `test_the_company_list_is_scoped_to_the_callers_tenant`, `test_a_non_autocount_job_cannot_be_steered_into_this_service`, `test_uninstall_wipes_only_this_tenants_rows`, `test_every_autocount_route_requires_authentication`; company scope for staged reads comes from the JOB payload, never client input | **PASS** |
| **AC-13-42** | AppId / Password / Token never in plaintext; stored payloads masked | `test_no_stored_row_or_result_ever_carries_a_credential`, `test_a_sync_writes_masked_activity_under_the_autocount_source`, `test_the_masker_treats_appid_as_a_credential`, `test_a_relay_detail_masks_an_echoed_credential_structurally`, `test_the_relay_raw_text_detail_branch_is_masked_and_capped`, `test_a_non_json_relay_body_detail_is_masked_and_capped`, `test_the_company_wire_shape_is_camel_case_and_leaks_no_credential`; E2E: secrets are never echoed back into the integrations form | **PASS** - with the standing caveat **BL-131** (the vendor's own JWT base64-decodes to the cleartext password; our masking covers it, but it permanently forbids any raw-request debug surface for this provider) |
| **AC-13-43** | A sync failure never breaks the triggering request | `test_a_handler_crash_never_propagates_to_the_caller`, `test_a_raising_sink_leaves_the_batch_re_approvable_not_stranded`, `test_a_fetch_fault_after_a_committed_abort_does_not_overwrite_it`, plus `record_activity`'s never-raises guard | **PASS in slice-1 scope.** The AC's literal subject is a *consumer-event-triggered write*, which does not exist until slice 4; the slice-1 analogue (handler + observability isolation) is verified. The write-path half is DEFERRED to slice 4. |
| **AC-13-44** | Review / quarantine / reconciliation usable at 375px and 1280px | E2E `assertResponsive` on company detail, review (both states) and the Runs tab - all PASS at both widths (table above) | **PARTIAL** - review surface **PASS**; **quarantine and reconciliation surfaces do not exist in slice 1** (slice 3), so those are **DEFERRED** to the slice-3 report. |
| **AC-13-45** | Module hygiene: own schema, per-module Alembic, `permissions.csv`, full bootstrap contract, `StorageKeyLocation`, module-tagged registry items | `test_module_implements_the_full_bootstrap_contract`, `test_module_tables_live_in_their_own_schema`, `test_module_permission_keys_are_namespaced_and_installed`, `test_every_migration_revision_id_fits_the_version_column`, `test_the_new_migration_chains_onto_the_baseline`, `test_the_sync_job_handler_is_registered`, `test_the_worker_module_imports_the_handler_module`; migrations `0001_autocount_baseline` / `0002_autocount_grn`; live DB shows `app_autocount` with 7 tables. `StorageKeyLocation`: **vacuously satisfied** - slice 1 stores no blob keys (no `*_key` column in `modules/autocount/models.py`) | **PASS** |
| **AC-13-46** | No silent caps - any bound is logged when hit; a truncated sync never reads as complete | `test_hitting_the_record_cap_fails_loudly` (asserts the log line), `test_a_full_page_is_never_returned_as_a_complete_result`, `test_a_truncated_fetch_fails_the_run_and_holds_the_watermark`, `test_a_vendor_error_is_not_flagged_as_a_truncation`, `test_the_retry_budget_is_per_call_not_global` | **PASS** |

---

## Verdict distribution

| Verdict | Count | ACs |
|---|---|---|
| **PASS** | 19 | AC-13-01, 02, 03, 04, 04a, 05, 06, 07, 08, 09, 10, 11, 12, 13, 15 (slice 1) · 41, 42, 45, 46 (cross-cutting) |
| **PARTIAL** | 3 | AC-13-14 (click path PASS / consumer delivery DEFERRED), AC-13-43 (slice-1 scope PASS / write path DEFERRED to slice 4), AC-13-44 (review PASS / quarantine + reconciliation DEFERRED to slice 3) |
| **FAIL** | 0 | - |
| **DEFERRED (whole AC)** | 0 | - |

Line-item total: **22** (19 PASS + 3 PARTIAL + 0 FAIL). Every PARTIAL names the deferred half and
where it lands (BL-133, slice 3, slice 4).

---

## Findings

**Finding #1 (environment, not product) - the dev server is not a valid E2E rig for this spec.**
Under `npm run dev`, `<nextjs-portal>` (the dev overlay) intercepts pointer events on the sidebar and
every section click times out. Against a fresh `npm run build && npm start` the same spec passes in
~11s. The house rule ("rebuild before E2E") is load-bearing here, not advisory.

**Finding #2 (spec robustness, fixed) - `Date.now()` alone is not a unique tenant slug.**
Two Playwright workers starting in the same millisecond minted identical slugs and collided on
`ix_tenants_slug`. Surfaced by `--repeat-each=2`. The spec now appends a random base-36 suffix.

**Finding #3 (spec correctness, fixed) - asserting the in-flight disabled state races the API.**
`expect(approveButton).toBeDisabled()` resolves the instant `isSubmitting` flips, i.e. *before* the
approve POST returns, so the read-back saw `needs_review` and looked like a product bug. It was not:
the DB showed `status=done, pushed=2` for that very job. The spec now waits for the **decided** state
("This batch has already been reviewed.").

**Finding #4 (environment, mitigated) - the first navigation after a backend/server restart can
exceed Playwright's 5s default.** One run failed at the sidebar → Integrations step immediately after
uvicorn was restarted mid-session (the backend had exited between runs); it passed on every run
before and after. The sidebar expectation now allows 15s for the cold first render. No product
assertion was relaxed.

**No product bugs were found by this pass.** The three findings above are all rig/spec issues, and all
are fixed in the committed spec. The slice-1 implementation behaved correctly on every path the
journey exercised, including the two paths most likely to hide a defect - the scoped diff
(only-changed-fields) and the idempotent approval claim.

### Standing risks carried forward (not defects of this slice)

- **BL-133** - the consumer sink is a no-op; `PUSHED` ≠ delivered. Until this closes, AC-13-14 cannot
  be fully claimed and no status in the UI distinguishes "handed off" from "delivered".
- **BL-131** - the vendor JWT embeds the cleartext password; forbids any raw-request debug surface.
- **BL-132** - `verifyTls` is read from config but never exposed by `fields()`, so a self-signed
  customer cannot connect and is told no reason why.

---

## Reproduction

```bash
# backend (:8001), seeded, eager Celery
uvicorn app.main:app --reload --port 8001

# frontend (:3001) - a FRESH prod build is required (Finding #1)
cd service_frontend && rm -rf .next && npm run build && npm start

# the journey
npx playwright test e2e/autocount.spec.ts --reporter=list
```

No external service, cloud credential or network access is needed: the spec starts and stops its own
scripted AutoCount on an ephemeral loopback port.

---

## Delta pass - `a3f4f42` and the log-fidelity fix

The body above was written against `544429c`. Three things landed after it, and the report is only a
Definition-of-Done artifact if it says what was verified **after** the last change, not before it.
This section covers only the delta; every claim above still holds unless contradicted here.

### Why the earlier AC-13-42/46 evidence was superseded

The original PASS for AC-13-42 (masked payload capture) and AC-13-46 (activity log carries the call)
was recorded when the log stored a *summary* of each call, not the call. `a3f4f42` replaced that with
the real masked request/response plus `status_code`, `latency_ms` and `trace_id`. The earlier evidence
therefore attested to a surface that no longer exists - it was not wrong, it was aimed at different
code. Re-verified below against what actually ships.

| AC | Verdict | Evidence (post-`a3f4f42`) |
|----|---------|---------------------------|
| AC-13-42 | **PASS** | `test_autocount_pipeline.py` masking cases + live smoke: the stored `request.headers.Authorization` reads `***`. This is load-bearing, not cosmetic - BL-131: the vendor JWT base64-decodes to the user's cleartext password, so an unmasked header **is** a credential leak. |
| AC-13-46 | **PASS** | Operator opens a run's activity entry and sees the actual outbound body, the vendor's reply, the HTTP code and the latency. This is what makes the "no records on second sync" class of question answerable without a debugger. |
| AC-13-04 | **PASS (re-verified)** | Extended: a `200` body with **no** `Status` key now logs `ok=False`. See below. |

### The log-fidelity defect this pass fixed

`client.py` had two success rules that disagreed on one input. `_unwrap` (which decides whether the
call *raises*) computes `str(body.get("Status") or "")` - an absent key collapses to `""`, which is
not `"success"`, so it raises. `_record_call` (which decides how the call is *badged*) skipped the
check entirely when the key was absent, and logged the leg green.

The consequence is specific and bad: the run fails, the operator opens the exact leg the failure
points at, and the log shows a green call with no error. The log is at its least trustworthy precisely
when it is being relied on. AutoCount's own error envelope - including the login one, which `login()`
reads only `Message` from - is that shape, so this was reachable, not theoretical.

`_record_call` now mirrors `_unwrap` verbatim, with a comment at both sites saying they must stay in
lockstep. A successful login returns a bare JSON *array*, so it never enters the dict branch and
cannot be mis-badged by the stricter rule - asserted explicitly rather than left as a reasoning step.

- **New test**: `test_a_200_body_with_no_status_key_is_logged_as_a_failure` - drives the real client
  through `MockTransport`, asserts the read raises, the leg logs `ok=False` carrying the vendor's
  `Message`, and the login leg beside it stays green.

### Surfaces added in `a3f4f42` with no prior AC row

Both came from operator review of the running UI, so neither existed when the UAC was written. Recorded
here against the AC they serve rather than inventing new ids.

| Surface | Serves | Verdict | Evidence |
|---------|--------|---------|----------|
| **Entities as its own tab** (split out of Overview) | AC-13-40 (operator can see per-entity state) | **PASS** | E2E journey navigates via the tab. Driven by the operator's own point that the entity count only grows - a list nested in Overview does not survive that. Fixed a real bug found while building it: `reload()` flipped `isLoading`, unmounting `ResourceForm` and silently throwing the operator back to Overview; guarded with `isLoading && !detail`. |
| **`initialLookbackDays` editable per company** | AC-13-16 (first-run window is operator-controlled) | **PASS** | `test_the_lookback_patch_persists_and_rejects_nonsense`. Closes a genuine design gap surfaced by the operator's "why no records on the second sync": the second sync was *correct* (watermark past all data), but a hardcoded 30-day first window made the back-catalogue permanently unreachable with no way to widen it. |

### Suite state at the end of this pass

```
tests/test_autocount_pipeline.py .......... 105 passed
```

### Known-imperfect, deliberately not fixed in slice 1

- `PATCH` with `initialLookbackDays` absent returns `200` having changed nothing. Harmless, but a
  silent no-op is a poor contract; worth an explicit shape in slice 2.
- "Edit first-run window" is offered on superseded rows, where it has no effect.
- `provider.test()` buffers the HTTP leg and discards it, so a connection test that fails is thinner to
  diagnose than a sync that fails. Backlogged.
