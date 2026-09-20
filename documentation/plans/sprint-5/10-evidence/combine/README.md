# Evidence: Combine rows (AC-10-82, AC-10-83) - BLOCKED

Run date: 2026-09-20 (UTC). Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`.
Tenant/user: `default` tenant, `demo@example.com` (Admin). Company `Sorento SRT S40`
(`AED_SORENTO`, this lane's `db1`).

## Precondition check (real clicks, from the sidebar)

AutoCount -> Companies -> `Sorento SRT S40` -> Entities tab -> **Add entity** picker.

The picker (a searchable SearchSelect, confirmed empty free-text) offers exactly:
`Customer, Warehouse, Product category, Brand, Unit of measure`. **"Stock balance" is not in the
list.** Screenshot `01-add-entity-no-stock-balance-1280.png`.

Cross-checked read-only against the running backend (no writes):

```
GET /autocount/presets/product?companyId=<db1>       -> 1 row (the product preset, path
                                                          /itembypage, keyFields ["ItemCode"])
GET /autocount/presets/stock_balance?companyId=<db1>  -> [] (empty - no preset registered)
```

This means `ENTITY_STOCK_BALANCE` / `CanonicalStockBalance` / the stock HTTP preset (AC-10-39,
AC-10-40, AC-10-41) are **not present in this lane's checked-out `service_backend`** - there is no
way, through real clicks or otherwise, to create a Stock balance task on this build, so the
"Combine rows" Source-tab section (AC-10-82) and its pre-filled drop-rule journey (AC-10-83) have
no entity to attach to. This was not something a hand-made DB row could safely stand in for (it
would fake the Definition-of-Done grant/registration sweep this plan requires), so no such
workaround was attempted.

## Verdict

- **AC-10-82 [FE]** BLOCKED / NOT VERIFIABLE in this lane - the "Combine rows" section cannot be
  reached because no entity in this build carries a `combine` config or a UI path to add the
  Stock balance entity. Not a FAIL of the FE code (the section may well exist for an entity that
  does carry `source_config.combine`) - it is a precondition gap. Escalate to the plan owner: is
  Group E (`sprint-5/10-autocount-pull-review.md` AC-10-39..46) merged into this lane's backend?
  If not, this lane needs a rebase/merge before S2 evidence for the combine slice can be recorded.
- **AC-10-83 [E2E]** BLOCKED for the same reason.
- **AC-10-84 [T]** (live-replay numbers) out of scope for this tester pass regardless (T-tagged,
  not FE/E2E), but also blocked by the same backend gap.

No fabricated screenshots were produced for a flow that does not exist in this build. If the
combine FE work is in fact present but gated behind something else (a company flag, a different
connection type), that should be named explicitly in the plan or the coder's handoff notes -
right now the SearchSelect option list is the ground truth and it does not include Stock balance.
