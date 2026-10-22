# Plan 34 - No transaction held open across network I/O (app_autocount)

Lane: SS-IDLE-TXN-LEAK (crew), branch `crew/ss-idle-txn-leak`, size S (no behaviour the owner sees).
Status: BUILD.

## Why

The prod deploy of #128 (run 39763255387, attempts 1 and 2) aborted: module migration 0031 hit
`lock_timeout` because the database held sessions `idle in transaction` on `app_autocount`
(pid=96 xact_age 00:07:36, pid=91 00:00:30, client_addr 172.21.0.2, application_name empty,
AccessShareLock on `ac_company`(+pkey), `ac_entity_config`(+pkey), ...). New ones keep appearing,
so the running code produces them. An `ALTER TABLE` needs an AccessExclusiveLock, so any open
read transaction on the table blocks it.

## Step 0 - audit (22 Oct, read-only)

No session is ever left unclosed: every `SessionLocal()` in a Celery task or the job runner is
closed in a `finally` (`app/workflow_engine/worker.py:177-576`, `app/jobs/worker.py:61`); the
request session is `app/database.py:get_db`. The holds are READ transactions left open across
slow network I/O inside one unit of work. Every `ORM` read autobegins a transaction; the next
commit can be minutes away, after a vendor walk. Ranked:

1. `modules/autocount/sync.py:436-472` - `run_autocount_sync` (non-paged): after the log commit,
   `config.source_impl` re-SELECTs `ac_entity_config`, `ac_company`, `connections`; then
   `source.fetch_changes` runs the whole vendor HTTP walk (retries, 90 s timeouts) before any
   commit (`http_source/source.py:1205`, `sync.py:861`). 30 s to 10+ min, every scheduled tick.
   This matches pid=96 (7.5 min, `ac_company` + `ac_entity_config`).
2. `sync.py:2952-2975` - pull snapshot: same shape; `_beat_and_check` (2944) only SELECTs.
3. `sync.py:1768` / `sql_source/source.py:2011,1419` - paged `sql_db`: reads held across the
   external SQL header and line queries, every page.
4. `preview_job.py:365` -> `etl_service.py:2558-2627` - preview: reads held across the Sorento
   contract probe, the source walk and `sink.dry_run`.
5. `services/sync_service.py:659,1117` - `auto_push` / `_auto_push_deletes`: `ac_company`
   read held across the Sorento contract probe (`company_service.py:971`) and delete batch.
6. `doc_feed/runner.py:503,673,969`, `doc_feed/snapshot.py:166`, `doc_lookup/job.py:177` -
   `ac_company` read held across vendor day GETs and Retry-After sleeps.
7. `sync_service.py:815` - `ac_staged_record` re-reads held across `write_batch` chunks.
8. `sync.py:1489` - fingerprint sweep: `ac_watermark` read held across external SQL.

API request paths: see "API audit" below (filled in from the second audit).

## Design

Fix once, at the session layer (`app/database.py`), and call it from the few network seams,
not by sprinkling `db.commit()` through `sync.py`:

- **Read-transaction registry.** A `Session` `after_begin` listener records every session whose
  transaction autobegan (thread-local weak set); `after_transaction_end` forgets it. A
  `before_cursor_execute` listener marks the connection's transaction as "wrote" for any
  statement that is not a plain `SELECT` (DML, `SAVEPOINT`, `SELECT ... FOR UPDATE/SHARE`).
- **`release_read_transactions()`** ends (commits) every registered transaction in this thread
  that (a) autobegan (never an explicit `begin()` / `begin_nested()` block), (b) executed no
  write, (c) has no pending ORM changes (`new` / `dirty` / `deleted`). A transaction with a
  write is left alone: committing it would split someone's unit of work. Committing a read-only
  READ COMMITTED transaction changes no data and no visibility; loaded objects expire and reload
  on next access.
- **Seams** (call `release_read_transactions()` immediately before the slow I/O):
  vendor HTTP (`http_source/client.py` `HttpApiClient.get`, `client.py` token client),
  Sorento HTTP (`sinks_sorento.py`, `sorento_provider.py`), doc-feed vendor
  (`doc_feed/vendor.py`), and every statement on an external SQL source engine
  (`sql_source/runtime.py` engine `before_cursor_execute`).
- **application_name** per process on the app engine `connect_args`
  (`foundryx-api`, `foundryx-worker:<queues>`, `foundryx-beat`, `foundryx-<script>`), override
  with `DB_APPLICATION_NAME`. DEPLOY.md lock report then names the owner.
- **idle_in_transaction_session_timeout** (proposal only, owner applies): 15 min
  (= 3 x `AUTOCOUNT_SINK_TIMEOUT_SECONDS` 300 s, the longest legit write-transaction hold
  across a Sorento POST). Where: `ALTER ROLE foundryx IN DATABASE foundryx_service SET
  idle_in_transaction_session_timeout = '15min';` (covers api, workers, beat, psql), or the
  existing per-worker env `WORKER_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_SECONDS=900`
  (`docker-compose.yml:188,215`). Documented in DEPLOY.md; no prod change in this lane.

## Tests (red first)

- `tests/test_db_read_txn_release.py` (sqlite, runs in CI): release ends a read-only autobegun
  transaction; leaves a flushed write, pending changes, `begin()` and `begin_nested()` alone;
  each seam releases before its request (stub transport asserts `not db.in_transaction()`);
  a real `run_autocount_sync` HTTP walk never reaches the vendor with an open read
  transaction; `application_name` per process.
- Same file, Postgres-only (skips without a reachable Postgres, CI has none): a read leaves the
  session `idle in transaction` in `pg_stat_activity` (control); at the seam the session is
  `idle`.

## DoD (size S)

Red commit alone first (`test(red):`), red-proof + kill-proof crew-notes, reviewer seat, CI
green. No UI, no migration, no permission, no backfill (no new column).
