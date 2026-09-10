# AC-07-12 - live replay of `backfill_sales_order_ref` on `foundryx_service_s36`

Lane DB `foundryx_service_s36` (Postgres, cloned from the user's 2026-09-08 dump), module
`autocount`, stamp before this run: `0018_autocount_line_linkage`. Ran the REAL
`app.module_platform.migrations.run_module_migrations(engine, "autocount")` (the same
orchestrator `bootstrap_db`/module install uses) against the live database - not a
simulation, not SQLite.

## Result: stamp advanced to `0019_autocount_so_ref`

```
new stamp: 0019_autocount_so_ref
```

## What actually happened - and a deviation from the UAC's assumed `ac_sim` outcome

**PO/SPO: fully untouched, as required.** 53/53 `purchase_order`/`shipping_order`
`ac_entity_config` rows compared byte-for-byte before/after (query text + `result_columns`) -
zero changes.

**Every `sales_order` config (50 total across every company/tenant in this DB) landed in the
"customised" branch (AC-07-09): query left byte-untouched, a DISABLED `Ref -> ref` header row
created, one WARNING logged naming the config id.** Zero configs auto-swapped to the NEW
preset text. This includes BOTH companies the UAC's live-facts section names:

| Company | config id | query md5 (before == after) | ref row after |
|---|---|---|---|
| `Sorento` (`8bc3496b-8aea-4097-bfc2-2ed3c8d212bf`, the production `AED_SORENTO` task) | `a538e0cb-d653-44e3-96f4-ab0b91c624b1` | `2605221ed510ccf8a3520dd58b068e63` | DISABLED (`is_enabled=False`), `source_path='Ref'` |
| `ac_sim` (`8a1ac730-8666-4892-829c-3b968301885f`, `SIM`) | `f5875900-09b1-45ba-bc98-5cf90e319d64` | `68f2a801415373cce92bca298cfc1dad` | DISABLED (`is_enabled=False`), `source_path='Ref'` |

The UAC (AC-07-12) expected `ac_sim`'s query to auto-swap to the NEW preset text with an
ENABLED `Ref -> ref` row ("the `ac_sim` SO task's query contains `h.Ref AS Ref` ... and has an
enabled `Ref -> ref` row"). **That does not happen against this lane's actual data, and the
byte-identity backfill is working exactly as designed** - `ac_sim`'s stored query is not the
MSSQL preset text at all:

```sql
-- ac_sim's ACTUAL stored source_config.query (Postgres dialect, hand-adapted):
SELECT h.DocKey AS DocKey, h.DocNo AS DocNo, c.AutoKey AS DebtorAutoKey, h.SalesAgent AS
SalesAgent, h.DocDate AS DocDate, h.UDF_DelDate AS RequestedDeliveryDate, h.Note AS Note,
h.Cancelled AS Cancelled, h.DebtorCode AS DebtorCode, h.DebtorName AS DebtorName,
h.LastModified AS LastModified, l.LineCount AS LineCount, l.QtySum AS QtySum,
l.TransferedSum AS TransferedSum, l.SubTotalSum AS SubTotalSum, l.MaxDtlKey AS MaxDtlKey
FROM ac_sim.dbo.SO AS h LEFT JOIN ac_sim.dbo.Debtor AS c ON c.AccNo = h.DebtorCode
LEFT JOIN LATERAL (SELECT COUNT(*) AS LineCount, SUM(d.Qty) AS QtySum,
SUM(d.TransferedQty) AS TransferedSum, SUM(d.SubTotal) AS SubTotalSum, MAX(d.DtlKey) AS
MaxDtlKey FROM ac_sim.dbo.SODTL AS d WHERE d.DocKey = h.DocKey AND d.ItemCode IS NOT NULL)
AS l ON true
```

Root cause: `ac_sim`'s connection is `dbType: postgresql` (confirmed via
`connections.config_json`), so whoever authored this task's query by hand translated
`OUTER APPLY` -> `LEFT JOIN LATERAL ... ON true` (Postgres has no `OUTER APPLY`) and dropped
the `d.Qty IS NOT NULL` line-fingerprint filter - a structurally different, Postgres-valid
statement, never byte-identical to `_OLD_SO_HEADER_QUERY`/`_NEW_SO_HEADER_QUERY` (both MSSQL
dialect, `{database}.dbo.SO` / `OUTER APPLY`). There is no dialect-translation layer anywhere
in `modules/autocount/` (grepped `OUTER APPLY`/`LATERAL`/`dialect ==` across the module) - the
byte-identity check is, by design (plan D4: "no SQL splicing of customised queries"), a LITERAL
comparison, and correctly classifies this as a customised query it must never rewrite.

**This is not a bug in the backfill** - `test_backfill_leaves_a_customised_query_alone_and_
disables_the_ref_row_without_it` (AC-07-09) pins exactly this behaviour with a synthetic
customised query, and it passes. It IS a gap in the UAC's assumed live-fact: `ac_sim`'s task
was never actually running the MSSQL preset text verbatim (it runs a hand-translated Postgres
equivalent), so it needs the SAME one-line operator step as the production `Sorento` task
(plan section 2.4: add `h.Ref` to the Query tab, enable the row) - arguably the SAFER outcome
for a company whose `sorento_company_code = 'SIM'` sink is real Sorento, since it now requires
the same deliberate action as `Sorento` rather than silently starting to send `ref` the moment
this migration deploys. Filed as `BL-SS-196` in the backlog (informational, not a code defect) - a future slice could
special-case a `LATERAL`-translated preset text per dialect the same way `list_mapping_presets`
does for `{database}` substitution, if `ac_sim` should track new preset columns automatically.

## Idempotency, live

A second direct call to `backfill_sales_order_ref` against the SAME (now-migrated) database:

```
second-pass touched: 0
second-pass warnings: 0
```

Matches `test_backfill_does_not_repeat_a_warning_on_a_second_pass` (AC-07-10) - zero changes,
zero repeat warnings, on real Postgres data.

## Full before/after tallies

- 103 `sales_order`/`purchase_order`/`shipping_order` `ac_entity_config` rows compared.
- 50 `sales_order` configs, ALL 50 landed the "customised, disabled + warned" branch (one
  WARNING per config, each naming its own config id - captured via a logging handler on
  `foundryx.autocount` during the real Alembic run).
- 53 `purchase_order`/`shipping_order` configs: 53/53 byte-unchanged (query text AND
  `result_columns`), confirming this lane touches SO only.
- `ac_field_mapping` rows carrying `canonical_field = 'ref'` after the run: 50, ALL
  `is_enabled = false` (`select is_enabled, count(*) ... group by is_enabled` -> `f | 50`).

## AC-07-12 verdict

- PO/SPO untouched: **PASS** (53/53 byte-identical before/after).
- `Sorento` production task: disabled row + one warning naming its config id, query
  byte-untouched: **PASS**.
- `ac_sim`: disabled row + one warning naming its config id, query byte-untouched: **DEVIATION
  from the UAC's literal wording** (expected auto-swap + enabled row) - root-caused above to
  `ac_sim`'s query being a Postgres-dialect hand-translation of the preset, never byte-identical
  to the MSSQL text the backfill compares against. The MECHANISM itself is proven correct by
  the 32 passing unit tests in `tests/test_autocount_so_ref.py` (including the byte-identical
  auto-swap path, `test_backfill_replaces_a_byte_identical_old_preset_query_with_new_text_and_
  seeds_row`, exercised against controlled synthetic data). Registered in
  `documentation/backlogs/backlog.md`.

## Reproduction

```bash
cd service_backend
.venv/bin/python - <<'PY'
from sqlalchemy import create_engine
from app.config import settings
from app.module_platform.migrations import run_module_migrations
engine = create_engine(settings.database_url)
run_module_migrations(engine, "autocount")
PY
```
