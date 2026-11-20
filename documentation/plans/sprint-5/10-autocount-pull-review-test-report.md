# 10 - AutoCount human-invoked pull (list price, stock balance, snapshot gateway) - Test Execution Report

Keyed to `10-autocount-pull-review-acceptance-criteria.md` (AC-10-01..88 plus AC-10-09b, 89 ids
total). Plan: `10-autocount-pull-review.md`. Written by the docs-only tester per AC-10-57, from the
evidence already committed on branch `sprint-5/10-autocount-pull-review` - no server was started
and no test suite was re-run to produce this report; every verdict below cites either a committed
`agent-browser`/curl/psql evidence file or a named pytest/vitest file, and states plainly which.

## Environment

- Worktree `.claude/worktrees/s40`, branch `sprint-5/10-autocount-pull-review`, HEAD `e873920b`
  (this report is written at, but does not move, this HEAD).
- Lane: backend `:8009` (uvicorn, `app.main:app`), frontend `:3009` (`npx next start -p 3009` after
  `rm -rf .next && npm run build`), DB `foundryx_service_s40` (native Postgres). Module
  `autocount` 0.10.0, module Alembic head `0021_autocount_pull_gateway`.
- Evidence dirs, all under `documentation/plans/sprint-5/10-evidence/`: `s1-live-replay/`,
  `lookups/`, `mapping-clamp/`, `delivery/`, `pull-setup/`, `pull-stock/`, `flip-push/`,
  `pull-keys-snapshots/`, `combine/` (+ `PROBE.md`), `live-replay/` (Run 1 db1+db2, Run 2 db2 with
  per-connection sizing). Fixtures: `documentation/plans/sprint-5/10-fixtures/README.md`. Cross-repo
  message: `documentation/plans/sprint-5/10-evidence/peer-message-a6.md`.
- Dates: build ran 2026-09-19 through 2026-09-20 (UTC) across multiple tester/coder rounds on the
  same lane; every evidence file states its own run date and the exact HEAD it verified.
- Coordinator-recorded facts cited below (not independently re-derived by this report): the S6
  security-pass verdict and the two Sonnet-quota handoff documents
  (`.claude/handoffs/20260920T112000Z-plan10-sonnet-quota-dead-wips-parked-opus-fix-coder.md`,
  `.claude/handoffs/20260920T104500Z-plan10-s6-replay-done-three-findings-confirm2-security-in-flight.md`).

## Summary

Of 89 AC ids: **87 PASS** (of which 9 carry a recorded, code-fixed defect history within their own
row - see "Defects found and fixed" below for the exact fix commits and re-verification status;
several others are qualified "suite only" or "suite + live-consistent" where this docs-only pass
could not exercise the live edge case itself), **1 PARTIAL** (AC-10-87, the optional `progress`
hint - genuinely not found in code at the final HEAD, a discrepancy against `BL-SS-236`'s own text,
recorded honestly rather than reconciled either way), **1 DEFERRED** (AC-10-56, the two cross-repo
joint live runs - owner STOP). No id has zero evidence. Backend/frontend suite totals are recorded
**as reported by the confirm-4 coder at HEAD `9e18400d`** (one commit before this report's HEAD,
which only adds the db2 live-replay Run 2 evidence commit, no application code) - **gate re-run
pending**, not independently re-executed by this docs-only pass:

- `tests/test_s10_*.py` (backend): **534 passed, 0 failed**.
- `tests/test_autocount_*.py` + `tests/test_seed_autocount_shape_source.py` (backend, full glob
  including this plan's diff against the pre-existing suite): **1444 passed, 0 failed**.
- `tests/test_url_guard.py`: green.
- `npx vitest run` (frontend, full suite): **3082 passed, 2 failed** - both pre-existing and
  unrelated to this plan (`BL-SS-223` `services/autocount-service.test.ts`'s `normalizeEtlTask`
  overlay throwing on a stub task with no `sourceConfig`; `BL-SS-224`
  `components/ui/pressed-class.inventory.test.ts`, two un-allowlisted webchat-panel buttons).
- `npm run build` (`rm -rf .next && npm run build`): clean.
- `npx eslint` on touched files: clean.

## Suites (as reported, gate re-run pending)

| Suite | Result | HEAD | Source |
|---|---|---|---|
| `tests/test_s10_*.py` | 534 passed / 0 failed | `9e18400d` | confirm-4 coder report |
| `tests/test_autocount_*.py` + `test_seed_autocount_shape_source.py` | 1444 passed / 0 failed | `9e18400d` | confirm-4 coder report |
| `tests/test_url_guard.py` | green | `9e18400d` | confirm-4 coder report |
| `npx vitest run` (full) | 3082 passed / 2 failed (BL-SS-223, BL-SS-224, both pre-existing) | `9e18400d` | confirm-4 coder report |
| `npm run build` | clean | `9e18400d` | confirm-4 coder report |
| `npx eslint` (touched files) | clean | `9e18400d` | confirm-4 coder report |

A dedicated gate-run tester (throwaway worktree `s40-gate`, out of scope for this docs-only pass)
re-confirms these counts independently before merge.

## Results by AC id

Tag legend: `[BE]` backend pytest, `[FE]` frontend vitest, `[E2E]` recorded agent-browser run,
`[T]` tester-owned proof (mutation/live replay/docs). "Suite-reported" = covered by a named test
file per the confirm-4 report above, not independently re-run by this pass; "Live" = confirmed
against the real `:8009`/`:8009+:3009` lane with real network calls to the AutoCount wrapper.

### Group A - list price by enrichment

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-10-01 | BE | PASS | Suite-reported: `test_s10_lookups_validate.py`, `test_s10_review1_lookup_path_validation.py`. Live: `s1-live-replay/README.md` negative probes (`round2-negative-probes.txt`, `round3-corrections.txt`) confirm the exact 422s: duplicate/colliding alias, `>5` lookups, a `local` naming a non-existent column, an escaping `path` (`/../db2/itembypage`) rejected with zero outbound calls. |
| AC-10-02 | BE | PASS | Suite-reported: `test_s10_http_lookups.py`. Live: `s1-live-replay/README.md` Part B - the ItemUOM lookup merges `BaseUOMPrice` onto every row before hash/mapping, multi-hop confirmed structurally by the stock preset's `item -> ItemBaseUOM` then `(ItemCode, ItemBaseUOM)` chained lookup (`combine/README.md`, `live-replay/README.md`). |
| AC-10-03 | BE | PASS | Suite-reported: `test_s10_http_lookups.py` (miss-warning mechanism). Live: not exercised (db1's real data enriches 100%, `s1-live-replay/README.md` "AC-10-03" section, honestly reported as not exercised) - the ENRICH-endpoint-failure half is corroborated live by `live-replay/README.md` Run 1 db2 `ENRICH_FAILED` (the `item` lookup's own endpoint timing out fails the whole build, not a per-row miss). |
| AC-10-04 | BE | PASS | Live: `s1-live-replay/ac10-04-product-task-save-response.json` - a first clean product save on db1 seeds the ItemUOM lookup and the `BaseUOMPrice -> list_price` clamp row verbatim per the AC. |
| AC-10-05 | BE | PASS | Live: `s1-live-replay/ac10-05-preview-columns-lookups.json` - `preview-columns` returns real remote columns, `preview` returns `lookups: [{"alias":"uom","matched":50,"missed":0}]` plus `BaseUOMPrice` in `columns`/`rows`. BL-SS-222 records the sample-count caveat (50-row sample, page-1-only lookup probe) for the FE label to honour. |
| AC-10-06 | BE | PASS | Suite-reported: `test_s10_http_lookups.py` (stubbed two-run price-change test). Consistent with the live 3-consecutive-stable-run replay in `s1-live-replay/README.md` (0/0/0 each run once the enriched value stopped changing). |
| AC-10-07 | BE | PASS | Live: `s1-live-replay/measure-run1-counts.txt` / `measure-round2-distinct-counts.txt` - 5,129/11,840 delivered `list_price == "0"/"0.0"` (JSON string, never omitted for a matched row), re-measured identically post-refactor (byte-identical). |
| AC-10-08 | BE | PASS | Code: `modules/autocount/http_source/client.py:40`, `USER_AGENT = "Foundryx-AutoCount-ESB/0.10.0"`. Live corroboration: every one of the dozens of live GET calls in `s1-live-replay/README.md` answered 200 (the wrapper 403s a default python-urllib UA per plan-08's own finding). Suite-reported: `test_s10_http_client_user_agent.py`. |
| AC-10-09 | FE | PASS (defect found and fixed) | `lookups/README.md` run 1: full editor journey PASS at both widths, one defect found (step 10: a false-positive "already a source column" inline error on lookup #1's own field alias after a second lookup's Test, save unaffected). `lookups/README.md` run 2 (HEAD `7618bb33`): **defect confirmed fixed** (fix commit `81eee16e`, collision check now derives from the backend-echoed `preview.task.sourceConfig.lookups`). A separate save-time gap the same investigation found (probe 4's field-alias self-collision hole) was closed by fix commit `4c5ce70d`, independently re-probed via curl in the same README's "Corrections" section. |
| AC-10-09b | E2E | PASS | `lookups/README.md` - full real-click journey at 1280px and 375px: pre-filled lookup visible/numbered, Add lookup, path + Test, join pair 1 (Exact) + join pair 2 (Ignore case and spaces), bring in `Rate` as `BaseUOMRate`, combined Test shows matched/missed, Save, Mapping tab source picker offers `BaseUOMRate`. |
| AC-10-59 | BE | PASS | Live: `mapping-clamp/README.md` - the `BaseUOMPrice -> list_price` row carries `if(number(value) <= 0, 0, number(value))`, per-row simulator `-1 -> 0`, whole-record "Simulate mapping" `-1 -> 0.0`. Wire-pinned live in `s1-live-replay`: 121/121 negative source prices clamped, delivered as `"0.0"`. |
| AC-10-60 | BE | PASS | Live: `s1-live-replay/README.md` - `source_ref`/`code` already trimmed (20 whitespace `ItemCode`s), `row_hash` unchanged pre/post the round-1b refactor, and `combine/PROBE.md`/`combine/README.md` confirm `'MBS '`/`'MBS'` fold to one group. |
| AC-10-61 | FE | PASS | `mapping-clamp/README.md` - `list_price` row reads `Custom` with the formula visible inline, both the per-row Testing tab and the whole-record simulator agree `-1 -> 0`. |
| AC-10-71 | BE | PASS | Live: `s1-live-replay` (11,840/11,840 db1 rows carry `AED_SORENTO:<ItemCode>`), `live-replay/README.md` (db2/Mocha rows carry the company's own prefix on the same `<ItemCode>` key pattern). Suite-reported: `test_s10_product_preset.py`/`test_s10_s3_product_code_wins.py` pin `key_fields == ("ItemCode",)` and the no-DB-variant rule. |
| AC-10-73 | BE | PASS | Live: `s1-live-replay/ac10-04-59-73-74-mapping-rows.json` - the `Description -> description` row carries the exact join formula `trim(if(default(Desc2, "") != "", concat(Description, " ", Desc2), Description))`; measured 2,768 live rows preserve an internal double space (plan estimated ~2,786, close - live-data drift across the ~1-day gap, not a defect). |
| AC-10-74 | BE/FE | PASS | Live: `s1-live-replay/ac10-04-59-73-74-mapping-rows.json` - `BaseUOM -> uom_code` present but `isEnabled: false` on a freshly-seeded task. |
| AC-10-75 | BE | PASS, genuinely live-proven (unprompted) | `s1-live-replay/README.md` - the real db1 wrapper timed out on page 3 twice DURING this replay (not engineered), producing the exact designed `NOTE` message ("timed out twice ... halving to 500 and restarting from page 1"), then completed cleanly as 24 pages of 500. Reproduced independently a second time in the same file's post-review re-check, and a third/fourth time on db2 in `live-replay/README.md` Run 2 (3 separate halvings, all recovered to `ready`). |

### Group B - delivery mode

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-10-10 | BE | PASS | Suite-reported: `test_s10_s3_delivery_mode.py` (column default, backfill). |
| AC-10-11 | BE | PASS | Live: `delivery/README.md` run 1 - the real backend correctly 422'd a Pull save because the lane company had no `sorentoCompanyCode` (confirms the AC-11 gate is real, not a mock); run 2 - after setting a real Sorento company code via the UI, the same save succeeded (`PUT .../delivery-mode` 200). Suite-reported: `test_s10_s3_delivery_mode.py`. |
| AC-10-12 | BE | PASS | Suite-reported: `test_s10_s3_delivery_mode.py` (spy: `auto_push` called zero times in pull mode). |
| AC-10-13 | BE | PASS | Suite-reported: `test_s10_s3_delivery_mode.py` (sweep filters `delivery_mode == 'push'`, activate arms no schedule in pull). |
| AC-10-14 | BE | PASS | Live: `flip-push/README.md` - Product flipped `pull -> push`, Incremental/Reconcile cadence returned with SAVED values unchanged, Runs tab showed the schedule armed (`Next 20 Sept 2026, 21:04` / `Next 21 Sept 2026, 10:00`), no re-Test/re-mapping required. Suite-reported: `test_s10_s3_delivery_mode.py` round-trip test. |
| AC-10-15 | BE | PASS | Live: `combine/README.md` step 11, `pull-stock/README.md` step 4 - the Stock balance entity's Schedule tab renders only a read-only "Pull on request" `StatusBadge`, no toggle, confirming the push gate is shut below contract 2.5. Suite-reported: `test_s10_s5b_registration.py`, `test_s10_s3_product_contract_gate.py` (generalised gate). |
| AC-10-16 | FE | PASS (defect found and fixed) | `delivery/README.md` run 1: toggle show/hide and Push-restores-values PASS; dirty-guard AlertDialog FAIL (Back/breadcrumb navigation silently discarded an unsaved toggle). Run 2 (HEAD `7618bb33`): **defect confirmed fixed** on BOTH Back and the breadcrumb (fix commit `4961b493`), revert-disarms and save-disarms both hold, reproduced at both 1280px and 375px. `pull-setup/README.md` and `combine/README.md` both independently reconfirm PASS at the current HEAD. |
| AC-10-17 | FE | PASS | `delivery/README.md` run 2: Entities-list Delivery `StatusBadge` confirmed live (Push AND Pull states) against the real backend. `pull-setup/README.md` step 3: the exact Pull-mode banner copy ("Activating lets the consumer request this extract.") observed live on a genuinely `draft`+`pull` task (Stock balance on the Mocha company). `combine/README.md` step 12: Delivery column badges (`Push`/`Pull on request`) confirmed at both widths. |

### Group C - snapshot store and build job

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-10-18 | BE | PASS | Suite-reported: `test_s10_s3_snapshot_store.py`, `test_s10_s3_review1_migration_indexes.py` (module Alembic `0020_autocount_pull_snapshot`, both tables tenant+company scoped, `UTCDateTime`/`JSON(none_as_null=True)`). |
| AC-10-19 | BE | PASS | Suite-reported: `test_s10_s3_snapshot_store.py`, `test_s10_s3_review1_dead_gates.py` (immutability on `ready`, second-write mutation test). |
| AC-10-20 | BE | PASS | Suite-reported: `test_s10_s3_snapshot_build_job.py` (job registration, `mode=reconcile`/`persist_hashes=False`, one-commit stamp). Live: every build in `live-replay/README.md`/`pull-setup/README.md`/`pull-stock/README.md` reached `ready` in one commit with `record_count`/`complete`/`content_hash`/`extracted_at`/`expires_at` all populated together. |
| AC-10-21 | BE | PASS | Live: `live-replay/README.md` - a pull run writes no `ac_staged_record`, one `ac_sync_run` row `mode='snapshot'` with `rows_scanned`/`added_count` populated, visible on the Runs tab equivalent (`ac_sync_run` rows cited by job id throughout). |
| AC-10-22 | BE | PASS | Suite-reported: `test_s10_s3_review1_complete.py`, `test_s10_s3_pull_build_error_codes.py`. Live corroboration: `live-replay/README.md` Run 1 db2 genuinely produced `SOURCE_PAGE_FAILED` (product) and `ENRICH_FAILED` (stock) with zero readable rows, both real, not stubbed. |
| AC-10-23 | BE | PASS | Suite-reported (fixed-fixture `content_hash` test in the S3 suite). Live: `live-replay/README.md` - a SECOND independent build of the same db1 product snapshot (operator route then gateway route) produced a **byte-identical `contentHash`**; `pull-setup/README.md` reproduces the identical hash again on a THIRD independent build days later. |
| AC-10-24 | BE | PASS | Suite-reported: `test_s10_s3_review1_complete.py`. Live: every `ready` header cites `complete: true` with `sourcePageSize` matching the actually-used page size (500 after a halving on db1, 1000/150/300 variants on db2). |
| AC-10-25 | BE | PASS | Suite-reported: `test_s10_s34_review2_failed_build_cooldown.py` and the S3/S34 prune tests (not independently re-run live - TTL is 24h, out of this pass's time budget). Live: `live-replay/README.md` confirms `expiresAt = createdAt + 24h` exactly on two real snapshots. |
| AC-10-26 | BE | PASS | Suite-reported: `test_s10_s3_review1_one_building.py`, `test_s10_s34_review2_failed_build_cooldown.py`, `test_s10_s3_review1_heartbeat.py`. Live: `live-replay/cooldown-reattach-transcripts.txt` and `run2-cooldown-reattach-transcript.txt` - re-attach returns the SAME `snapshotId` in 15-34ms while `building`; cooldown answers 429 with `Retry-After`; `pull-keys-snapshots/README.md` Run 4 independently reproduces re-attach-during-grace-window on the KEY side (a different mechanism, same "alive window" principle). |
| AC-10-62 | BE | PASS | Live: `s1-live-replay`/`10-fixtures/products-header-ready.json`/`pull-keys-snapshots/README.md` Run 2 - a product snapshot with 10 `excludedRows` (`mapping_failed`, blank-`Description` items) still reached `ready`, `complete: true`, `record_count` counting delivered rows only. |
| AC-10-63 | BE | PASS | Live: `live-replay/README.md` db1 product header - `zeroListPriceCount 5129`, `negativeListPriceCount 121`, `enrichMissCount 0`, with `negativeListPriceCount <= zeroListPriceCount` holding exactly (121 <= 5129). Suite-reported: `test_s10_s5b_header_metadata.py`-class fixture test for the 5-row edge case. |

### Group D - pull gateway, API keys, permissions

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-10-27 | BE | PASS | Suite-reported: `test_s10_s3_review1_migration_indexes.py`, `test_s10_s4_pull_key_service.py` (module Alembic `0021_autocount_pull_gateway`, no payload/PII columns). |
| AC-10-28 | BE | PASS | Live: `pull-setup/README.md` step 5, `pull-keys-snapshots/README.md` - plaintext key (`fxa_live_...`) shown exactly once, `last_used_at` stamped on resolve (`pull-keys-snapshots/README.md` Run 4's grace-window probe). Suite-reported: `test_s10_s4_pull_key_service.py`, `test_s10_s4_sec_key_issue_validation.py`. |
| AC-10-29 | BE | PASS | Live: `live-replay/README.md` - `POST /api/v1/autocount/snapshots`, `GET .../{id}`, `GET .../{id}/rows` all exercised against the real gateway on both books. Suite-reported: `test_s10_s4_gateway_build.py`, `test_s10_s4_gateway_reads.py`. |
| AC-10-30 | BE | PASS | Suite-reported: `test_s10_s4_gateway_auth_and_throttle.py`, `test_s10_s4_sec_ambiguous_company.py` (cross-tenant uniform 404, key-derived tenancy, case-insensitive/trimmed company-code resolution). Not independently re-run live cross-tenant this pass (would need a second tenant in the lane). |
| AC-10-31 | BE | PASS | Live: `live-replay/README.md` (`INVALID_API_KEY` 401, `UNKNOWN_SNAPSHOT` 404, `TOO_MANY_BUILDS` 429 with `Retry-After`), `flip-push/README.md` (`PUSH_ACTIVE` 409, two independent transcripts). `SNAPSHOT_EXPIRED` (410) not live-timed (24h TTL) - suite-reported: `test_s10_s4_gateway_errors_and_audit.py`. |
| AC-10-32 | BE | PASS | Live: exact header shape confirmed on every `ready`/`building`/`failed` header across `live-replay/`, `pull-setup/`, `pull-stock/`, `pull-keys-snapshots/` evidence, including the product-only and stock-only extra fields. |
| AC-10-33 | BE | PASS | Live: `live-replay/gateway-row-samples.json`, `gateway-db2-product-rows-run2.json` - `page`/`pageSize`/`totalPages` correct, stable, rows served exactly as stored. |
| AC-10-34 | BE | PASS (suite only) | `live-replay/README.md` explicitly states this was NOT independently re-verified live this session (time budget); suite-reported: `test_s10_s4_gateway_errors_and_audit.py`. |
| AC-10-35 | BE | PASS (suite only) | Suite-reported: `test_s10_s4_gateway_auth_and_throttle.py`, `test_s10_s4_sec_key_throttle_and_audit_retention.py`. Not live-flooded this pass. |
| AC-10-36 | BE | PASS | Live: the `autocount.pull.read`/`autocount.pull.manage`-gated sidebar "Pull" menu entry rendered for `demo@example.com` on the `default` tenant throughout every evidence run (an existing, pre-plan-10 tenant), confirming the grant sweep reached it. Suite-reported: `test_s10_s3_permissions_grant_sweep.py`. |
| AC-10-37 | BE | PASS | Live: every operator route (`/autocount/pull/keys`, `/autocount/pull/snapshots` + sub-routes) exercised via the UI and curl throughout `pull-setup/`, `pull-keys-snapshots/`, `live-replay/`. |
| AC-10-38 | FE | PASS (multi-round defect history, final state PASS) | `pull-keys-snapshots/README.md` Run 1 (S2 mock phase, `AC-10-48` fixture state): FAIL - Issue key does not persist, no Revoke affordance at all, Build-snapshot company picker empty (mock-bound surface, as briefed). Run 2 (phase-2 swap landed): Issue key confirmed PASS (run-1 finding retracted as a test-script bug); Revoke confirmed a genuine, newly-found FAIL (no `ActionMenu` column wired). Run 3: Revoke reachable (gap fixed) but 404s (list still read the Phase-1 mock while the mutation targeted the real backend - a read/write mismatch, root-caused, not a backend bug). Run 4 (HEAD `17dc2c61`, phase-2 swap fully landed): **PASS, fully, both viewports** - Issue key -> plaintext-once -> Revoke -> grace countdown -> commit -> `401 INVALID_API_KEY` on the revoked key, 6 keys revoked cleanly with no defects. |
| AC-10-47 | BE | PASS (suite + design review) | Suite-reported: tenant-scoped repository tests per method + cross-tenant read test per gateway route (S3/S4 suites). Reinforced by the S6 security-pass verdict below (no unscoped `get_by_id` found). |
| AC-10-64 | BE | PASS | Suite-reported: `test_s10_s34_review2_failed_codes_constant.py` (pins the exact set: `SOURCE_PAGE_FAILED`, `ENRICH_FAILED`, `ROW_LIMIT`, `EMPTY_EXTRACT`, `BUILD_ABANDONED`, `COMBINE_RULE_FAILED`). Live: `live-replay/README.md` Run 1 genuinely produced two of the six (`SOURCE_PAGE_FAILED`, `ENRICH_FAILED`) from a real db2 timeout, not a stub. |

### Group E - stock balance entity

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-10-39 | BE | PASS | Suite-reported: `test_s10_s5b_registration.py` (entity/canonical registration, D33 - extends `CanonicalRecord`, not `CanonicalMaster`, no `sinks_sorento` path). Live: `combine/README.md`, `pull-stock/README.md` confirm the entity is reachable and pull-only. |
| AC-10-40 | BE | PASS | Live: `pull-stock/README.md` step 1, `combine/README.md` step 2 - preset path `/itembatchbalqtybypage`, no watermark, exactly the two lookups (`ItemBaseUOM`/`ItemDescription` from `/itembypage`, `UomRate` from `/itemuombypage`) pre-filled and confirmed live. |
| AC-10-41 | BE | PASS | Live: `combine/README.md` step 2 - every combine field (computed `item_code`/`location_code`/`base_qty`, `uom_rate` require rule, group-by, carry, `qty` measure, `half_up 0dp` round, `zero`/`negative` drop rules) matches the preset verbatim. Backend proof: `combine/PROBE.md` (`test_s10_s5b_live_numbers.py` replayed against the FULL recorded db1 capture). |
| AC-10-42 | BE | PASS | Live: `combine/PROBE.md` / `live-replay/README.md` - 56,422 `zero`-dropped, 42 `negative`-dropped (all listed), 12,133 delivered, exactly the two-drop-rule mechanism, no location/item filter (R7). Suite-reported: `test_s10_s5a_combine_apply.py`. |
| AC-10-43 | BE | PASS | Live: `combine/PROBE.md`/`live-replay/README.md` - `roundedCount 0` (`fractionalPairs 0`) on both books' real captures. |
| AC-10-44 | BE | PASS (suite-reported edge case + live-consistent) | Live captures this pass all show `excludedCount: 0` (the R6 "amended" measured fact per AC-10-84), so the `complete: true`-despite-exclusions edge itself was not exercised live; suite-reported: `test_s10_s5b_header_metadata.py`. |
| AC-10-45 | BE | PASS | Live: `live-replay/gateway-row-samples.json`/`gateway-db2-stock-rows-run2.json` - stock row shape `{source_ref, item_code, item_description, location_code, uom_code, qty}` confirmed exactly; `complete: true` on both books' full-set builds. |
| AC-10-46 | BE | PASS (suite only) | Suite-reported: EMPTY_EXTRACT zero-row guard test (S3/S5b suites). Not live-triggered this pass (would require a genuine 0-row rebuild against a non-zero prior snapshot). |
| AC-10-65 | BE | PASS (suite + live-consistent) | Suite-reported fixture test (product exclusions never block, `complete: true`, no blocking flag). Live: `pull-keys-snapshots/README.md` Run 2 - a product snapshot with 10 exclusions read `ready`/`complete: true` with no blocking flag, consistent with the rule. |
| AC-10-66 | BE | PASS (suite + live-consistent) | Suite-reported 3-of-which-2-nonzero fixture test. Live: every captured header this pass shows `excludedNonzeroCount: 0` (clean data), the nonzero counting path itself not exercised live. |
| AC-10-68 | BE | PASS | Live: `combine/PROBE.md`/`s1-live-replay` - 12,133 rows over 75 locations delivered with NO location filter applied (R7 confirmed structurally: the reducer's own drop rules are quantity-only). Suite-reported: `test_s10_s5b_reducer_behaviour.py`. |
| AC-10-69 | BE/FE | PASS (suite-reported; a coupling note recorded, not a defect on this AC) | Suite-reported: `test_s10_s6_logging_sink_pull.py`, `test_s10_s3_product_contract_gate.py`. Not independently live-pushed against a real sub-2.4 Sorento contract this pass. `live-replay/README.md` Finding 0 records a related design coupling (`sinkImpl=logging` clears `sorento_company_code`, which the pull path also needs) - flagged for the plan owner, not a failure of this AC's own gate logic. |
| AC-10-70 | BE | PASS (suite only) | Suite-reported fixture test (`warnings: ["ref_mismatch"]` counted, outcome stays `updated`/delivered). Not exercised live this pass (no real Sorento sink target was ever pushed to). |
| AC-10-72 | BE | PASS (suite only) | Suite-reported: `test_s10_s3_product_delete_codes_wiring.py` (body-shape + multi-key negative). Not exercised live (no delete batch was pushed to a real consumer this pass). |
| AC-10-76 | BE | PASS | Suite-reported: `test_s10_s5a_combine_validate.py` (the full 422 catalogue: unknown column/alias, forward reference, alias clash, empty `groupBy`, a `measure` that does not name a known pre-group column, a numeric op over a non-numeric sample, a non-boolean `require`/`drop`). Live: `combine/README.md`'s Save/persisted-state journey exercises the happy path of this save gate against the real preset, round-tripping cleanly. |
| AC-10-77 | BE | PASS | Suite-reported: `test_s10_s5a_combine_apply.py`, `test_s10_s5a_review3_bool_and_save_gate.py` (D25 - fail-closed `to_bool_strict` for `require`/`drop`). Live: `combine/README.md` funnel and `combine/PROBE.md` (the `uom_rate` require rule evaluated over the full 68,612-row db1 capture with 0 exclusions in this exact recording). |
| AC-10-78 | BE | PASS | Suite-reported: `test_s10_s5a_combine_apply.py`. Live: `combine/README.md` funnel and the combined-rows preview grid showing carried `ItemDescription`/`ItemBaseUOM` columns and the `qty` measure alias, first-appearance group ordering implied by the deterministic, byte-identical repeat builds in `live-replay/README.md`. |
| AC-10-79 | BE | PASS | Suite-reported: `test_s10_s5a_combine_apply.py`, `test_s10_s5a_review4_combine.py` (rounding + drop-rule mechanics). Live: `combine/README.md` funnel (`negative: 16 dropped` listed, `zero: 29 dropped` not listed after the toggle), `combine/PROBE.md` (`roundedCount 0` on the full real capture). |
| AC-10-80 | BE | PASS | Live: `combine/README.md` step 3 - the read-only "Key columns" pill row reads `item_code, location_code`, taken from the combine step's `groupBy`, never typed separately. Suite-reported: `test_s10_s5a_key_fields_groupby.py`. |
| AC-10-81 | BE | PASS | Suite-reported: `test_s10_s5b_header_metadata.py` (pins the serialised stock header against Appendix A3's agreed example byte for byte). Live: `live-replay/README.md` db1 AND db2 stock headers both show `zeroPairs`/`negativePairs`/`negativePairList`/`fractionalPairs`/`excludedNonzeroCount` exactly matching the generic `dropped["zero"].count` / `dropped["negative"].count` / `roundedCount` mapping. |
| AC-10-82 | FE | PASS (defect found, fixed) | `combine/README.md` - Combine rows section renders below Lookups with every named field type, shell primitives only, funnel renders after Test. Defect 1 (formula-builder rejects the pre-filled drop-rule formulas referencing `qty`) does not block the AC's own acceptance text; **fixed** at `b1593264` (`combine-editor.tsx`, unit-tested), not independently browser-re-verified after the fix. |
| AC-10-83 | E2E | PASS | `combine/README.md` steps 4-8, both widths: pre-filled rules visible -> opened the `negative` rule's control (toggle, since "Edit formula" was blocked by Defect 1 at capture time) -> toggled "list dropped rows" off -> Test -> funnel showed the dropped count with no listed rows -> toggled back on (undo) -> Save -> reload via real sidebar clicks -> persisted correctly. |
| AC-10-84 | T | PASS | `combine/PROBE.md` - `test_s10_s5b_live_numbers.py` replayed against the FULL recorded db1 capture (93 page files, 68,612 raw rows): 68,597 groups -> 56,422 zero + 42 negative + 12,133 delivered, `roundedCount 0`, `excludedCount 0` (the amended figure per R6, matching the plan's own updated UAC text). Independently reproduced live against the real wrapper in `combine/README.md` step 5 ("Paged - 68,612 total"). |
| AC-10-85 | BE/FE | PASS (built and fixed mid-pass, live-verified) | `live-replay/README.md` Run 1: **NOT IMPLEMENTED** at that HEAD - `AutoCountProvider.fields()` had no `pageSize`/`requestTimeoutSeconds`, db2 could not complete ANY pull build as a direct result (Finding 1). Fixed across `6c150e73`/`8b2d0bc4` (provider fields, one shared connection-sizing helper for BOTH preview and the real-run path, measured-latency Test message). Run 2 (same file): **PASS, fully live-verified** - `PATCH .../connections/{id}` accepts `pageSize`/`requestTimeoutSeconds`, `POST .../test` reports "Reached in 0.55 s, 21 locations.", both db2 entities build `ready` end to end at the raised ceiling, deterministically (byte-identical `contentHash` across independent builds). `pull-setup/README.md` Finding C independently confirms the fields are present and correctly gated on the lane's own db1 connection (minor UX gap: blank with no default placeholder, needs backlog id, not a hard fail). |
| AC-10-86 | BE | PASS | Live: `live-replay/README.md` Run 2 - two db2 builds ran ~20m19s and ~20m25-31s with no short global timeout hit, `sourcePageSize` correctly stamped (150 after one halving, 300 unchanged) on the header after completion. `s1-live-replay/README.md`'s ~9-minute db1 builds are a second, independent long-running-build data point. |
| AC-10-87 | BE | **PARTIAL - not implemented in code at this HEAD, contradicting the backlog's own description** | `live-replay/README.md` Run 1 explicitly checked and found no `progress` key on ANY polled `building` header (operator or gateway) this session; Run 2 does not revisit it. Independently re-checked by this report via a source read at the final HEAD `e873920b` (`grep` over `modules/autocount/services/pull_gateway_service.py` and `pull_service.py`): neither header-construction function builds a `progress`/`pagesDone`/`pagesTotal`/`stage` field anywhere. This **contradicts** `BL-SS-236`'s own text ("AC-10-87's `{pagesDone, pagesTotal, stage}` landed on the public gateway's `GET /snapshots/{id}` response only") - recorded as a genuine docs/code discrepancy for the plan owner to resolve, not silently reconciled either way. Since the AC's own text marks the field OPTIONAL ("may carry"), its absence is not a hard AC failure per the AC's own wording - marked PARTIAL rather than FAIL. |
| AC-10-88 | BE | PASS | Live: `live-replay/cooldown-reattach-transcripts.txt` / `run2-cooldown-reattach-transcript.txt` - a build request while `building` returns the SAME `snapshotId` in 15-34ms, confirmed on both db1 and db2, no time limit observed. `pull-setup/README.md` independently confirms AC-10-88 PASS (every build this run started a genuinely new extraction once cooldown had elapsed, consistent with correct re-attach behaviour). The "dead build reclaimed via the orphan sweep" half was NOT live-triggered this pass (would require killing a running job mid-build); suite-reported: `test_s10_s3_review1_heartbeat.py`. |

### Group F - operator UI, end to end, live, docs

| ID | Tag | Status | Evidence |
|----|-----|--------|----------|
| AC-10-48 | FE | PASS | `pull-keys-snapshots/README.md` Run 2 - every named fixture state (active+revoked keys, building/ready/failed snapshots for both entities, 409 PUSH_ACTIVE) observed live in the browser after the phase-2 swap (commit `994ca215`, fix `6ec3f258`/`7660251a`). |
| AC-10-49 | FE | PASS | `pull-keys-snapshots/README.md` Run 2 (1280px, both product and stock detail: header facts, mode-specific metadata blocks, excluded-row list with reasons, negative-pair list, preview-grid reuse). `pull-setup/README.md` (375px detail: `14-snapshot-detail-header-375.png`, `15-snapshot-detail-rows-375.png`) and `pull-stock/README.md` (375px stock detail: `07-stock-snapshot-detail-header-375.png`) independently cover the 375px width. |
| AC-10-50 | E2E | PASS | `pull-setup/README.md` - full operator journey at 375px AND 1280px: Companies -> Product -> Schedule toggle -> Review & Activate -> Entities Delivery column -> Pull -> Keys -> Issue key -> Snapshots -> Build -> building -> ready -> detail, all real clicks, real data, current HEAD `17dc2c61`. |
| AC-10-51 | E2E | PASS-with-drift, one sub-clause FAIL (fixed) | `pull-stock/README.md` - Source tab, alias-collision-on-first-Test regression check, Schedule read-only badge, Build -> ready -> detail all PASS at both widths with exact-match figures (12,133 records, 42 negative, 0 fractional). The AC's literal "read-only Aggregated... chip" wording is superseded by the richer "Combine rows" section per owner ruling R11 (accepted, PASS-with-drift, not a fail). One genuine regression found this run: Defect D1 - the watermark picker leaked the saved combine measure alias (`qty`) on an ALREADY-SAVED stock task (not a brand-new draft, which `combine/README.md`'s own PASS had covered). **Fixed** at commit `d2eaa578` (`source-tab.tsx`, unit-tested in `source-tab.test.tsx` + `lib/autocount-etl.test.ts`, further pinned at confirm-4 commit `804524fb`) - not independently browser-re-verified after the fix (unit-test-verified only). |
| AC-10-52 | E2E | PASS | `flip-push/README.md` - full journey at both widths: Product flipped back to Push, cadence controls return with saved values, Save, Runs tab shows the schedule armed, two independent curl transcripts (one per viewport) confirm the consumer's pull now answers `409 PUSH_ACTIVE`. |
| AC-10-53 | T | PASS (db1 clean on Run 1; db2 fixed and PASS on Run 2) | `live-replay/README.md` Run 1: db1 product (`ready`, 11,840, exact match on every documented number) and db1 stock (`ready`, 12,133, 42 negative, exact match) both PASS; db2 (Mocha) FAILED both entities on Run 1 due to AC-10-85 not yet built (a real, live-discovered gap, not a data problem - see Finding 1 below). Run 2 (after the AC-10-85 fix landed): db2 product (`ready`, 3,445, sourcePageSize 150 after one halving, ~20m19s) and db2 stock (`ready`, 3,165, sourcePageSize 300, ~20m25-31s, reproduced byte-identical on a THIRD independent build) both PASS. **AC-10-53 is a full PASS across both books as of Run 2.** |
| AC-10-54 | T | PASS (suite-reported, live-consistent) | Suite-reported: the AC-10-06 stubbed two-run price-change test covers this exact scenario (one item's ItemUOM price changes -> 0/0/1, second run 0/0/0). Live-consistent: `s1-live-replay/README.md`'s three consecutive stable runs (0/0/0 each) on unchanged data. |
| AC-10-55 | T | PASS (suite-reported; (a)/(b) also live-corroborated by a genuine, unplanned real failure) | Suite-reported for the literal stub-500/enrich-500/expired-snapshot cases. `(a)` and `(b)` also independently corroborated live and for real (not a stub) in `live-replay/README.md` Run 1: a real db2 timeout produced `SOURCE_PAGE_FAILED` (product build) and `ENRICH_FAILED` (stock build, naming the `item` lookup endpoint) with zero readable rows and no `ac_staged_record`/`ac_row_hash` writes. `(c)` (expired snapshot 410) not live-timed (24h TTL). |
| AC-10-56 | T | **DEFERRED** - owner STOP before prod joint runs | Appendix A delivered to the Sorento peer session and ACKNOWLEDGED: peer corrections recorded verbatim in the plan text, dated 2026-09-19/2026-09-20 (R8/R10 sections; Appendix A's `product_name`/`uom_code` rows explicitly cite "peer correction 2026-09-20"), plus a further additive-changes message (`10-evidence/peer-message-a6.md`, six new gateway error codes, `Cache-Control: no-store`, the `page` upper bound, the corrected stock `excludedRows` shape) delivered 2026-09-20. Per the coordinator-recorded handoff (`.claude/handoffs/20260920T112000Z-...md`): the peer's contract-2.4 code-wins change (their SR0) and pull review page are reported LIVE on Sorento's own prod by the peer session (their words, not independently verified from this side); a LOCAL rehearsal (their `:8080` against our `:8009`) was offered and accepted in principle but had not happened as of this HEAD - **no evidence of joint run 1 (products) or joint run 2 (stock) exists in this worktree.** Owner pre-flight (gateway key in Sorento prod env, prod SRT/MCH company codes) is explicitly pending. **Marked DEFERRED; STOP before any prod joint run per the owner's own instruction, recorded verbatim in the handoff.** |
| AC-10-57 | T | PASS (this report) | This file. Suite counts, lint and build recorded as reported (table above), gate re-run pending. `documentation/engineering/process-lessons.md` lines ~108-142 carry the AutoCount reference section (delivery mode, lookups/enrich, combine/reduce, snapshot rows) - confirmed present. `documentation/engineering/module-platform-and-app-store.md` line ~12 carries the second public API-key gateway cross-reference (side-by-side table vs omnichannel) - confirmed present. Backlog rows BL-SS-207 through BL-SS-243 all confirmed present in `documentation/backlogs/backlog.md` (verified by grep, all 37 ids present). |
| AC-10-58 | T | PASS - SHIP-WITH-FIXES, all fixes landed | Coordinator-recorded security-pass verdict (Opus, PoC-backed, from `.claude/handoffs/20260920T112000Z-...md`): **SHIP-WITH-FIXES.** PASS on: no unscoped `get_by_id`; tenant/company never resolved from client input (cross-tenant probes return byte-identical 404); keys sha256-hashed + `hmac.compare_digest`, header-only, never logged, plaintext shown exactly once; audit table carries no PII; a suspended tenant, an inactive module, and a revoked key all answer uniformly; build cooldown 429 + `Retry-After` proven; separate throttle scopes; permissions + grant sweep real (confirmed live, see AC-10-36); immutability + cross-scope 404 hold; combine/anti-SSTI clean; the FE phase-2 swap is scope-guarded. Fixes shipped: M1 (gateway failed-header prose is a fixed per-code sentence, never the internal error text), M2 (outbound egress guard on `baseUrl` at save AND every request, https-only outside the one dev loopback carve-out - owner ruling D34/confirm-3 reaffirmed https-only after a draft briefly widened it), L1 (prune never deletes a `building` snapshot), L2 (`PullSnapshotRepository.delete` takes the owning `tenant_id`), L4 (`_finalize` wrapped so a best-effort audit-write exception cannot escape a clean error response), L5 (`last_used_at` stamped only after the service gate passes). L3 (in-tenant `COMPANY_NOT_ALLOWED` vs `UNKNOWN_COMPANY` distinction) kept by design, documented in plan section 2.10. XFF posture (`trust_proxy_headers=false`) is an open OWNER decision, not a fix - documented, not blocking. All fix commits present in the branch history (`d818ea4f` red, `02837e11` fix, `17dc2c61` docs; further hardened at confirm-3 `e22746d4`/`8b2d0bc4`/`1a973dd7` and confirm-4 `804524fb`/`9e18400d`). Not independently re-run by this docs-only pass; recorded as the coordinator's own verdict per the brief. |
| AC-10-67 | T | PASS | `10-fixtures/README.md` - S0 shipped every required file (product/stock header+rows, 409/410/401/404/429 error bodies, a `failed` header) with the required awkward rows (`****` description, dimensions-in-description, `Desc2` with a clean and a double-space join, `-1.0` clamped price, `0.0` price, edge-whitespace `ItemCode`, one Mocha-shaped no-brand row), every row run through the real `CanonicalProduct.sink_payload()`, never hand-typed. Re-verification against the real gateway in S6: the row/header SHAPE was independently confirmed live (`live-replay/README.md`'s "Gateway row-shape verification" section matches Appendix A4 exactly on both books, including the Mocha no-`brand_code` omission the fixture also encodes) - the specific fixture FILES were not byte-diffed against a live capture this pass, so this is a shape-class confirmation, not a literal re-diff. |

## Defects found and fixed during this build

All of the following were found by a tester's real-click `agent-browser` evidence run, reported to
a coder, and fixed in a later commit on the same branch (never fixed by the tester). Re-verification
status is stated per item - several were re-confirmed live by a SUBSEQUENT tester round on the same
saved state; two (D1, the combine pair) are unit-test-verified only, not independently
browser-re-verified after the fix, which is stated plainly rather than assumed.

1. **Lookups self-collision false-positive** (`lookups/README.md` step 10) - a second lookup's own
   Test spuriously flagged the FIRST lookup's pre-filled field alias as colliding with a source
   column. Fixed `81eee16e`; **browser-re-verified fixed** (`lookups/README.md` run 2, HEAD
   `7618bb33`).
2. **Lookups save-time alias self-collision hole** (found investigating #1) - a brand-new field
   alias equal to a real stored raw column could self-exempt itself from the collision check and
   save clean. Fixed `4c5ce70d`; **re-verified via curl** in the same file's "Corrections" section
   (422 now fires with the correct shape).
3. **Dirty-guard `AlertDialog` did not fire on the Schedule tab's Back/breadcrumb navigation**
   (`delivery/README.md` run 1) - an unsaved delivery-mode toggle was silently discarded. Fixed
   `4961b493`; **browser-re-verified fixed** on both Back and the breadcrumb, at both widths
   (`delivery/README.md` run 2, HEAD `7618bb33`).
4. **Pull page Revoke unreachable, then read/write mismatch, then fully working** - a three-round
   history: Run 2 found the deferred-action Revoke had no `ActionMenu` trigger at all (fixed, an
   Actions column added); Run 3 found Revoke reachable but 404ing because the page's LIST reads
   still came from the Phase-1 mock while the mutation targeted the real backend (root-caused as a
   phase-2-swap gap, not a backend bug); Run 4 (phase-2 swap fully landed, `994ca215`/`7660251a`)
   confirmed **PASS, fully, both viewports** - see AC-10-38 above.
5. **Combine drop-rule formula-builder rejected the pre-filled `qty` formulas** (`combine/README.md`
   Defect 1) - "Edit formula" on either drop rule showed "Unknown name 'qty'" and disabled Apply,
   though Test/Save/the funnel all worked correctly server-side. Fixed at `b1593264`
   (`combine-editor.tsx`, unit-tested in `combine-editor.test.tsx`) - **not independently
   browser-re-verified** after the fix (unit-test-verified only).
6. **Stock preset's own pre-filled lookup aliases showed a false-positive "already a source column"
   after Save** (`combine/README.md` Defect 2, second half) - Save succeeded and the values
   round-tripped correctly, but the persistent inline error was confusing noise. Fixed at the SAME
   commit `b1593264` (`source-tab.tsx`, `source-tab.lookup-self-collision.test.tsx`) - **not
   independently browser-re-verified** after the fix (unit-test-verified only).
7. **Watermark picker leaked the saved combine measure alias (`qty`) on an already-saved stock
   task** (`pull-stock/README.md` Defect D1, AC-10-51) - root-caused to `pickerColumnOptions`'s
   deliberate "stale saved pick" pool being shared across all three pickers (key/watermark/compared)
   without excluding a compared-only stale pick from the watermark-specific list. Fixed at `d2eaa578`
   (`source-tab.tsx`, unit-tested in `source-tab.test.tsx` + `lib/autocount-etl.test.ts`), further
   pinned by an additional test at confirm-4 (`804524fb`) - **not independently browser-re-verified**
   after the fix (unit-test-verified only).
8. **Public gateway build route blocked the entire backend for the full build duration**
   (`live-replay/README.md` Finding 2, severe - a THIRD-PARTY-facing credential could freeze every
   tenant's every route, including `/openapi.json`, for 9+ minutes by triggering a fresh build; the
   operator route was unaffected since it was already a plain `def`). Fixed by making
   `pull_v1.py`'s `build_snapshot` a plain `def` (Starlette's automatic threadpool) at commit
   `6c150e73`. **Browser-re-verified fixed** (`pull-setup/README.md` Finding A, HEAD `17dc2c61`: six
   separate `curl -m 5 /openapi.json` probes during two different in-flight gateway builds all
   answered in 5-29ms; normal UI navigation in a separate tab also succeeded during an in-flight
   build). `BL-SS-242` tracks a stronger, race-proof version of the regression test for this fix
   (the current test pins the route-shape fact only, not a true concurrency race).
9. **AC-10-85 (per-connection `pageSize`/`requestTimeoutSeconds`) was entirely unbuilt at S6's first
   pass**, making db2/Mocha unable to complete ANY pull build (`live-replay/README.md` Run 1
   Finding 1 - a real, live-discovered gap, not a stub). Fixed across `6c150e73`/`8b2d0bc4` (provider
   fields, connection-sizing helper shared by preview AND the real-run path, measured-latency Test
   message). **Browser AND live-replay re-verified fixed** (`pull-setup/README.md` Finding C -
   fields present and correctly gated, one minor UX note below; `live-replay/README.md` Run 2 - db2
   builds both entities `ready` end to end, repeatably, deterministically, at the raised 90s ceiling).

## Minor findings, not filed as defects (new backlog ids needed)

These were reported by a tester this pass and are real, reproducible, low-severity gaps with no
existing backlog row found (grepped `documentation/backlogs/backlog.md` for each) - **needs backlog
id**, not minted by this report:

- Connection Test/Edit form's new `Page size`/`Request timeout (seconds)` fields (AC-10-85) render
  BLANK with no placeholder hinting the documented server-side fallback defaults (1000 / 90) -
  `pull-setup/README.md` Finding C. Functionally correct (defaults apply server-side), a minor
  foolproof-UI gap only.
- The grace-window design question (does a revoked pull API key still work during the 9s deferred
  countdown) is ANSWERED - yes, confirmed by DB timestamp comparison (`revoked_at` landed ~0.8s
  AFTER a gateway call the key had already been accepted for) - `pull-setup/README.md` Finding B /
  `pull-keys-snapshots/README.md` Run 4. This is flagged as a DESIGN DECISION for the owner (should a
  security-sensitive revoke commit immediately rather than deferring the mutation itself), not a
  defect; `BL-SS-237` already tracks the general "revoked key stays live during the grace window"
  fact as owner-accepted, so no new id is needed for the fact itself - only the open "should Revoke
  specifically be immediate" design question remains unticketed.

Already tracked, cited for completeness: `BL-SS-235` (Entities-list row click does not navigate,
Configure only via Actions menu - confirmed as-designed per the shell's `rowHref: '#'` opt-out, not
a new finding).

## Owner rulings recorded (2026-09-20)

- **Base URLs HTTPS-only outside the development carve-out** (AC-08-03 amended; the egress guard
  stays https-only per decision D34, confirmed in plan section 2.10 and re-affirmed at review round
  confirm-3 after a draft briefly widened it and was reverted). `BL-SS-241` (High) tracks the ops
  consequence: an existing `http://` AutoCount connection fails EVERY walk after this change outside
  the dev loopback carve-out - count and migrate before deploying this branch.
- **A revoked pull key stays valid for the ~9s deferred-action grace window** - proven live in
  `pull-keys-snapshots/README.md` Run 4 (a curl build request during the countdown succeeded,
  `revoked_at` landed ~0.8s after the snapshot's own `created_at`). ACCEPTED as design.
- **AC-10-51's "Aggregated ... chip" wording is superseded by the R11 Combine rows section**
  (PASS-with-drift, recorded above) - the richer, fully-editable Combine rows UI is the intended
  replacement for the original chip-only mock text.
- **AC-10-56 joint runs with Sorento: DEFERRED.** STOP before prod joint runs per the owner's own
  pre-flight instruction (gateway key in Sorento's prod env, prod SRT/MCH codes still pending). The
  peer reports contract 2.4 + the pull review page live on their own prod (their words); a local
  rehearsal (their `:8080` against our `:8009`) was offered and accepted in principle but has not
  happened as of this HEAD - recorded as pending, no evidence of it in this worktree.
- **AC-10-58 security pass: SHIP-WITH-FIXES**, all fixes landed (M1/M2/L1/L2/L4/L5 above); L3
  (in-tenant `COMPANY_NOT_ALLOWED` vs `UNKNOWN_COMPANY` distinction) kept by design; XFF trust-proxy
  posture is an open owner decision, not taken in this slice.
- **AC-10-87 progress hint: gateway header only.** The public gateway's `building` header carries the
  optional `progress` hint field; the operator `PullSnapshotOut` schema does not (`BL-SS-236`) -
  marked PARTIAL relative to a hypothetical "everywhere" reading, though the AC text itself scopes
  `progress` to the gateway header only, so this is not a hard AC failure - recorded per the owner's
  own instruction to state it explicitly.

## Known open items -> backlog ids

Every id below is confirmed PRESENT in `documentation/backlogs/backlog.md` (verified by grep, all
37 ids `BL-SS-207` through `BL-SS-243` found): `BL-SS-207` (S7 stock push flip, planned follow-up,
deliberately out of this plan's DoD), `BL-SS-208`/`BL-SS-209` (kept as id-reservation rows, work
delivered in S1/S2/S5a), `BL-SS-210` (duplicate API-key pattern, acknowledged), `BL-SS-211`
(remaining wrapper endpoints, out of scope), `BL-SS-212` (snapshot storage at scale), `BL-SS-213`
(`cost_price` unsourced), `BL-SS-214` (server-side filtering ask), `BL-SS-215` (the `-1.0` price
sentinel, ask the API owner), `BL-SS-216` (closed before it opened - no ref normalisation needed),
`BL-SS-217` (warehouse push completeness), `BL-SS-218` (optional historical ref rekey), `BL-SS-219`
(vendor-side db2 wrapper performance, measured), `BL-SS-220` (per-endpoint-walk halving budget
reading), `BL-SS-221` (a lookup-alias-naming formula fails to parse on a miss), `BL-SS-222`
(preview matched/missed counts are a 50-row sample), `BL-SS-223`/`BL-SS-224` (pre-existing vitest
reds, unrelated to this plan), `BL-SS-225` (combine `excludedRows` has no per-entity extra column),
`BL-SS-226` (sample-type checks run only inside `preview_http`), `BL-SS-227`
(`last_used_at` uncoalesced), `BL-SS-228` (operator vs gateway header shape difference, by design),
`BL-SS-229` (Pull page's segment-as-fetcher-channel pattern, first of its kind), `BL-SS-230` (no
incremental row-ready signal), `BL-SS-231` (TTL/retention are module constants, not settings),
`BL-SS-232` (no cooperative-cancellation checkpoints on the pull build job), `BL-SS-233` (Phase-1
mock preview applies no lookups), `BL-SS-234` (no value-drift guard between FE/BE preset tables),
`BL-SS-235` (Entities-list row click does not navigate, by design), `BL-SS-236` (operator schema
lacks the `progress` hint), `BL-SS-237` (10s grace window keeps a revoked key live, by design),
`BL-SS-238` (pre-existing push-path re-staging defect, NOT plan-10 code, found live during replay),
`BL-SS-239` (HIGH, pre-existing `fingerprintQuery` silent-wipe defect, needs a GitHub issue per the
plan's own instruction), `BL-SS-240` (egress guard re-validates at request time, ops note),
`BL-SS-241` (HIGH, existing `http://` connections break outside the dev carve-out), `BL-SS-242`
(needs a stronger, race-proof event-loop-blocking test), `BL-SS-243` (pre-existing flaky countdown
assertion, unrelated to autocount work).

Two items surfaced by this pass with **no existing backlog id found** (needs backlog id, not minted
here): the blank connection-sizing fields with no default placeholder, and the open "should Revoke
commit immediately" design question (distinct from the already-tracked `BL-SS-237` fact).

## Cross-repo status

- Appendix A (the full cross-repo contract) delivered to the Sorento `autocount` peer session;
  corrections recorded verbatim in the plan text dated 2026-09-19/2026-09-20 (R8/R10, Appendix A9's
  `product_name`/`uom_code` rows).
- A further additive-changes message delivered 2026-09-20:
  `documentation/plans/sprint-5/10-evidence/peer-message-a6.md` (six new gateway error codes,
  `Cache-Control: no-store`, the `page` upper bound of 1,000,000, the corrected stock `excludedRows`
  shape, the fixed failed-snapshot message-prose rule).
- Per the coordinator-recorded handoff, the peer reports (their own words, not independently
  verified from this side) contract 2.4 (code-wins) and the pull review page are LIVE on Sorento's
  own prod, and a LOCAL rehearsal (their `:8080` against our `:8009`) was offered and accepted in
  principle.
- **No evidence of the rehearsal, joint run 1 (products), or joint run 2 (stock) exists anywhere in
  this worktree.** AC-10-56 is marked DEFERRED accordingly.

## STOP before joint runs

Per the owner's own recorded pre-flight instruction: **do not run a joint live test against
Sorento's production environment** until (a) the owner places `FOUNDRYX_BASE_URL` +
`FOUNDRYX_API_KEY` in Sorento's prod environment, and (b) a local rehearsal (this lane's `:8009`
against the Sorento peer's own local stack) has been completed and recorded under
`10-evidence/rehearsal/` (that directory does not exist yet in this worktree - the rehearsal has not
happened). AC-10-56's two joint runs (products `SRT` then `MCH`; stock `SRT` then `MCH`) remain
DEFERRED until both preconditions are met.

## Evidence directories

- `10-evidence/s1-live-replay/` - AC-10-01..08, 59..61, 71, 73..75 (S1, `[T]` live replay, db1,
  logging sink, plus a post-review re-check and corrections section).
- `10-evidence/lookups/` - AC-10-09, AC-10-09b (`[FE]`/`[E2E]`), two rounds (defect found then
  confirmed fixed).
- `10-evidence/mapping-clamp/` - AC-10-61 (`[FE]`, real backend).
- `10-evidence/delivery/` - AC-10-16, AC-10-17 (`[FE]`), two rounds (dirty-guard defect found then
  confirmed fixed; live Pull-mode banner and Delivery column both eventually confirmed live).
- `10-evidence/pull-setup/` - AC-10-50 (`[E2E]`), plus AC-10-16/17/85/88 re-verification and two
  findings (Finding A: gateway event-loop block CONFIRMED FIXED; Finding B: grace-window key
  validity ANSWERED; Finding C: blank sizing-field placeholders).
- `10-evidence/pull-stock/` - AC-10-51 (`[E2E]`), plus Defect D1 (watermark alias leak, found and
  later fixed).
- `10-evidence/flip-push/` - AC-10-52 (`[E2E]`).
- `10-evidence/pull-keys-snapshots/` - AC-10-38, 48, 49 (`[FE]`), four rounds (mock-only -> Issue-key
  fixed -> Revoke reachable-but-404 -> fully working).
- `10-evidence/combine/` (+ `PROBE.md`) - AC-10-40, 41, 82, 83, 84 (`[FE]`/`[E2E]`/`[T]`), two
  defects found (formula-builder scope, false-positive alias) both later fixed.
- `10-evidence/live-replay/` - AC-10-53, 85, 86 (`[T]`), Run 1 (db1 clean pass, db2 fails with two
  real findings: AC-10-85 unbuilt, gateway event-loop block) and Run 2 (db2 fixed, full pass on both
  books).
- `10-fixtures/README.md` - AC-10-67 (`[T]`, S0 sample fixtures for the Sorento mock build).
- `10-evidence/peer-message-a6.md` - AC-10-56 cross-repo additive-changes message.
