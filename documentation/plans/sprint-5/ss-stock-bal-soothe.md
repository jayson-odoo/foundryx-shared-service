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
| `pagePauseSeconds` | 1 | Pause between two page requests of one serial walk (main path and every lookup), never before page 1. 0 = off, max 10. A connection saved before this lane gets 1. |
| `lookupCacheMinutes` | 60 | A scheduled (`incremental`) `stock_balance` run reuses the `/itembypage` and `/itemuombypage` rows of the last verified walk for this long (BL-SS-353). Manual / reconcile runs and every other entity read them fresh. 0 = off, max 1440. |

- The cache holds only fully verified lookup walks, lives in the worker process (no table), and
  notes "Reused the 'item' lookup ... read N min ago" on the run's activity trail.
- An opt-in concurrent walk (`maxConcurrentPages` > 1) is unchanged and never pauses.
- Keep `pagePauseSeconds` at or below ~1.5 s: a 70-page walk at ~2.3 s per page plus 69 pauses
  must still finish inside the 5-minute tick, or the next tick is skipped by the overlap guard.

## Acceptance

- AC-1 [BE][T] the walker pauses `pagePauseSeconds` between pages, never before page 1; 0 = no pause.
- AC-2 [BE][T] a second scheduled stock run inside `lookupCacheMinutes` makes no lookup page
  requests, its rows still carry the lookup fields, and the walk still verifies; after the TTL it
  walks them again; manual runs and other entities never use the cache; 0 = off.
- AC-3 [BE][T] the two connection fields show for the open REST wrapper only, validate on save
  (range, number) and default when blank; no skip setting exists.
- AC-4 [BE][T] every scheduled stock run walks all balance pages.

Tests: `service_backend/tests/test_ss_stock_bal_soothe.py`.
