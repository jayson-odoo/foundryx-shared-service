# Sprint 5 / 11 - S0 baseline (lane + docs + probes)

Lane `s41`, branch `sprint-5/11-autocount-extraction-speed`, worktree
`.claude/worktrees/s41`, forked from `origin/main` (`bf54663d`, same base as the `s40` rehearsal
lane it was cloned from). Backend port `8010`, frontend port `3010`, DB `foundryx_service_s41`.
No server was started for this slice (no probe in this plan required one); ports 8010/3010
confirmed free throughout.

## (a) AC-11-13 - the mandated probe: `page=2&pageSize=1000` on db1, 5x serial

Raw file: `ac-11-13-probe.txt`. `https://hapi.sorento.cc.cd/api/db1/itembypage?page=2&pageSize=1000`,
`curl/8`, no auth header (db1 is an `auth=none` connection), `--max-time 40`, requests spaced 5 s.

| Attempt | Timestamp (UTC) | Status | Bytes | Latency (s) |
|---|---|---|---|---|
| 1 | 2026-09-21T01:37:22Z | 200 | 659,974 | 18.31 |
| 2 | 2026-09-21T01:37:45Z | 200 | 659,974 | 22.37 |
| 3 | 2026-09-21T01:38:13Z | 200 | 659,976 | 19.47 |
| 4 | 2026-09-21T01:38:37Z | 200 | 659,976 | 17.94 |
| 5 | 2026-09-21T01:39:00Z | 200 | 659,976 | 23.57 |

**Result: does not reproduce.** All 5 attempts returned 200 with a consistent payload size
(~660 KB, the full 1000-row page) and latency in the 18-24 s band already measured for db1's
per-page cost. Per AC-11-13's own instruction ("if it reproduces, concurrency stays at N=1 for
that book...") this does NOT gate db1 down - the finding was a single observation (BL-SS-251,
dated the same day, 2026-09-21) that this probe could not reproduce a few hours later. Recorded
as additional evidence on the existing backlog row rather than closing it: a single-occurrence
4xx on a vendor wrapper of unknown internals is not disproven by one clean follow-up run, and the
backlog row already asks the finding be carried to the vendor beside the BL-SS-219 latency
numbers.

## (a-extended) The brief's wider matrix: pages 1-3 x pageSize {1000, 500} x 3 reps, spaced 5 s

Raw file: `vendor-matrix-probe.txt`. Same endpoint/host/db, `page` and `pageSize` varied.

| page | pageSize | rep 1 | rep 2 | rep 3 |
|---|---|---|---|---|
| 1 | 1000 | 200 / 657,474 B / 15.48s | 200 / 657,474 B / 15.34s | 200 / 657,474 B / 15.85s |
| 1 | 500  | 200 / 326,345 B / 8.68s  | 200 / 326,345 B / 8.32s  | 200 / 326,345 B / 8.60s |
| 2 | 1000 | 200 / 659,976 B / 17.52s | 200 / 659,976 B / 17.93s | 200 / 659,976 B / 18.07s |
| 2 | 500  | 200 / 331,228 B / 9.29s  | 200 / 331,228 B / 8.49s  | 200 / 331,228 B / 8.41s |
| 3 | 1000 | 200 / 649,558 B / 18.27s | 200 / 649,558 B / 18.88s | 200 / 649,558 B / 18.61s |
| 3 | 500  | 200 / 332,991 B / 9.01s  | 200 / 332,991 B / 9.08s  | 200 / 332,991 B / 8.93s |

18/18 requests: 200, zero errors, zero timeouts. Byte size is stable per (page, pageSize) across
all 3 reps (no drift, no partial pages), and latency scales roughly with pageSize (500-row pages
cost about half of 1000-row pages at every page tested), consistent with a page-proportional
server cost rather than a page-position effect. No evidence in this run of a page-specific
anomaly at page 2 or anywhere else in pages 1-3. Total probe wall time (both runs): ~7 minutes,
23 requests, all against `db1`/`AED_SORENTO` - `db2` was not probed here (BL-SS-251 names db1
only) and this plan's S6 concurrency work has not started, so no production behaviour was
touched.

## (b) Serial baselines - cited, not re-run

Per the plan's explicit instruction ("cite, do not re-run a 9-minute build"), the following are
carried from `documentation/plans/sprint-5/10-evidence/live-replay/README.md` (same repo,
sprint-5/10 S6 live replay, lane `s40`, backend `:8009`, DB `foundryx_service_s40`):

| Book | Entity | Status | Records | Duration | Source line |
|---|---|---|---|---|---|
| db1 (SRT, `AED_SORENTO`) | product | ready | 11,840 | **9m 0.1s** (540,111ms) | README.md:22, :209 |
| db1 (SRT, `AED_SORENTO`) | stock_balance | ready | 12,133 | **8m 0.8s** (480,810ms) | README.md:23, :231 |
| db2 (MCH, `MOCHA`) | product (Run 1) | failed (`SOURCE_PAGE_FAILED`) | 0 | 3m 4.9s (to failure) | README.md:24 |
| db2 (MCH, `MOCHA`) | stock_balance (Run 1) | failed (`ENRICH_FAILED`) | 0 | 3m 5.5s (to failure) | README.md:25 |
| db2 (MCH, `MOCHA`) | product (Run 2, after AC-10-85 sizing fix) | ready | 3,445 | **20m 18.5s** | README.md:346 |
| db2 (MCH, `MOCHA`) | stock_balance (Run 2) | ready | 3,165 | 20m 31.1s | README.md:347 |

**Discrepancy flagged, not silently corrected:** this plan's own section 1 text states "the
measured full build is 9m00s (db2: 8m01s for 3,445 rows)". The evidence file has no db2
measurement of 8m01s for 3,445 rows anywhere - db2/MCH's product build (3,445 rows) is measured
at **20m 18.5s** (Run 2, after the AC-10-85 connection-sizing fix landed; Run 1 never completed
at all, failing at ~3m5s). The figure "8m 0.8s" that DOES exist in the evidence belongs to
**db1's stock_balance** build (12,133 rows), not db2's product build. Read literally: db1 has
TWO measured full builds (product 9m0.1s, stock_balance 8m0.8s); db2 has one completed build per
entity, at 20m18.5s / 20m31.1s. Carrying forward the plan's own parenthetical without comment
would misstate the db2 number by a factor of ~2.5x; flagging it here for the plan/UAC owner to
correct in the next revision of section 1's prose (not changed unilaterally in this S0 commit,
since the brief's instruction was to cite, not edit, the plan text).

**AC-11-12's 50%-of-9m00s exit criterion** is unaffected by this discrepancy - it names the db1
serial baseline (9m00s) explicitly and correctly.

## (c) Slowest single Postgres statement of a full `SRT` build (input to AC-11-85)

**Not measurable on this lane today.** Checked the native Postgres instance both lanes share
(`/opt/homebrew/var/postgresql@17`, native, no Docker):

- `pg_stat_statements` is **not installed** on `foundryx_service_s40` (`SELECT extname FROM
  pg_extension` lists only `plpgsql`).
- `shared_preload_libraries` is empty (checked as the `foundryx` role - denied,
  `pg_read_all_settings` required - and again as the OS superuser `tehjayson`, confirmed empty
  for both `foundryx_service_s40` and `postgres`).

Enabling it requires: (1) add `shared_preload_libraries = 'pg_stat_statements'` to
`/opt/homebrew/var/postgresql@17/postgresql.conf`, (2) **restart** the Postgres server (a
config-file reload is not enough for `shared_preload_libraries`) - this is the ONE native
Postgres instance every worktree/lane on this machine shares, so a restart is a real
cross-lane action, not taken unilaterally in this slice, (3) `CREATE EXTENSION
pg_stat_statements;` in the target database, (4) run a full `SRT` product build, then
`SELECT query, calls, max_exec_time, mean_exec_time FROM pg_stat_statements ORDER BY
max_exec_time DESC LIMIT 20;`.

A lighter-weight alternative that avoids the extension (but still needs a reload, not a
restart) is `log_min_duration_statement` - already the pattern used in production
(`docker-compose.yml` line 102, `-c log_min_duration_statement=500` on the deployed `db`
service) - set to a low threshold, run the build, then grep the slow-statement log. Not applied
here for the same shared-instance reason.

AC-11-85 itself already anticipates this: "the row-hash upsert and the `all_hashes` read are
the candidates... **verified in S1**" (UAC line 366-374). This measurement is S1's job, not S0's;
this section records why it could not be done here and exactly what S1 needs to do it (own DB
instance, own Postgres restart, or a `log_min_duration_statement` reload on the S1 lane's own
Postgres if one is stood up independently).

## (d) `worker_workflow` config facts (no `-c`, no time limits, prefetch default)

**`docker-compose.yml` line 158** (`worker_workflow` service command):
```
command: ["celery", "-A", "app.workflow_engine.worker", "worker", "-Q", "workflow", "--loglevel", "info"]
```
No `-c` flag anywhere on this line - Celery's prefork pool defaults to one worker process per
CPU core; on the 1-vCPU production host (per the plan's narrative) that is exactly one
`ForkPoolWorker`, confirming the plan's "so there is exactly ONE ForkPoolWorker" claim.

**`service_backend/app/workflow_engine/worker.py` lines 25-38** (the Celery app + its ONLY
`conf.update` call):
```python
celery_app = Celery(
    "workflows",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=False,
    broker_connection_retry_on_startup=True,
    task_default_queue="workflow",
)
```
No `worker_prefetch_multiplier` (Celery default: 4), no `task_soft_time_limit` /
`task_time_limit` set anywhere in this file (grepped: zero matches for `prefetch`, `time_limit`
in the whole file). Confirms the plan's claims 1 and 2 in section 2.6 exactly: a hung task holds
its slot forever (no limit), and the default prefetch of 4 lets a blocked child hold several
beat messages in its buffer.

**`service_backend/app/jobs/worker.py` lines 8-20** (`jobs.run`, the task that hung in the
2026-09-21 incident):
```python
from app.workflow_engine.worker import celery_app


@celery_app.task(name="jobs.run")
def run_job_task(job_id: str) -> None:
    ...
```
`jobs.run` is registered on the SAME `celery_app` as every workflow task - no dedicated queue
(`task_routes`), no per-task time limit. It shares the single `workflow` queue and the single
`ForkPoolWorker` with `workflows.run_due`, `status.reevaluate_time_based`,
`autocount.etl_sweep`, and every other 60 s beat tick registered in `worker.py`'s
`beat_schedule` (lines 43-90) - exactly the starvation shape the plan's incident narrative
describes.

**`service_backend/app/database.py`** (supplementary, confirms plan claim 3): no
`connect_args`, `statement_timeout`, `lock_timeout` or `idle_in_transaction_session_timeout`
anywhere (grepped, zero matches) - worker sessions have no bound today, matching the plan's
"the vendor client... carry their own timeouts... the hang is something that has none" claim.

## What could not be done, and why

- **(c)** the slowest-statement measurement itself: `pg_stat_statements` absent, enabling it
  needs a shared-Postgres-instance restart not appropriate to take unilaterally mid-session
  with other lanes live on the same server. Requirements listed above for S1 to pick up.
- No server was started (not needed for any S0 item); no `[E2E]` evidence run in this slice
  (S0 has none).
- The db2/`MCH` probe (page=2 style) was not repeated - BL-SS-251 names db1 only, and the
  brief's matrix instruction named db1 (`hapi.sorento.cc.cd/api/db1`) explicitly.

## Housekeeping

- Backend `.env`: `DATABASE_URL=...foundryx_service_s41`, `API_PORT=8010`,
  `FRONTEND_URL=http://localhost:3010`. Frontend `.env.local`: 8010/3010 pair. `.venv`
  symlinked to the main checkout's `service_backend/.venv`.
- `foundryx_service_s41` created via `createdb -O foundryx foundryx_service_s41` (the
  `foundryx` role cannot `CREATE DATABASE`), then `python -m scripts.bootstrap_db` - migrated
  to a single Alembic head, seeded (2 tenants; `app_autocount`/`app_ideation`/`app_meetings`/
  `app_omnichannel` schemas present), re-run confirmed idempotent (no errors on a second pass).
- Backlog rows BL-SS-244 through BL-SS-252 appended to `documentation/backlogs/backlog.md`,
  confirmed 244 was the next free `BL-SS-` id (existing max in this branch's backlog.md: 243,
  from sprint-5/10; grepped the whole plans tree for BL-SS-244..252 before appending - only this
  plan's own text referenced them, no collision).
