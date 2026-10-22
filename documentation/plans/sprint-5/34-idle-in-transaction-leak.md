# Plan 34 - No transaction held open across network I/O (app_autocount)

Lane: SS-IDLE-TXN-LEAK (crew), branch `crew/ss-idle-txn-leak`, size S (no behaviour the owner sees).
Status: REVIEW (round 1 addressed).

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

### API audit (request paths, same root cause)

9. `services/etl_service.py:1219-1289` and the commit -> `refresh(config)` -> `_task_view` tail of
   PUT etl-task, activate, pause, resume, delivery-mode, run: `ac_entity_config` / `ac_company`
   pkey reads held across the Sorento `/contract` probe (`company_service.py:1093,1178,1327`).
   Most frequently hit; 5-30 s per request. The exact pkey lock signature.
10. `services/etl_service.py:2068-2194` - PUT etl-task (sql_db): reads held across up to 3
    customer-DB round trips (header / line preview, wrap probe).
11. `services/sync_service.py:1353-1369, 1248-1287` - approve / preview: reads held across
    `write_batch` / `dry_run` chunks and the contract probe.
12. `etl_service.py:3034,3051,3128`, `doc_feed_service.py:154,234`, `company_service.py:1654-1871`
    - activate / delivery-mode / doc-feed GET+PUT / company create: probes after reads.
13. No never-closed or module-level session; no StreamingResponse / BackgroundTasks; `get_db`
    closes after the response is sent (FastAPI 0.139 default), so even a clean read stays open
    through response transmission (short).

## Design

Fix once, at the session layer (`app/database.py`), and call it from the few network seams,
not by sprinkling `db.commit()` through `sync.py`:

- **Read-transaction registry.** A `Session` `after_begin` listener records every session whose
  transaction autobegan in a `ContextVar` (immutable tuple; each entry pinned to its thread and
  to a per-transaction token in `session.info`); `after_transaction_end` forgets it. Per
  context, not per thread: the API runs endpoint, serialization and `get_db` close as separate
  threadpool hops on shared pool threads. A `before_cursor_execute` listener marks the
  connection as "wrote" for any statement that is not a plain `SELECT` (DML, `SAVEPOINT`,
  `SET LOCAL`, `SELECT ... FOR UPDATE/SHARE`, xact advisory locks, `set_config`).
- **`release_read_transactions()`** ends (commits) every registered transaction in this thread
  that (a) autobegan (never an explicit `begin()` / `begin_nested()` block), (b) executed no
  write, (c) has no pending ORM changes (`new` / `dirty` / `deleted`). A transaction with a
  write is left alone: committing it would split someone's unit of work. Committing a read-only
  READ COMMITTED transaction changes no data and no visibility. The commit runs with
  `expire_on_commit` off, so loaded objects stay loaded (no re-SELECT that would reopen the
  transaction). A broken / invalidated session is skipped and a failing commit is logged, never
  raised into the caller's I/O.
- **Seams** (call `release_read_transactions()` immediately before the slow I/O):
  vendor HTTP (`HttpApiClient.get`, which the doc-feed vendor also uses; `AutoCountClient._post`;
  `probe_open_connection`), Sorento HTTP (`SorentoSink._call` + both `/contract` probes,
  `SorentoProvider.test`), customer DB (`open_readonly`, `SqlDbSource._attach_lines`), the
  thread-pool fan-outs on the calling thread (concurrent Sorento push / delete, concurrent page
  batch), and the doc-feed backfill Retry-After sleep.
- **application_name** per process on the app engine `connect_args`
  (`foundryx-api`, `foundryx-worker-<queues>`, `foundryx-beat`, `foundryx-<script>`; `python -m`
  entry points resolve through the package dir), override with `DB_APPLICATION_NAME`;
  `bootstrap_db` sets `PGAPPNAME` so Alembic's own engines are named too. DEPLOY.md lock report
  then names the owner.
- **idle_in_transaction_session_timeout** (proposal only, owner applies): 15 min
  (= 3 x `AUTOCOUNT_SINK_TIMEOUT_SECONDS` 300 s, the longest legit write-transaction hold
  across a Sorento POST). Where: `ALTER ROLE foundryx IN DATABASE foundryx_service SET
  idle_in_transaction_session_timeout = '15min';` (covers api, workers, beat, psql), or the
  existing per-worker env `WORKER_DB_IDLE_IN_TRANSACTION_SESSION_TIMEOUT_SECONDS=900`
  (`docker-compose.yml:188,215`). Documented in DEPLOY.md; no prod change in this lane;
  tracked as BL-SS-310.

## Tests (red first)

- `tests/test_db_read_txn_release.py` (sqlite, runs in CI): release ends a read-only autobegun
  transaction without expiring loaded objects; leaves a flushed write, pending changes,
  `begin()`, `begin_nested()`, locking selects and `set_config` alone; never touches another
  thread's or another context's session (commit spy); skips a broken session and survives a
  raising commit; each seam releases before its request (stub transport asserts
  `not db.in_transaction()`), including the concurrent fan-outs; a real `run_autocount_sync`
  HTTP walk never reaches the vendor with an open read transaction; `application_name` per
  process and bootstrap `PGAPPNAME`.
- Same file, Postgres-only (skips without a reachable Postgres, CI has none): a read leaves the
  session `idle in transaction` in `pg_stat_activity` (control); at the seam the session is
  `idle`.

## DoD (size S)

Red commit alone first (`test(red):`), red-proof + kill-proof crew-notes, reviewer seat, CI
green. No UI, no migration, no permission, no backfill (no new column).
