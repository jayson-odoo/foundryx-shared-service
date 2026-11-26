# SS-STOCK-BAL-SOOTHE - plan card (as built)

Lane: the 5-minute `stock_balance` push walks `/itembatchbalqtybypage` (70 pages at 1000 rows,
~69.3k rows on db1) plus `/itembypage` + `/itemuombypage` (~12 pages each) back to back, every
5 minutes. The owner sees AutoCount traffic spike on every run. Goal: same freshness for users,
less load, no bursts. The 5-minute schedule stays.

## Owner rulings (26 Nov)

- Page size stays 1000 (vendor recommendation; already the default and the wrapper's cap).
- No skipping: every scheduled stock run walks the balances in full. Internal transfers,
  write-offs and adjustments move stock without any DO/GRN/SO/PO, so "no document changed" is
  never a reason to skip.

## Settings (per open-REST connection, generic connection form, both ON by default)

| Key | Default | Effect |
|---|---|---|
| `pagePauseSeconds` | 1 | Pause between two page requests of a serial walk of the task's MAIN endpoint (the 70-page balance walk), never before page 1. Lookup walks are not paused (they run about once an hour now, and a cache-miss run must still fit the 5-minute tick). 0 = off, max 10. A connection saved before this lane gets 1. |
| `lookupCacheMinutes` | 60 | A scheduled (`incremental`) `stock_balance` run reuses the `/itembypage` and `/itemuombypage` rows of the last verified walk for this long (BL-SS-353). Manual / reconcile runs read fresh AND refresh the cache, so "Run now" picks up a new item or UOM rate for the next scheduled runs too. Every other entity reads fresh. The age is checked against the CURRENT setting, so lowering it applies on the next run. 0 = off, max 1440. |

- The cache holds only fully verified lookup walks, lives in the worker process (no table), and
  notes "Reused the 'item' lookup (N row(s)) read N min ago" on the run's activity trail; entries
  older than a day are swept on the next store.
- An item created inside the TTL shows its stock without the lookup fields (base UOM) until the
  cache refreshes (or a manual run); the existing "N row(s) had no match" note names it.
- An opt-in concurrent walk (`maxConcurrentPages` > 1) is unchanged and never pauses.
- Keep `pagePauseSeconds` at or below ~1.5 s: a 70-page walk (+ a lookup walk on a cache miss)
  plus 69 pauses must still finish inside the 5-minute tick, or the next tick is skipped by the
  overlap guard.

## Acceptance

- AC-1 [BE][T] the main walk pauses `pagePauseSeconds` between pages, never before page 1, never
  on a lookup walk; 0 = no pause.
- AC-2 [BE][T] a second scheduled stock run inside `lookupCacheMinutes` makes no lookup page
  requests, its rows still carry the lookup fields, and the walk still verifies; after the TTL it
  walks them again; lowering the TTL applies on the next run; a manual run reads fresh and
  refreshes the cache; other entities never use it; 0 = off.
- AC-3 [BE][T] the two connection fields show for the open REST wrapper only, validate on save
  (range, number) and default when blank; no skip setting exists.
- AC-4 [BE][T] every scheduled stock run walks all balance pages.

Tests: `service_backend/tests/test_ss_stock_bal_soothe.py`.
