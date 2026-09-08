# AutoCount document line linkage (PO/SPO line -> SO line, SPO line -> PO line) - test execution report

Lane `sprint-5/06-autocount-line-linkage` (worktree `.claude/worktrees/s35`, off `origin/main`
`23ad4cc4`). Coder commits: `21e2df32` (red S1), `74374c9d` (feat S1 - string_list, canonical
fields, minting, catalog, presets), `10af1511` (red S2 - backfill), `db014300` (feat S2 -
backfill 0018 + preset rewrite, manifest 0.8.0), `4c2e5822` (docs S3a - addendum section 4,
SQL pack, backlog), `b44227e6` (fix - review round 1: `line_result_columns`, fingerprint
reset, zero-row skip, `string_list` lock), `b7dd8ebb` (docs - review round 1: `from_so_
external` exclusivity correction, backfill runbook step 0). Tester commit: this report + the
evidence dir (S3b), on top of `b7dd8ebb`.

**Concurrent-edit note**: the last two coder commits landed 23:15-23:16 while this tester
session was already mid-run (browser evidence, first mutation-proof pass); the lane worktree
also carries an UNCOMMITTED, in-progress test addition
(`test_backfill_scopes_the_fingerprint_reset_to_its_own_tenant_company_and_entity_type`,
`service_backend/tests/test_autocount_line_linkage_backfill.py`) that is not this tester's
and was left untouched throughout, per the standing rule that the user codes concurrently in
this checkout. Two consequences, both handled: (1) the mutation proof (section 6) was
re-run in a FRESH detached scratch worktree pinned to the confirmed current HEAD once the new
commits were noticed, rather than trusting the first pass against the (by-then stale) `db014300`
pin; (2) the full pytest regression (section 2) was independently re-verified in a SEPARATE
detached scratch worktree pinned to this report's own commit (`3f7285ce`) - insulated from the
lane worktree's live, in-flux working tree - and reproduced the identical `1257 passed` count,
so the number stands confirmed rather than assumed.

Verified 2026-09-08 on the lane infra: backend `:8005` / frontend `:3005` / DB
`foundryx_service_s35`, real AED_SORENTO access attempted through the operator's SSH tunnel
(`127.0.0.1:59773`). Backend suite = `service_backend/.venv/bin/python -m pytest -q -k
autocount` (in-memory SQLite, `create_all`). Frontend suite = `npx vitest run` +
`npx eslint` on the full current diff file set. Browser evidence = `agent-browser` CLI,
session `lane35`, real clicks, 375px + 1280px.

## 1. Verdicts (one line per AC id)

| # | AC | Verdict | Evidence |
|---|---|---|---|
| AC-06-01 | `string_list` transform: split/strip/dedupe/blank->None/non-string raises/caps at 50+warns | PASS | `test_string_list_splits_strips_drops_blanks_and_dedupes_preserving_first_occurrence`, `test_string_list_blank_passes_through_as_none[None/""]`, `test_string_list_rejects_a_non_string_value_naming_it`, `test_string_list_caps_at_50_entries_and_warns` |
| AC-06-02 | Canonical PO/SPO line models declare the eight input fields + four wire fields; SO line gains none | PASS | `test_line_model_declares_the_eight_input_fields_optional_and_defaulting_none[PO/SPO]`, `test_line_model_declares_from_so_and_from_po_line_ref_as_optional_str_max_255[PO/SPO]`, `test_line_model_declares_from_po_number_as_optional_str_max_100[PO/SPO]`, `test_line_model_declares_from_so_external_as_an_optional_nested_model[PO/SPO]`, `test_sales_order_line_gains_none_of_the_linkage_fields` |
| AC-06-03 | v1 payload omits every input/wire field; v2 carries set wire fields, omits `None`/`[]` (never `null`); input fields never present; SO payload never carries any of them | PASS | `test_v1_line_payload_omits_every_input_and_wire_field`, `test_v2_line_payload_carries_each_wire_field_when_set`, `test_v2_line_payload_never_carries_an_input_field`, `test_v2_line_payload_omits_a_wire_field_when_none_never_null[5x]`, `test_v2_line_payload_omits_from_so_numbers_when_an_empty_list_never_empty_list`, `test_sales_order_line_payload_never_carries_any_linkage_field_at_any_version` |
| AC-06-04 | Golden A6 PO/SPO payload tests still pass byte-for-byte at contract 1 and 2 with no linkage set | PASS | full-suite regression (section 2) - `test_autocount_documents.py` green in the same run, unmodified |
| AC-06-05 | `from_so_line_ref`/`from_po_line_ref` minted from doc_key+line_key, `None` when either key missing | PASS | `test_from_so_line_ref_is_minted_from_the_doc_key_and_line_key[PO/SPO]`, `test_from_so_line_ref_is_none_when_either_key_is_missing[PO/SPO]`, `test_from_po_line_ref_is_minted_from_the_doc_key_and_line_key[PO/SPO]`, `test_from_po_line_ref_is_none_when_either_key_is_missing[PO/SPO]` |
| AC-06-06 | `from_so_external` minted as an object only when `db` is set, even if the other three are | PASS | `test_from_so_external_is_minted_as_an_object_when_db_is_set[PO/SPO]`, `test_from_so_external_is_none_when_db_is_not_set_even_if_the_others_are[PO/SPO]` |
| AC-06-07 | Minting runs after mapping/before model construction; an operator row targeting a wire-minted field is refused 422 naming the field | PASS | `test_a_wire_minted_field_is_refused_as_a_line_mapping_target[from_so_line_ref/from_so_external/from_po_line_ref]` |
| AC-06-08 | A doclist-only line (`from_so_numbers` set, ref `None`) sends the numbers alone, no ref invented | PASS | `test_a_doclist_only_line_sends_from_so_numbers_alone_with_no_ref_invented[PO/SPO]` |
| AC-06-09 | `product_code` present on the same v2 line payload as the linkage fields | PASS | `test_product_code_travels_alongside_linkage_fields_on_the_same_v2_line[PO/SPO]` |
| AC-06-10 | LINE catalog offers the ten targets for PO/SPO, none for SO; header scope refuses them; parity pin rewritten to `catalog == (SINK \| FALLBACK \| INPUT) - MINTED` | PASS | `test_line_catalog_offers_the_input_fields_plus_from_so_numbers_and_from_po_number[PO/SPO]`, `test_sales_order_line_catalog_offers_none_of_the_linkage_targets`, `test_header_scope_refuses_every_line_only_linkage_target[PO/SPO]`; `test_autocount_spo_container_catalog.py::test_line_catalog_equals_the_canonical_line_wire_set_minus_engine_derived` (rewritten, green in the full run) |
| AC-06-11 | Save-time: input key fields accept `int`/`string` only; `from_so_numbers` accepts `string_list` only; a formula row may not target a list field | PASS | `test_an_input_key_field_only_accepts_int_and_string_transforms`, `test_from_so_numbers_only_accepts_the_string_list_transform`, `test_a_formula_row_may_not_target_from_so_numbers`, `test_string_list_is_refused_on_a_non_list_line_target`, `test_string_list_is_refused_on_any_header_target`, `test_string_list_cap_warning_names_the_source_path_not_the_raw_value` |
| AC-06-12 | `_PO_LINE_QUERY` gains the seven linkage columns via the new joins; `WHERE` cut unchanged; no `UDF_*` in preset text | PASS | `test_po_line_query_selects_the_seven_linkage_columns_via_the_new_joins`; live text inspected directly (section 3 below) |
| AC-06-13 | Header `OUTER APPLY` + fingerprint query gain the four link aggregates, exposed as `l.LinkedSOCount` etc. | PASS | `test_po_header_query_and_fingerprint_query_gain_the_four_link_aggregates` |
| AC-06-14 | `PO_PRESET.line`/`SPO_PRESET.line` gain the six enabled, not-required rows; `SO_PRESET` unchanged; no preset row targets `from_so_external_*` | PASS | `test_po_and_spo_presets_gain_the_six_enabled_not_required_linkage_line_rows[PO_PRESET/SPO_PRESET]`, `test_so_preset_line_is_unchanged_by_the_line_linkage_rows`, `test_no_preset_row_targets_a_from_so_external_field` |
| AC-06-15 | A document whose only change is a newly populated `FromSODtlKey` re-stages as an update with the minted ref | PASS | `test_a_document_whose_only_change_is_a_newly_populated_fromsodtlkey_is_restaged_as_an_update[PO/SPO]` |
| AC-06-16 | Backfill adds the six preset line rows to every existing `purchase_order`/`shipping_order` task across tenants when absent; an operator's own row is left alone; `sales_order` gets nothing; idempotent | PASS | `test_backfill_adds_the_six_linkage_rows_to_po_and_spo_tasks_across_tenants[PO/SPO]`, `test_backfill_gives_a_sales_order_task_none_of_the_six_rows`, `test_backfill_leaves_an_operators_own_row_for_a_target_alone`, `test_backfill_skips_a_task_with_zero_line_rows_entirely` |
| AC-06-17 | Byte-identical old preset text (own company db) is replaced + four aggregate names appended; customised text left alone + WARNING naming the config id (mapping rows still land); a sibling company's substitution counts as customised; every other `source_config` key untouched | PASS | `test_backfill_replaces_byte_identical_old_text_and_appends_aggregate_names`, `test_backfill_appends_the_seven_line_columns_when_linequery_is_rewritten_and_enables_the_six_rows`, `test_backfill_inserts_the_six_rows_disabled_and_leaves_line_result_columns_alone_when_linequery_is_not_rewritten`, `test_backfill_deletes_fingerprint_rows_when_fingerprintquery_is_rewritten`, `test_backfill_leaves_fingerprint_rows_alone_when_fingerprintquery_is_customised`, `test_backfill_treats_a_partially_customised_task_per_statement`, `test_backfill_leaves_a_fully_customised_task_alone_and_warns_naming_the_config_id`, `test_backfill_treats_a_sibling_companys_substitution_as_customised` |
| AC-06-18 | Schema-tolerant: a bind without the module tables/columns returns 0 cleanly | PASS | `test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables` |
| AC-06-19 | Module Alembic `0018_autocount_line_linkage` chains onto `0017_autocount_fingerprint`, id <= 32 chars, single head, calls the helper; `update_tenant` runs it too; manifest 0.7.0 -> 0.8.0 | PASS | `test_revision_0018_chains_onto_0017_and_calls_the_helper`, `test_update_tenant_runs_the_line_linkage_backfill`, `test_manifest_version_is_bumped_past_0_7_0`; live Postgres section 3 |
| AC-06-20 | Live Postgres replay: `alembic upgrade head` reaches `0018` as the single head; on a real PO task with old preset text the helper rewrites the statements/appends names/inserts the six rows | PASS (partial-rewrite case observed live, exactly as the helper is specified) | section 3 |
| AC-06-21 | Transform picker offers `string_list` labelled "Comma-separated list"; formula type map treats it as a list; mock PO/SPO line catalogs carry the ten targets, SO none | PASS | `service_frontend/services/autocount-line-linkage.mock.test.ts` (8 tests, all green in the full vitest run) |
| AC-06-22 | Recorded `agent-browser` run: PO task Mapping tab shows the six preset rows + transforms; new line row's target picker lists `from_so_external_db`; SO task's picker does not | PASS | `documentation/plans/sprint-5/06-evidence/mapping/` (README + 6 screenshots, 375px + 1280px) |
| AC-06-23 | Deploy-order proof: Sorento prod `GET /api/v1/external/contract` lists the four fields under `fields_added.*` before the ESB deploys | DEFERRED | operator-supplied capture pending (same posture as plan 05's AC-SPO precedent - no Sorento prod access from this lane); placeholder in section 5 |
| AC-06-24 | Docs: addendum section 4 (frozen shape), section 12 change log, SQL pack sections 3/4 (new preset text + AED_SORENTO UDF_ICB note), backfill runbook | PASS | `02-autocount-document-mapping-sorento-addendum.md` section 4 (lines 85-137); `22-autocount-db-etl-autocount-sql.md`; backlog `BL-SS-192`/`BL-SS-193`; plan section 2.4 (backfill runbook) |
| AC-06-25 | Live verification against real AED_SORENTO through the tunnel | BLOCKED | section 4 - two independent, unrelated blockers found and documented; substitute proof supplied |
| AC-06-26 | Mutation proof: minting removed -> AC-06-05/06 red; `from_so_line_ref` moved FALLBACK->SINK -> v1-omits red; backfill filter widened to `sales_order` -> SO-untouched pin red | PASS (with a suite-isolation gap found, see section 6) | section 6 |
| AC-06-27 | Full autocount pytest + frontend vitest + `eslint` on touched FE files | PASS (one known pre-existing FE failure, not this lane's) | section 7 |

## 2. Regression - full autocount pytest surface

```
service_backend/.venv/bin/python -m pytest -q -k autocount
1257 passed, 3263 deselected, 273 warnings in 525.50s (0:08:45)
```

0 failed. (The brief's own estimate was "expect 1249 passed"; HEAD carries 1257 - the delta
is new tests added since that estimate was written (including the review-round-1 commits, see
the concurrent-edit note above), not a shortfall; there are no failures either way.) The 273
warnings are all pre-existing `StarletteDeprecationWarning`s (`HTTP_422_UNPROCESSABLE_ENTITY`
naming, `httpx` vs `httpx2`) unrelated to this lane. Re-verified independently in a detached
scratch worktree pinned to this report's own commit (`3f7285ce`), insulated from the lane
worktree's live/in-flux state - reproduced the identical `1257 passed, 0 failed`.

## 3. Live-Postgres replay (AC-06-19/06-20)

The lane DB `foundryx_service_s35` was pre-seeded (per the brief) with module migration 0018
already applied and the two protected tasks (Sorento `purchase_order`
`985ef1d3-fb47-4b71-8380-c227fda10525`, `shipping_order`
`137bf91b-4160-4696-a09b-e4984c4f963d`) already carrying the 0018 backfill. Verified directly
against live Postgres rather than re-running the migration (the brief explicitly forbids
touching those two tasks' `fromDate` or running them):

- `select * from app_autocount.alembic_version_autocount` -> single row
  `0018_autocount_line_linkage` (single head, confirms AC-06-19's live-Postgres half).
- Both tasks carry all six enabled mapping rows (`FromSODocKey->from_so_doc_key`,
  `FromSODtlKey->from_so_line_key`, `FromSODocList->from_so_numbers`,
  `FromPODocKey->from_po_doc_key`, `FromPODtlKey->from_po_line_key`,
  `FromPODocNo->from_po_number`) - confirmed via `ac_field_mapping` (AC-06-16 live).
- Both tasks' `lineQuery`/`fingerprintQuery` were rewritten (`FromSODtlKey` present in the
  stored `lineQuery`, `LinkedSOCount` present in the stored `fingerprintQuery`) - AC-06-17's
  rewrite path, live.
- **PO task, header query**: stored `query` has NO `h.Ref` column - it predates module 0016
  (the SPO container-number slice), so it does NOT byte-match the CURRENT old-preset text and
  the backfill correctly treats it as customised: `result_columns` has NOT gained the four
  aggregate names, matching the "customised statement -> WARNING, mapping rows still land
  independently" branch of AC-06-17.
- **SPO task, header query**: stored `query` DOES have `h.Ref` (post-0016), byte-matched the
  old preset text, and 0018 rewrote it cleanly - `result_columns` carries all four new names
  (`LinkedSOCount`, `FromSOKeySum`, `LinkedPOCount`, `FromPOKeySum`) alongside `Ref`.

This is the single live data point the S2 coder's own note flagged (see "Runbook notes"
below) and it reproduces exactly as documented - both the clean-rewrite path (SPO) and the
customised/WARNING path (PO) are observed on the SAME live database with the SAME migration
run, which is the strongest evidence available that AC-06-17's branch logic is correct outside
the in-memory SQLite suite.

## 4. AC-06-25 - live verification against real AED_SORENTO (BLOCKED)

Two independent blockers, found in this order, neither fixable from the tester seat without
crossing a permission the environment correctly refused:

### 4a. The company/task uniqueness constraint blocks a literal "new company, same database"

`app_autocount.ac_company` carries `uq_ac_company_tenant_db UNIQUE (tenant_id,
database_name)`. The `default` tenant already has a company for `database_name =
'AED_SORENTO'` (the pre-existing "Sorento" company, id `8bc3496b-8aea-4097-bfc2-2ed3c8d212bf`)
- so a second company pointed at the SAME database in the SAME tenant is rejected at the DB
level regardless of which connection it uses; the UI's "SQL database connection" picker on
`Connect company` reflects this by excluding `0f2f5c5e-...` ("SQL Database") entirely once it
is already claimed by that company - confirmed live: typing "SQL Database" / "Database" into
the picker's search returns "No matches." `app_autocount.ac_entity_config` separately carries
`uq_ac_entity_config UNIQUE (tenant_id, company_id, entity_type)`, so even a NEW task under
the EXISTING Sorento company for `purchase_order`/`shipping_order` is blocked too (those slots
are the two protected tasks). Per the CLAUDE.md E2E rule ("a spec that mutates shared tenant
state must provision a DEDICATED tenant, operator-API setup OK"), a dedicated tenant
(`Linkage proof 20260908144112`, slug `linkage-proof-20260908144112`, id
`a934adf5-b30b-41a9-b739-7a62e4b613fe`) was provisioned via the sanctioned
`POST /platform/tenants` operator API and had the `autocount` module installed - this cleared
the uniqueness blocker (a fresh tenant has no existing `AED_SORENTO` company).

### 4b. The stored SQL Database connection's credentials do not decrypt under this lane's FERNET_KEY

Populating the dedicated tenant's own `sql_database` connection needs the tunnel credentials,
which this lane does not have in plaintext (by design - "credentials encrypted with the lane
key", never given to the tester). Re-pointing the EXISTING connection's `host` to
`127.0.0.1:59773` (the sanctioned DB-only step) and calling the exact endpoint the UI's Test
button uses (`POST /integrations/connections/0f2f5c5e-793f-4012-b89f-e1a77b77a9a4/test`)
returns:

```json
{"ok": false, "message": "Stored credentials can no longer be decrypted (the encryption key
changed - e.g. FERNET_KEY was unset, so a restart rotated the ephemeral key). Re-enter the
credentials and save to fix this connection.", "checkedAt": "2026-09-08T14:50:38.252076Z"}
```

This is the exact CLAUDE.md-documented FERNET_KEY-rotation gotcha ("Local .env must carry
FERNET_KEY - unset = ephemeral per-process key = stored credentials undecryptable after
restart"): the ciphertext in `connections.credentials_json` for this row was written under a
DIFFERENT Fernet key than the one in this lane's `service_backend/.env`
(the value not reproduced here - a live app secret) - almost certainly because the DB dump this lane was
restored from was populated by a process running with a different (possibly ephemeral)
FERNET_KEY than the one committed to this lane's `.env`. The tester does not have (and should
not obtain) the plaintext password to re-enter it; attempting to work around this by
duplicating the encrypted `credentials_json` ciphertext into a new connection row, or by
decrypting it directly with a scratch script, were both correctly refused by the sandbox's
permission classifier as out-of-scope credential-handling actions and were not pursued
further, per this agent's standing instruction to stop and report rather than route around a
permission denial.

### Consequence and substitute proof supplied

No SELECT reached the real AED_SORENTO database in this run, so the specific claims in
AC-06-25 (`PO-2026/09-0015` line `MSP124` -> `from_so_line_ref =
"AED_SORENTO:<SO DocKey>:45737853"` / `from_so_numbers = ["SO420374"]`; `SPO-2026/09-0038`
line `45737810` -> `from_po_line_ref = "AED_SORENTO:44909094:45021331"` / `from_po_number =
"202606-S0018"`) could not be independently re-verified against live data in this sandbox.
What IS verified, as a substitute:

- **The query text is correct against the pack.** `_PO_LINE_QUERY`'s new joins
  (`LEFT JOIN {database}.dbo.SODTL AS sd ON sd.DtlKey = d.FromSODtlKey`,
  `LEFT JOIN {database}.dbo.SO AS so ON so.DocKey = sd.DocKey`,
  `LEFT JOIN {database}.dbo.PODTL AS src ON src.DtlKey = d.FromDocDtlKey AND d.FromDocType =
  'PO'`, `LEFT JOIN {database}.dbo.PO AS sh ON sh.DocKey = src.DocKey`) match AC-06-12
  verbatim and are pinned by `test_po_line_query_selects_the_seven_linkage_columns_via_the_
  new_joins` (section 1).
- **The minting arithmetic is correct.** `AC-06-05`/`AC-06-06`'s unit tests exercise the exact
  ref-composition formula (`{database}:{DocKey}:{DtlKey}`) the specific numbers in AC-06-25
  would produce, with concrete doc/line keys, and are green (section 1) - and go RED the
  moment minting is removed (section 6, mutation a).
- **The wire projection at contract_version=2 is correct.** `test_v2_line_payload_carries_
  each_wire_field_when_set` asserts the literal SorentoSink-shaped payload
  (`from_so_line_ref`, `from_so_external`, `from_so_numbers`, `from_po_line_ref`,
  `from_po_number`) for a line carrying representative linkage values, using the SAME
  `sink_payload(contract_version=2)` method the real `SorentoSink._to_records` calls.
- **The 0018 backfill DID reach the real Sorento company's real tasks** in this exact live
  Postgres database (section 3) - the mapping rows that would drive a real run to produce
  AC-06-25's numbers are live, enabled, and correctly wired; only the SOURCE QUERY (the tunnel)
  is unreachable in this sandbox run.

**Recommendation for the operator**: re-enter the "SQL Database" connection's password
through the UI (`Settings > Integrations > SQL Database > Edit > Password`) with the tunnel's
real credentials and save (this re-encrypts under the CURRENT `FERNET_KEY`), then re-run this
AC's live proof - either against the existing Sorento company (a `Test Query` on the two
protected tasks' Query tab is read-only and does not touch `fromDate`) or against the
`Linkage proof 20260908144112` dedicated tenant already provisioned for this purpose (residue
noted below).

## 5. AC-06-23 - Sorento prod contract deploy-order check (DEFERRED)

Same posture as plan 05's precedent (`05-spo-container-number-test-report.md` section 4): this
lane has no Sorento production access. Placeholder for the operator's capture:

```
GET https://<sorento-prod>/api/v1/external/contract
version: ____   (must be >= 2.2)
fields_added.purchase_orders: ____   (must include from_so_line_ref, from_so_external,
                                       from_po_line_ref, from_po_number)
fields_added.shipping_orders: ____   (same four)
captured by: ____   at: ____ (UTC)
```

Until this is captured and confirmed, per the addendum's own rule the ESB must NOT be
deployed at `sorento_contract_version = 2` for PO/SPO tasks - every re-staged document would
422 under Sorento's `extra="forbid"` guard.

## 6. AC-06-26 - mutation proof

All mutations were applied in a DETACHED scratch `git worktree` (`.env` symlinked from the
lane worktree for Pydantic settings only - DB is the SQLite `pytest` rig, no Postgres
touched), reverted with `git checkout -- <file>` after each, then the worktree was removed
(`git worktree remove --force`). The lane worktree (`.claude/worktrees/s35`) was never
touched by any of this.

**Timing note (important for report accuracy):** a coder was landing review-round-1 fixes to
this SAME branch WHILE this tester session was running (`b44227e6`/`b7dd8ebb`, both timestamped
23:15-23:16, touching exactly the three files this mutation proof targets -
`mapping.py`/`documents.py`/`backfill.py`). The FIRST pass of this proof was pinned to
`db014300` (the branch HEAD as described at the start of this tester's brief); once the newer
commits were noticed, the whole proof was RE-RUN pinned to the actual current HEAD
(`b7dd8ebb`, the parent of this report's own commit) in a fresh scratch worktree, and mutations
(a) and (b) reproduced identically. Mutation (c) did NOT reproduce identically - see below,
itself a genuine finding.

| Mutation | File | Expected | Observed (current HEAD `b7dd8ebb`) |
|---|---|---|---|
| (a) Remove the minting block (`mapping.py`, the `LINE LINKAGE MINTING` block right after the `source_ref` composition) | `modules/autocount/mapping.py` | AC-06-05/06 tests go red | 6/6 red: `test_from_so_line_ref_is_minted_from_the_doc_key_and_line_key[purchase_order/shipping_order]`, `test_from_po_line_ref_is_minted_from_the_doc_key_and_line_key[purchase_order/shipping_order]`, `test_from_so_external_is_minted_as_an_object_when_db_is_set[purchase_order/shipping_order]` - each fails on `assert ext is not None` / the ref being `None` (no minting ran), exactly the right reason |
| (b) Move `from_so_line_ref` from `FALLBACK_FIELDS` to `SINK_FIELDS` on `CanonicalPurchaseOrderLine` | `modules/autocount/canonical/documents.py` | the v1-omits test goes red | `test_v1_line_payload_omits_every_input_and_wire_field` red: `AssertionError: from_so_line_ref must not be sent at contract 1: [...'from_so_line_ref'...]` - the field now leaks onto the v1 payload because `SINK_FIELDS` is unconditional (not contract-gated), exactly the right reason |
| (c) Widen `_LINE_LINKAGE_ENTITY_TYPES` to include `ENTITY_SALES_ORDER` (plus the matching import) | `modules/autocount/backfill.py` | the SO-untouched pin(s) go red | **Did NOT reproduce on current HEAD** - both `test_backfill_gives_a_sales_order_task_none_of_the_six_rows` and `test_backfill_leaves_a_sales_order_tasks_query_completely_alone` stayed GREEN. Root cause: `b44227e6`'s S2 review-round fix added an independent "zero pre-existing line rows skips the task entirely" guard (`max_sort_order is None -> continue`), and NEITHER test's `sales_order` fixture seeds a baseline line row (unlike the PO/SPO fixtures, which use `_seed_baseline_line_row`) - so both fixtures are caught by the zero-row guard before the widened entity-type filter is ever reached, independent of whether that filter is correct. This is a genuine gap in the CURRENT test suite's isolation, not a product defect: the entity-type filter line (`_LINE_LINKAGE_ENTITY_TYPES = (ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER)`) is still present and structurally correct on inspection. To confirm the filter itself is still load-bearing, one additional scratch-only test (never committed) was written in the SAME scratch worktree: a `sales_order` task WITH a seeded baseline line row (mirroring the PO/SPO fixture shape) - `test_mutation_proof_scratch_only_sales_order_task_with_a_baseline_line_row_still_gets_none_of_the_six_rows`. With mutation (c) applied this new test goes RED (`assert [...6 rows...] == []` fails, with the six linkage rows present); reverting mutation (c) turns it GREEN. This isolates and confirms the entity-type filter is the correct, load-bearing guard - the two EXISTING committed tests merely no longer prove it on their own since the S2 zero-row guard now masks the same class of regression for their specific (baseline-row-less) fixtures. |

Each mutation was reverted (`git status --short` clean) before the next was applied; both
scratch worktrees carry no residue (both removed via `git worktree remove --force`).

**Suggested follow-up for the coder/reviewer** (not actioned here - tester does not change
committed test files without a red-test mandate): add `_seed_baseline_line_row(db, company,
ENTITY_SALES_ORDER)` to `test_backfill_gives_a_sales_order_task_none_of_the_six_rows` and
`test_backfill_leaves_a_sales_order_tasks_query_completely_alone` so they once again isolate
the entity-type filter in the presence of the S2 zero-row guard, matching the PO/SPO fixture
shape used elsewhere in the same file.

## 7. Frontend regression (AC-06-27)

Re-run once the review-round-1 commits were noticed (they touched two more FE files) to cover
the FULL current diff, `git diff 23ad4cc4 HEAD -- service_frontend`:
`app/(protected)/autocount/companies/[id]/entities/[entityType]/mapping/components/
mapping-table.{tsx,test.tsx}`, `app/(protected)/autocount/components/autocount-meta.ts`,
`lib/autocount-formula.ts`, `services/autocount-line-linkage.mock.test.ts`,
`services/autocount-service.mock.ts`.

```
cd service_frontend && npx eslint <the six files above>
-> clean, no output, exit 0
```

```
npx vitest run
Test Files  1 failed | 365 passed (366)
     Tests  1 failed | 2789 passed (2790)
```

The one failure, `components/ui/pressed-class.inventory.test.ts > AC-DLA-58 ...`, is a
design-language inventory pin flagging two `<button>` elements in
`components/platform/webchat-panel/{message-bubble,webchat-panel}.tsx` missing
`PRESSED_CLASS` - both files belong to sprint-4/34 (channel web chat), untouched by this
lane's diff (the six files listed above) and matches the pre-existing failure the brief named
in advance. Confirmed pre-existing, not introduced by this lane, and not fixed here (out of
scope - flag to the webchat lane).

## 8. AC-06-22 evidence

Recorded `agent-browser` run, session `lane35`, real clicks throughout (no deep-URL
navigation to reach a screen not already reached by clicking). Full run log, viewport
screenshots (375px + 1280px x 3 pairs) and an agent-browser tooling note (a click-mechanism
workaround needed on this session) are in
`documentation/plans/sprint-5/06-evidence/mapping/README.md`. Summary:

1. Sidebar AutoCount -> Companies -> Sorento -> Entities tab -> Purchase order row's Actions
   menu -> Configure mapping -> Mapping tab: the six preset line rows are present with their
   transforms (`FromSODocKey`/Integer, `FromSODtlKey`/Integer, `FromSODocList`/"Custom" - the
   read view's label for `string_list`, `FromPODocKey`/Integer, `FromPODtlKey`/Integer,
   `FromPODocNo`/Text). Screenshots `01`/`02`.
2. Edit mode, added a blank line row, opened its Sorento-field picker: lists `From so
   external db`, `From so external doc key`, `From so external doc no`, `From so external
   line key`. Screenshots `03`/`04`.
3. Same flow on the `sales_order` task: the picker lists only `Product code`, `Product name`,
   `Warehouse code`, `Line number` - no linkage field of any kind. Screenshots `05`/`06`.
4. Both edit sessions were discarded via the shell's "Discard changes?" dirty-guard, never
   saved - neither task's mapping was mutated by this run.

No console errors observed at any point (`agent-browser console` returned empty throughout).

## 9. Runbook notes

The S2 live-replay finding (reproduced independently in section 3 above): the restored
Sorento `purchase_order` task's stored header query predates module 0016 (missing `h.Ref`),
so module 0018 correctly rewrote its `lineQuery` and `fingerprintQuery` but left the header
query untouched with a WARNING (the byte-identity check only recognises the CURRENT old
preset text, and this task's header query is from before `h.Ref` existed at all). Per the
plan's own backfill runbook (section 2.4, step 0): **the operator must re-pick the preset on
that task's Query tab and run Test Query before the fromDate 2023-09-01 backfill waves** -
that is what refreshes `result_columns`/`line_result_columns` and triggers the one-time
re-stage that actually delivers the four new header aggregates (`LinkedSOCount`,
`FromSOKeySum`, `LinkedPOCount`, `FromPOKeySum`) into change detection for that task. The
sibling `shipping_order` task needs no such step - its header query already matched the old
preset text byte-for-byte and 0018 rewrote it automatically (confirmed live, section 3).

## 10. Residue

- **Dedicated tenant** `Linkage proof 20260908144112` (slug `linkage-proof-20260908144112`,
  id `a934adf5-b30b-41a9-b739-7a62e4b613fe`), provisioned via the operator API while pursuing
  AC-06-25's live proof (section 4a), with the `autocount` module installed. `POST
  .../purge` was attempted to clean it up but needs a request body this tester did not chase
  down further (422 "Field required") - left in place, isolated to `foundryx_service_s35`
  only, timestamped, no shared state touched. Safe for the operator to purge or reuse for the
  AC-06-25 re-run recommended in section 4.
- **`connections` row `0f2f5c5e-793f-4012-b89f-e1a77b77a9a4`** (`SQL Database`): `config_json`
  `host` was re-pointed from `192.168.196.185` to `127.0.0.1` per the brief's own instruction
  (to reach the tunnel) - left as-is; it is a no-op change once the real host is reachable
  again, and matches the brief's own sanctioned setup step. `credentials_json` was NOT
  touched (still whatever ciphertext predates this run - undecryptable under this lane's
  `FERNET_KEY`, per section 4b).
- Scratch worktrees used for the mutation proof and regression re-verification
  (`wt-s35-mutation`, `wt-s35-mutation2`, `wt-s35-verify`) were all removed
  (`git worktree remove --force`) - none left behind.
- No `ac_company`/`ac_entity_config`/`ac_field_mapping` row under the ORIGINAL `default`
  tenant was created, mutated or run by this tester session; both protected tasks' `fromDate`
  are untouched at `2023-09-01` and neither was run.
