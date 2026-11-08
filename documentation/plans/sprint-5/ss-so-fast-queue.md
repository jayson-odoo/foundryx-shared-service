# SS-SO-FAST-QUEUE - plan card

Lane: AutoCount SO edits reach the CRM ~5 min late (p90). Cause (owner prod probe 1-8 Nov):
the shared `jobs` queue (`docker-compose.yml` `worker_jobs -c 2`) is ~82% busy in working hours,
mostly with Sorento `stock_balance` (~220 s every 5 min) and Mocha `product` (~900 s, 41% failed).
A document incremental waits behind them (SO queue wait 11.6 s p50 / 231 s p90), and because a
PENDING job counts as in flight (`scheduler.py` overlap guard -> `first_unfinished`), ~38% of SO
ticks were skipped.

## 1. Queue split

| Queue | Worker service | Concurrency | Carries |
|---|---|---|---|
| `jobs_docs` (new) | `worker_jobs_docs` (new) | `-c 2` | `autocount_sync` with `mode=incremental` for document entities: sales_order, purchase_order, shipping_order, goods_received_note, cancel_sales_order, cancel_purchase_order, consignment, consignment_return, invoice, cash_sale, credit_note, debit_note |
| `jobs` (unchanged) | `worker_jobs` | `-c 2` | everything else: masters, product, stock_balance, ar_outstanding, every reconcile, every manual "Run now", previews, pull snapshots, storage migration |

- Routing is per JOB, not per type: `JobHandlerDef` gains an optional `queue_for(job)` resolver;
  `JobService.enqueue` asks it first, then falls back to the type's static `queue`.
- A document reconcile (8-10 min) stays on `jobs` so it can never block the next SO incremental.
- `ops_liveness.KNOWN_QUEUES` gains `jobs_docs` (per-queue beat ping + stale signal).
- `worker_jobs_docs` also registers every task (same image, same app), so a message on either queue runs.

**Resource estimate (SS host):** one more Celery prefork service, 1 parent + 2 children, the same
image as `worker_jobs`: ~+450-600 MB RSS (each child ~150-200 MB after module boot), CPU near idle
(I/O-bound: AutoCount DB/HTTP, Sorento HTTP, Postgres). Postgres: +2 worker connections (+ source
pool, unchanged per job). If memory-tight: `-c 1` on `worker_jobs_docs` still removes the wait
(one SO run is 4.7 s p50).

## 2. Overlap guard

Keep the per-task guard and keep counting a PENDING job as in flight (otherwise every tick behind
a slow worker queues one more duplicate job). Make it explicit: a tick skipped behind a QUEUED job
writes its own skip reason, "queued for N s, waiting for a worker", distinct from "still running".
With the split, a queued SO job should almost never exist.

## 3. Queue wait visible

`ac_sync_runs.queue_wait_ms` (new nullable column, module migration, no backfill needed - historic
runs show "-") = job `started_at - created_at`, stamped when the run starts. Exposed on the run
history wire (`queueWaitMs`) and in the run-history table ("Queue wait").

## 4. Defaults / config

- `DEFAULT_INCREMENTAL_MINUTES` for document presets -> 1 (Mocha SO is on the old 15 default).
- Reconcile "Daily at" gets a timezone: `source_config.reconcileTimezone` (IANA). New tasks default
  `Asia/Kuala_Lumpur`; a task without the key keeps today's UTC meaning (no silent 8 h shift on
  deploy). The editor shows the time with its zone.
- Owner-run admin script `python -m modules.autocount.scripts.move_reconciles_off_hours`
  (dry-run by default, `--apply` to write, idempotent): sets every Daily-at task to
  `Asia/Kuala_Lumpur`, staggers reconciles 02:00-05:00 MYT (one company's tasks spaced out,
  documents before masters), sets document incrementals to 1 min, re-arms `next_*_at`.

## 5. Mocha product + stock_balance

Needs prod facts I cannot reach from the sandbox (see questions 4-5). Code-side candidates under
investigation: product walk exceeding budget/timeouts on the open REST API, walk not verifying
when the population changes mid-walk.

## Deploy

1. Merge -> release. Module migration adds `ac_sync_runs.queue_wait_ms` (additive, nullable).
2. `docker compose up -d worker_jobs_docs` (new service) alongside the usual worker restart.
3. Owner runs the admin script (dry-run, read, then `--apply`).

## Rollback

Stop `worker_jobs_docs` and set `AUTOCOUNT_DOCS_QUEUE=` (empty) -> routing falls back to `jobs`;
any message already on `jobs_docs` drains once the worker is started again, or after the
undispatched sweep (150 min) fails it and the next tick re-enqueues. The column is additive and
harmless. Script changes are plain config values; the dry-run prints the old values to restore.
