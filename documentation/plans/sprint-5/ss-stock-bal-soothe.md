# SS-STOCK-BAL-SOOTHE - plan card

Lane: the 5-minute `stock_balance` push walks `/itembatchbalqtybypage` (~69 pages at the
wrapper's 1000-row cap, 68.6k rows) plus `/itembypage` + `/itemuombypage` (~12 pages each)
back to back, every 5 minutes. The owner sees AutoCount traffic spike (~900 MB/s) on every
run. Goal: same freshness for users, far less load, no spikes. The 5-minute schedule stays.

## Settings (per open-REST connection, generic connection form, defaults ON)

| Key | Default | Effect |
|---|---|---|
| `pageSize` (existing) | 1000 | Already the wrapper's own cap (it silently clamps above 1000, `10-evidence/peer-message-a6.md` section 3), so a run cannot ask for bigger pages. Unchanged. |
| `pagePauseSeconds` (new) | 1 | Pause between two page requests of one walk (main path and every lookup). 0 = off. Max 10. |
| `stockSkipWhenUnchanged` (new) | yes | A scheduled stock run first reads the day lists of `/deliveryorderbyLastModified`, `/goodsreceivenotebyLastModified`, `/salesorderbyLastModified`, `/purchaseorderbyLastModified` for the days since the last full walk started. No document modified since then -> the run is skipped and recorded in the runs list as `skipped` with a plain reason. |
| `stockFullWalkMinutes` (new) | 60 | A full walk always runs when the last successful one started this many minutes ago or more, whatever the probe says. |
| `lookupCacheMinutes` (new) | 60 | `stock_balance` lookups (`/itembypage`, `/itemuombypage`) are reused from the last verified walk for this long (BL-SS-353). 0 = off. |

## Rules

- The probe never decides "unchanged" on doubt: any probe failure, a row without a readable
  `LastModified`, no earlier successful walk, more than 3 days since it, or a manual / reconcile
  run -> full walk.
- Skip only applies to `stock_balance` push runs started by the scheduler (`mode=incremental`).
- The lookup cache holds only fully verified lookup walks and is process-local (each worker process
  walks a lookup at most once per TTL).

## Acceptance

- AC-1 [BE][T] the walker pauses `pagePauseSeconds` between pages, never before page 1, not after the last.
- AC-2 [BE][T] scheduled stock run with no document change since the last full walk -> no balance
  walk, run row `mode=skipped` with reason; job DONE.
- AC-3 [BE][T] a changed document, a probe error, a manual run, or the last full walk older than
  `stockFullWalkMinutes` -> full walk.
- AC-4 [BE][T] second stock run inside `lookupCacheMinutes` makes no lookup page requests; after
  the TTL it walks them again.
- AC-5 [BE][T] the new connection fields validate (range, yes/no) and default when blank.
