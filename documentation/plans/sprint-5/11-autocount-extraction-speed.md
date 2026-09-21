# 11 - AutoCount HTTP extraction speed + non-blocking preview

UAC: `11-autocount-extraction-speed-acceptance-criteria.md` (the contract; this file is how we
meet it). Builds directly on `sprint-5/08-autocount-http-source.md` (the HTTP source) and
`sprint-5/10-autocount-pull-review.md` (lookups, combine, the snapshot store, the pull
gateway, AC-10-75/85/86/87). Branch `sprint-5/11-autocount-extraction-speed`.

## 0. Open owner rulings (answer before S1 starts; each has a planner recommendation)

1. **R1 - concurrency knob and default.** Recommended: a per-CONNECTION `maxConcurrentPages`
   (1..8, **default 1** = today's behaviour), not a module constant, because db1 and db2 have
   provably different host capacity and AC-10-85 already accepted that sizing belongs to the
   connection. Recommended production values after the S6 ramp: **db1 (SRT) N=4**, **db2 (MCH)
   N=2** - to be confirmed by the measured matrix (AC-11-12), never guessed.
2. **R2 - 429 back-off carve-out.** Recommended: at N > 1 a 429 aborts the parallel attempt,
   honours `Retry-After` (clamped 1..30 s) and restarts the walk once serially; a second 429
   fails. At N = 1 nothing changes. Alternative if refused: a 429 fails immediately at any N.
3. **R3 - does the Source tab Test share the preview job kind?** Recommended: **yes**, ONE job
   type with a `scope` of `sample` or `full`. A sample is 1 + one-per-lookup requests, each up
   to the connection's 100 s timeout, so it can already exceed Cloudflare's cut on a slow book;
   two mechanisms for one question would also mean two progress UIs and two cancel paths.
4. **R4 - stored prediction cap.** Recommended: a `full` job stores at most 500 predictions
   with `predictionsTruncated: true`, summary counts uncapped. Today's synchronous route
   returns every prediction (11,840 for SRT products), which is already a payload problem.
5. **R5 - reuse a just-walked extraction between Test, Preview and Activate?** Recommended:
   **reject** (see D8). Backlogged as BL-SS-247 with the only honest shape it could take.
6. **R6 - pending-job recovery: fail, or re-dispatch?** Recommended: **fail** (option a), plus
   the new 5-minute core beat tick and a dedicated `background_job_undispatched_after_minutes`
   setting (default 60, floor 15). Re-dispatch is rejected in D12 with its double-execution
   argument.
7. **R7 - an operator Cancel for a BUILDING pull snapshot?** Recommended: not in this plan
   (backlog BL-SS-248). The preview job gets Cancel; a build already has the orphan path.
8. **R8 - the evidence rig runs a real Celery worker** (`CELERY_TASK_ALWAYS_EAGER=false`) for
   the `[E2E]` slices, otherwise the non-blocking behaviour is unobservable. Recommended: yes.
9. **R9 - concurrency of the new `worker_jobs` service on a 1-vCPU host.** Recommended `-c 2`:
   this work is I/O bound (vendor HTTP, Sorento HTTP, Postgres), so two prefork children use
   the single core well; the cost is one extra forked image in memory. `-c 1` is the
   conservative fallback if the host is memory-tight.
10. **R10 - the bounds.** Recommended: `jobs.run` soft time limit 2 h (hard 2 h 5 min), beat
   ticks soft 300 s; worker Postgres sessions `statement_timeout=120s`, `lock_timeout=30s`,
   `idle_in_transaction_session_timeout=300s`, all confirmed against the measured slowest
   statement of a full `SRT` build before they are enabled.
11. **R11 - where the worker-liveness read lives.** Recommended: one platform-operator route
   reusing an EXISTING platform permission key (named during S1 after grepping core) - never a
   new permission key for an ops read; if no key fits, backlog it rather than mint one.

## 1. Why

The owner's words are "unbearably long". Two separate defects sit behind that, and they need
different fixes:

1. **The walk is serial.** `http_source/source.py::_walk_path` requests page N+1 only after
   page N returns. db1 answers a 1000-row page in about 21 s, so a 12-page product extraction
   spends about 4 minutes purely waiting, and the measured full build is 9m00s (db2: 8m01s for
   3,445 rows). The wrapper's own per-page latency is not ours to fix; the serialisation is.
2. **The two operator previews are synchronous HTTP requests that perform that walk.** Review
   and Activate's "Run preview" runs the FULL walk plus mapping plus a Sorento dry run inside
   one request (`EtlService.preview_task` -> `_extract_and_map` -> `fetch_changes`), and the
   Source tab's "Test" runs 1 + one-per-lookup requests inside another. Production sits behind
   Cloudflare, which cuts at about 100 s: the browser gets a 524, the server keeps working, and
   the task is later stamped `lastPreviewAt` - so the operator sees an error and then, after a
   reload, "Preview passed". That is the worst possible shape: slow AND lying.

A third, smaller gap belongs with them: AC-10-87's `progress` hint was specified and never
built (no `pagesDone` symbol exists in the repo), so a long build reports nothing at all, and
`BL-SS-236` claims it landed on the gateway header when it landed nowhere.

And one production incident, 2026-09-21, is added to the same change because it is the same
class of "a long job that nobody can see is a job nobody can recover": a deploy restarted the
worker while an `autocount_sync` job was queued, the Celery message was lost, the job sat
`pending` for 8+ hours, and every scheduler tick wrote a `skipped` run until the owner reset it
by hand in SQL.

## 2. Design

### 2.1 Bounded-concurrency page fetch (AC-11-01..13)

The walk keeps its exact shape; only the page-2..N loop changes.

```
page 1  -> serial, always. Establishes: envelope kind, echoed Page/PageSize/TotalPages/TotalCount.
            (this is also the only page whose result can decide whether concurrency is legal)
pages 2..TotalPages -> submitted to a ThreadPoolExecutor(max_workers=N); results collected into
            a dict keyed by REQUESTED page number; rows assembled in ascending page order.
```

**Concurrency is legal only when the server has told us the page set** (AC-11-02): a paged
envelope, `TotalPages >= 2`, and an echoed `Page` on page 1 that equals 1. Anything else (bare
array, absent `TotalPages`, absent echo, N = 1) takes the existing serial loop untouched. This
is what makes "trust the ECHOED values" (the plan-08 rule) survive: we never invent a page
count, we only parallelise a page set the server itself declared.

**Determinism is the whole game** (AC-11-04/05). Rows are ordered by requested page, never by
completion, so `_dedupe`'s first-occurrence-wins, `source_ref` minting, `row_hash`, the
watermark maximum, change detection and `content_hash` are all byte-identical to the serial
walk. The parity test (AC-11-05) is the gate: same fixture at N=1 and N=4, equal records, equal
counters, equal persisted hash map, equal snapshot `content_hash`, plus a mutation check so it
cannot pass for the wrong reason.

**Guards, one by one.** The non-advancing-page guard becomes STRONGER, not weaker: in the
concurrent path every page's echoed `Page` must equal the page requested (a server ignoring the
parameter fails on the first mismatch instead of after two requests). Shape change, non-JSON,
4xx and the row cap keep their codes and their fail-before-state position - the walk still
completes or fails entirely before a single hash, watermark or snapshot row is touched. The row
cap gains a cheap pre-flight projection (`TotalPages x echoed PageSize`) so a 200k-row endpoint
is refused before we fire N requests at it. AC-10-75's ladder is per page and unchanged; a
halving aborts the in-flight set, discards every partial result (AC-10-24) and restarts from a
serial page 1.

**Threads touch HTTP only** (AC-11-09). `httpx.Client` is thread-safe; a SQLAlchemy `Session`
is not. Worker threads do request plus parse; the draining thread fires the existing
`heartbeat` callback once per completed page, which is the callback that writes the job
heartbeat and raises `_BuildAbandoned`. This is a review hard-gate for the slice: any database
access inside the worker body is an automatic reject.

**Politeness** (AC-11-10, R2). We do not know the wrapper's capacity, and Cloudflare sits in
front of it. Three deliberate brakes: the default is 1 (nothing changes until an operator opts
in), the ceiling is 8, and a 429 at N > 1 drops the walk back to serial once with a clamped
`Retry-After` wait. The value an operator should choose is MEASURED, not guessed: S6 runs the
matrix in AC-11-12 and the chosen N goes on the connection. We deliberately do NOT build a
"measure throughput" button - the preview job's own result already reports pages, wall time and
concurrency, which is the same evidence with no new surface (see D4).

### 2.2 Preview and Test as a background job (AC-11-20..31)

One new job type, `autocount_source_preview` (`heartbeats=True`, registered like
`autocount_sync` and imported on the Celery worker path - forgetting that import leaves jobs
Pending forever, the nastiest footgun in this codebase), with two scopes:

| scope | what it runs (UNCHANGED logic) | stamps |
|---|---|---|
| `sample` | `EtlService.preview_http` (page 1 x 50 rows, plus one page per lookup, plus combine) | `result_columns`, `last_preview_at` (AC-08-20) |
| `full` | `EtlService.preview_task` (full walk, mapping, Sorento `dry_run`) | `last_preview_at`, `last_preview_failed_count` |

The two POST routes keep their paths and become 202 `{jobId, status}`; two new routes,
`GET /autocount/previews/{jobId}` and `POST /autocount/previews/{jobId}/cancel`, complete the
surface. These are session-authed internal routes with exactly one consumer (this frontend), so
no external contract moves. `POST /autocount/http/preview-columns` stays SYNCHRONOUS - it is
one request, used inline by the Lookups editor - but its client timeout is clamped to
`min(connection timeout, 45 s)` so it can never be the thing Cloudflare cuts (AC-11-29).

**One preview per task**, claimed atomically on the module's own column
`ac_entity_config.preview_job_id` with `UPDATE ... WHERE preview_job_id IS NULL`
(AC-11-23). A module may not add a partial index to core `background_jobs`, and scanning job
payloads is both racy and slow; a module-local claim column is the honest version, and it also
lets the UI re-attach after a reload. Every terminal path releases it, including the orphan
hook.

**Cancel** is the storage-migration pattern: the route sets `aborted`, the handler's per-page
checkpoint re-reads the FRESH status and stops within one page. Nothing is stamped on a
cancelled preview.

**Progress** rides the heartbeat (see 2.3) so a poll shows a stage and `pagesDone/pagesTotal`.
The result is stored in `background_jobs.result_json`, with a `full` job's predictions capped
at 500 plus `predictionsTruncated` (R4) - the summary counts stay authoritative, and the
existing `PreviewPanel` partitions what it is given.

Frontend layering is the house one and mock-first: `types/autocount.ts` ->
`services/autocount-service.{ts,mock,real}.ts` -> `hooks/use-autocount-preview-job.ts` -> the
existing tabs. The running state (stage plus page counter plus Cancel) is ONE component reused
by the Source tab, the Review and Activate tab and the snapshot detail - extended with a prop,
never cloned.

### 2.3 The progress hint, for real (AC-11-40..43)

`AC-10-87` said "written on the snapshot row as the build advances". It is written on the JOB
row instead, for one reason: the handler ALREADY updates that row once per page (the
heartbeat), so folding `progress_done` / `progress_total` / `cursor_json.stage` into that same
UPDATE costs zero extra statements, while a snapshot-row write would add one UPDATE per page to
a wide JSON column. The wire contract is untouched - both headers project
`{pagesDone, pagesTotal, stage}` exactly as Appendix A specifies, and both OMIT it whenever it
is not known. `background_jobs` is read, never altered, so module governance holds.

`BL-SS-236` is closed by this plan with its text corrected: `progress` had landed on NEITHER
header.

### 2.4 Pending-job orphan recovery (AC-11-50..60)

The existing sweep (`JobService.fail_orphaned_running_jobs`) is RUNNING-only by deliberate
design: "a PENDING one of any age is a backlogged queue". The 2026-09-21 incident is the case
that assumption misses - the message itself was lost, so the job can never start, and the
AutoCount overlap guard (AC-22-14) correctly refuses to run over it forever.

The fix is a sibling sweep in CORE, not in the module:
`JobService.fail_undispatched_pending_jobs` - `status = 'pending' AND started_at IS NULL AND
created_at < now - window` - stamping a new `UNDISPATCHED_ERROR` sentence and fanning out the
SAME `on_job_orphaned` module hooks, so `ac_sync_run` closes, a `building` snapshot fails, and
a preview claim releases, all through machinery that already exists and is already tested.
It lives in core because losing a queued message is a core `background_jobs` bug class that any
type can hit (imports, storage migration, meetings transcription), and because duplicating the
hook fan-out inside a module would fork core machinery.

Unlike the running sweep it is NOT limited to `heartbeats=True` types (a lost message is
type-agnostic) and it needs its own clock: `created_at`, with a dedicated
`background_job_undispatched_after_minutes` (default 60, floor 15) rather than a multiplier of
the 15-minute heartbeat window, because the two measure different things and a multiplier is
un-reasonable-about.

Consumers: the AutoCount scheduler's overlap guard sweeps exactly the stale in-flight job and
proceeds with the tick (one-for-one with its existing RUNNING branch), and a new 5-minute beat
task `jobs.sweep_orphaned` runs BOTH sweeps for every job type, closing the gap for types with
no scheduler in front of them. A fresh pending job still skips the tick, unchanged.

One frontend consequence ships with it: the Runs list badges any run with a null `outcome` as
"Running", so the four finished skip rows from the incident read as running runs. A run with
`finishedAt` set and no outcome is a SKIP - it renders the existing `SKIPPED` registry badge
(tone secondary) with its reason (AC-11-58).

### 2.5 Decision log

- **D1 - page 1 always alone.** It is the only page that can authorise concurrency, and it is
  the page whose envelope every later page is validated against.
- **D2 - trust only an echoed page set.** No `TotalPages`, no echoed `Page`, no concurrency.
  This keeps plan 08's "never trust the requested values" rule intact.
- **D3 - N is per connection, default 1** (R1). Sizing already belongs to the connection
  (AC-10-85); one module constant cannot serve a 21-s-per-page book and a 0.2-s-per-row book.
  Default 1 means merging this branch changes no production behaviour until an operator opts in
  with measured evidence.
- **D4 - no throughput-probe endpoint.** The preview job already reports pages, wall time and
  effective concurrency; the S6 ramp (N = 1, 2, 4 per book) is an ops procedure, not machinery.
  Rejected under "simplest thing that works"; recorded as BL-SS-249 if the owner wants a
  button.
- **D5 - one job kind, two scopes** (R3). Extending rather than adding a parallel mechanism;
  one progress UI, one cancel path, one claim.
- **D6 - the POST routes keep their paths** and change shape to 202. Internal surface, single
  consumer; a second set of routes would leave two ways to do one thing.
- **D7 - the column probe stays synchronous**, clamped to 45 s. It is exactly one request and
  it is used inline while typing an endpoint path; a job round-trip there would make the
  Lookups editor worse, not better.
- **D8 - no extraction cache between Test, Preview and Activate** (R5). Rejected: it needs a
  config-hash key, a store, an invalidation story (task edit, connection edit, and source data
  that changed under us), a TTL and an honest staleness statement in the UI - and the Activate
  gate exists precisely to prove the CURRENT source, so stamping `lastPreviewAt` off a cached
  walk would defeat it. The measured win after concurrency is small. If reuse is ever wanted,
  the honest shape already exists: let Activate consume the newest READY snapshot (immutable,
  hashed, TTL'd) rather than hide a cache. Backlogged BL-SS-247.
- **D9 - progress rides the heartbeat UPDATE**, not a snapshot-row write (2.3).
- **D10 - the preview claim is a module column**, not an index on core `background_jobs`.
- **D11 - predictions are capped at 500 in the stored result** (R4); summary counts stay whole.
- **D12 - undispatched jobs are FAILED, not re-dispatched** (R6). Re-dispatch looks attractive
  (the job keeps its identity) but carries a real double-execution path: `run_job` treats a
  RUNNING job as a crash-resume and runs the handler AGAIN, so if the original message is
  delivered after we re-enqueue, two workers can execute the same `autocount_sync` and push
  twice. Closing that hole means changing core's crash-resume semantics - a much wider blast
  radius than this incident justifies. Failing costs one minute: the next scheduler tick finds
  nothing in flight and enqueues a fresh job, and the Runs list explains what happened. For a
  manual run or a gateway build the human or the consumer retries, which is already the
  designed path. A late delivery of the original message is harmless: `run_job` sees a terminal
  row and no-ops.
- **D13 - worker-boot reconciliation is rejected** as the primary fix: re-dispatching every
  pending job of a queue when a worker boots multiplies the same double-execution risk by the
  number of workers booting (a rolling deploy boots two), and it cannot help a job queued while
  no worker ever boots again. The periodic sweep (AC-11-56) covers the same ground safely.
- **D14 - the sweep does not require "nothing else is running".** Considered (an old pending
  job while the pool is idle is provably lost) and rejected as a condition that changes no
  outcome class: sweeping a job whose message is merely delayed is benign, because the late
  delivery hits a terminal row and no-ops, while the condition itself would silently disable
  recovery whenever any long job is running.

### 2.6 The worker starvation that froze production (highest-priority slice)

**What happened.** `foundryx_ss_worker_workflow` runs `celery -A app.workflow_engine.worker
worker -Q workflow` with no `-c` on a 1-vCPU host, so there is exactly ONE ForkPoolWorker, and
`jobs.run` shares it with every beat tick in the platform. A `jobs.run` for an AutoCount
supplier sync started 2026-09-20T17:15:33Z and never returned; every tick after it was
"received" by MainProcess and never executed for 8+ hours. Beat was healthy the whole time.

**Why nothing caught it.** Three gaps, all verified in the code:

1. The workflow Celery app sets no `task_time_limit` / `task_soft_time_limit` at all, so a hung
   task holds its slot forever. (The meetings worker already sets `worker_prefetch_multiplier`
   and `task_acks_late` for its own queue - the precedent for per-app tuning exists.)
2. No `worker_prefetch_multiplier` is set, so Celery's default of 4 let the blocked child hold
   several beat messages in its prefetch buffer. That is precisely the "received by
   MainProcess, never executed" signature.
3. `create_engine` passes no `connect_args`, so worker sessions have no `statement_timeout`,
   `lock_timeout` or `idle_in_transaction_session_timeout`. The vendor client, the Sorento sink
   and the SQL source all carry their own HTTP/driver timeouts, so the hang is something that
   has none - a Postgres lock wait or a raw socket. The owner's `ss -tnp` and `pg_stat_activity`
   capture is appended to the test report when it lands; the fix does not depend on it.

And the reason it lasted 8 hours rather than 15 minutes: **the recovery machinery was queued
behind the thing it recovers.** Outside app startup, the only caller of the orphan sweep is the
AutoCount scheduler tick - a beat task on the starved queue.

**The fix, in priority order.**

- **Isolate the long work** (AC-11-80): route `jobs.run` to a `jobs` queue and give it its own
  container (`worker_jobs`, `-Q jobs -c 2`). `worker_workflow` keeps `-Q workflow` and keeps
  the task registered, so the rollout cannot strand a message that is already queued. Raising
  `-c` on the shared worker instead is rejected: it lowers the probability and removes no
  coupling.
- **Never hold a second message** (AC-11-81): `worker_prefetch_multiplier = 1`.
  `task_acks_late` stays OFF for `jobs.run` on purpose - redelivery after a hard kill meets
  `run_job`'s crash-resume branch (a RUNNING row is re-entered) and that is a double push. The
  undispatched sweep is the safe recovery for a lost message.
- **Bound every task** (AC-11-82/83): soft 300 s / hard 330 s for the tick family, soft 2 h /
  hard 2 h 5 min for `jobs.run` from settings. `SoftTimeLimitExceeded` is handled cooperatively
  in `run_job`: the job is failed with a sentence naming the limit and the SAME module close
  hooks run, so `ac_sync_run` closes and the next tick proceeds. That hook fan-out moves out of
  `fail_orphaned_running_jobs` into one helper shared by all three closers (orphan sweep,
  undispatched sweep, time limit).
- **Bound the database sessions** (AC-11-85): settings-driven `statement_timeout` /
  `lock_timeout` / `idle_in_transaction_session_timeout` via engine `connect_args`, set on the
  worker services in compose, unset (unchanged) for the API. Sized from a measured slowest
  statement, and labelled honestly as defence in depth.
- **Make a freeze visible** (AC-11-86): beat publishes `ops.ping` to each queue every 60 s, the
  consuming worker stamps a per-queue Redis key with a 300 s TTL, and one platform-operator
  route reports `lastSeen` / `stale` per queue.

### 2.7 Decision log, continued

- **D15 - queue separation is the invariant; concurrency is only a dial.** A shared queue means
  one hung job can starve the entire platform's scheduled work, whatever `-c` is.
- **D16 - the sweep must never share a queue with the jobs it sweeps.** This is the rule the
  incident teaches, and it is why AC-11-56's `jobs.sweep_orphaned` tick runs on `workflow`.
- **D17 - `acks_late` is refused for `jobs.run`.** Redelivery plus crash-resume equals a double
  push; a lost message is recovered by a sweep that fails the row, not by re-running it.
- **D18 - time limits are per task kind, not global.** A 300 s ceiling that is right for a beat
  tick would kill a legitimate 25-minute Mocha build.
- **D19 - DB timeouts are measured before they are set,** and are not sold as the fix. A paged
  extraction is many short statements; if a single statement legitimately needs more than the
  proposed ceiling, the ceiling moves, not the statement.
- **D20 - the liveness signal is a per-QUEUE ping stamped by the CONSUMER,** not a beat
  heartbeat: beat was healthy throughout the incident, so a beat-side heartbeat would have
  reported everything fine.
- **D21 - failing a job whose worker is provably dead is NOT added to the sweep here.** The
  heartbeat rule already covers every `heartbeats=True` type, the undispatched rule covers
  pending, and the queue split plus the time limit close the incident. Backlogged
  (BL-SS-250) rather than layered on speculatively.

## 3. Files

Backend, core (`service_backend/app/`):
`workflow_engine/worker.py` (`task_routes` for `jobs.run`, `worker_prefetch_multiplier`, the
app-level soft/hard limits, the `jobs.sweep_orphaned` beat entry, the `ops.ping` fan-out, and
the import of the new preview-job module on the worker path), `jobs/worker.py` (`jobs.run`
soft/hard limit declaration), `jobs/service.py` (`fail_undispatched_pending_jobs`,
`UNDISPATCHED_ERROR`, the extracted `close_module_bookkeeping(job)` helper shared by the three
closers, `SoftTimeLimitExceeded` handling in `run_job`, `beat_progress`), `config.py`
(`background_job_undispatched_after_minutes` + floor validator,
`background_job_soft_time_limit_seconds`, the three DB-timeout settings), `database.py`
(settings-driven `connect_args` options), one platform ops route + its schema for the worker
liveness read.

Backend, module (`service_backend/modules/autocount/`):
`http_source/client.py` (`ConnectionSizing` dataclass, `maxConcurrentPages`,
`PREVIEW_REQUEST_TIMEOUT_CEILING_SECONDS`), `http_source/source.py` (the concurrent page
fetcher inside `_walk_endpoint`/`_walk_path`, the echoed-page verification, the row-cap
projection, the 429 back-off, `source_concurrency`), `http_source/preview.py` (timeout ceiling
on the column probe), `provider.py` (the `maxConcurrentPages` field + validation),
`preview_job.py` (new: the `autocount_source_preview` handler, registered from `sync.py` so the
existing worker import covers it), `services/preview_job_service.py` (new: request / claim /
poll / cancel), `services/etl_service.py` (call-site only - `preview_http` / `preview_task`
bodies unchanged), `routers/http.py` + `routers/companies.py` (the two POSTs become 202) and
`routers/previews.py` (new: poll + cancel), `models.py` (`AcEntityConfig.preview_job_id`),
`alembic/versions/0022_autocount_preview_job.py`, `services/pull_service.py` +
`services/pull_gateway_service.py` (the `progress` projection), `schemas.py`
(`PullSnapshotOut.progress`, the preview job schemas), `scheduler.py` (the undispatched branch
in the overlap guard), `bootstrap.py` (`on_job_orphaned` releases `preview_job_id`), `sync.py`
(`beat_progress` stage reporting in `_run_pull_snapshot`, `sourceConcurrency` in metadata).

Frontend (`service_frontend/`): `types/autocount.ts`,
`services/autocount-service.{ts,mock,real}.ts`, `hooks/use-autocount-preview-job.ts`,
`components/platform/autocount/job-progress.tsx` (new, ONE running-state component: stage,
`pagesDone of pagesTotal`, Cancel - reused by the Source tab, Review and Activate, and the
snapshot detail), `app/(protected)/autocount/companies/[id]/entities/[entityType]/components/
{source-tab,activate-tab,task-editor-view}.tsx`,
`app/(protected)/autocount/companies/components/use-runs-list-config.tsx` (the Skipped badge),
`app/(protected)/autocount/pull/snapshots/[id]/components/*` (the progress hint), tests beside
each.

Ops / docs: `docker-compose.yml` (`worker_jobs`, worker DB-timeout env), `DEPLOY.md`,
`docs/reference/process-lessons.md` (AutoCount section: the freeze, the queue rule, the
concurrency knob), the background-jobs reference, this plan pair, and the backlog rows in
section 6.

## 4. Slices and order

| Slice | Scope | UAC |
|---|---|---|
| S0 | Lane + docs commit; record the serial baselines again on the lane; probe `page=2&pageSize=1000` on db1 five times; measure the slowest single Postgres statement of a full `SRT` build (input to AC-11-85) | AC-11-13, 11-85 (measurement only) |
| S1 | **Worker starvation (ship first).** Queue split + `worker_jobs` compose service, prefetch 1, per-kind time limits, cooperative `SoftTimeLimitExceeded` close, the shared `close_module_bookkeeping` helper, worker DB timeouts, `ops.ping` liveness + the platform read, DEPLOY.md | AC-11-80..88 |
| S2 | **Undispatched-job recovery.** `fail_undispatched_pending_jobs` + setting + hook reuse, the scheduler's overlap-guard branch, the `jobs.sweep_orphaned` beat tick (on `workflow`), incident replay | AC-11-50..57, 11-60 |
| S3 FE mock | Preview-job types, mock service, `use-autocount-preview-job`, the ONE `job-progress` component, both tabs wired, snapshot-detail progress, the Runs list Skipped badge; every state tuned against the mock; agent-browser 375/1280 against the mock | AC-11-20, 11-27, 11-43, 11-58, 11-73 |
| S4 BE | **The preview job.** Job type + handler + the two 202 routes + poll + cancel, the `preview_job_id` claim + migration `0022`, the result cap, the save-gate stamping, the synchronous column probe's timeout ceiling; swap the mock for the real service | AC-11-21..26, 11-29..31, 11-70..72 |
| S5 BE | **Progress for real.** `beat_progress`, stages in both handlers, the gateway `building` header, `PullSnapshotOut.progress`, BL-SS-236 corrected and closed | AC-11-40..42 |
| S6 BE | **Bounded-concurrency walk.** `ConnectionSizing` + the `maxConcurrentPages` field + validation, the concurrent fetcher, echoed-page verification, row-cap projection, halving/429 behaviour, `sourceConcurrency`, and the full serial-vs-concurrent parity suite | AC-11-01..11 |
| S7 | Live replay on BOTH books: the N = 1/2/4 matrix, the chosen N written onto each connection, the beat-not-starved regression, the incident replays, recorded agent-browser runs at 375 and 1280, AC-keyed test report, docs, backlog rows appended to `documentation/backlogs/backlog.md` | AC-11-12, 11-28, 11-59, 11-84, 11-74 |

Rules: S1 before S2 (the sweep's own tick must not live on the starved queue); S3 before S4 and
S5 (frontend-mock first, PRINCIPLES step 3); S4 before S6 (a long walk is only observable once
the preview is a job); every backend slice is TDD red-green with the tester's failing tests
first; every coder and tester brief embeds the PRINCIPLES design mandates, the DoD gate and the
hard-fail list; reviewer (Opus) on S1+S2 together and again on S6 (the concurrency slice is the
one that can corrupt a data set silently).

### Test list per slice

- **S1**: route resolution for `jobs.run` and for a queue-declaring type; the app's declared
  soft/hard limits; a handler raising `SoftTimeLimitExceeded` -> job failed with the limit
  sentence + `ac_sync_run` closed + `building` snapshot failed + preview claim released; the
  `connect_args` options string rendered from settings (and absent when unset); the liveness
  route reporting `stale` for a silent queue; a blocked-job-versus-beat-tick integration check
  on the lane.
- **S2**: the sweep's positive case; the five exclusions including the explicit `needs_review`
  pin; the module hook closing the run row with the new sentence; the scheduler replay (swept +
  tick proceeds + no skip row); the fresh-pending skip; the manual-run 409 both ways; the
  setting floor validator.
- **S3**: Vitest per preview state (queued, running with/without a page count, cancelling,
  cancelled, failed, done sample, done full, re-attach after reload); the disabled-while-running
  rule for both buttons; the runs-list badge across all three row shapes; a11y (labelled
  Cancel); no hint copy.
- **S4**: the 202 contract and the sub-second return against a 5 s stub; two concurrent POSTs
  yield one job; the claim released on done / failed / cancelled / hook; cancel stops within one
  page; the save-gate stamps (and the absence of stamps on failure/cancel); the prediction cap;
  the column-probe timeout ceiling; cross-tenant 404 per route.
- **S5**: progress written in one UPDATE (statement count pinned); `building` header carries it
  when known and omits it otherwise; `ready`/`failed` never carry it; the operator schema field;
  a bare-array endpoint omits it.
- **S6**: AC-11-02's five fallback conditions; the in-flight counter at N=4; shuffled-completion
  ordering; the full parity suite at N=1 vs N=4 including the persisted hash map, the snapshot
  `content_hash` and the mutation control; the echoed-page mismatch; the 4xx on page 5 of 12; the
  row-cap projection and the exact check; the halving restart at N=4; the 429 back-off at N>1
  and its byte-identical N=1 control; `sourceConcurrency` recorded.
- **S7**: the measured matrix, the evidence runs, the test report keyed to every AC id.

## 5. Risks and answers

- **A concurrent walk silently changes a data set.** The one risk that matters, because Sorento
  zeroes stock pairs absent from a fed set. Answered by construction (assembly by requested page
  index, never by completion) and pinned by the mandatory parity suite including the snapshot
  `content_hash` and a mutation control. Default N = 1 means the risk is not even live until an
  operator opts in.
- **A SQLAlchemy session touched from a worker thread.** Sessions are not thread-safe; a stray
  DB call inside the fetch worker would corrupt state in ways tests rarely catch. Answered by
  keeping the threads HTTP-only, by firing the heartbeat from the draining thread, and by making
  it a named review hard-fail for S6.
- **We become the wrapper's load problem.** Cloudflare fronts it and its capacity is unknown.
  Answered by default 1, ceiling 8, the measured ramp (AC-11-12), and the 429 back-off.
- **The unexplained page-2 400.** One observation, not a pattern. Probed in S0 before any book
  is raised above N = 1; if it reproduces, that book stays serial and the finding goes to the
  vendor (BL-SS-251).
- **`CallRecord` ordering becomes non-deterministic** under concurrency, and the buffer is
  capped at 200. Acceptable: it is an activity trail, not a contract; 12 product pages or 69
  stock pages plus lookups stay well inside the cap. Stated so a reader is not surprised.
- **A preview job wedges the claim** and Test is blocked forever. Answered by releasing the
  claim on every terminal path INCLUDING the orphan hook, and by the time limit (AC-11-82).
- **Eager dev still blocks.** With `CELERY_TASK_ALWAYS_EAGER=true` the POST runs the job inline.
  Unchanged from the pull snapshot build's own behaviour; documented, and the evidence lane runs
  a real worker (R8).
- **A deep, legitimate queue gets mis-swept** by the undispatched rule. Answered by a 60-minute
  default window (longer than the longest measured build) and by the fact that a late delivery
  of the original message hits a terminal row and no-ops, so the cost of a false positive is one
  re-enqueued tick, not a double run.
- **The queue split strands in-flight messages at deploy.** It does not: `worker_workflow` keeps
  the `jobs.run` task registered and keeps consuming `workflow`, so anything already queued
  there still executes.
- **Two prefork children on a 1-vCPU host.** Memory, not CPU, is the constraint (the work is I/O
  bound). R9 keeps `-c 1` as the fallback.
- **DB timeouts kill a legitimate statement.** Answered by measuring first (S0) and by leaving
  the API unbounded, so a mis-sized value can only affect worker sessions.
- **BL-SS-236's text was wrong** about what shipped. Corrected in the backlog row rather than
  quietly overwritten (the sprint-5/10 test report's PARTIAL was right).

## 6. Backlog (append these rows to `documentation/backlogs/backlog.md` in S0; ids reserved here)

| ID | Title | Priority |
|---|---|---|
| BL-SS-244 | **Lookup endpoints are still walked serially after the main path** - the concurrent fetcher applies per endpoint, so a product run on a slow book still pays main-walk plus lookup-walk end to end. Walking lookups concurrently WITH the main path needs a dependency-aware scheduler and is deliberately not built here. | Medium |
| BL-SS-245 | **`MAX_BUFFERED_CALLS` (200) and `CallRecord` ordering under concurrency** - the activity trail is no longer chronological per page, and a very large walk could still evict early records. Consider an ordered, page-indexed activity summary instead of raw per-request records. | Low |
| BL-SS-246 | **Preview job results live in `background_jobs.result_json`** with a 500-prediction cap. If operators need the full dry-run diff for a 12k-row book, promote the result to its own module table (or reuse the snapshot store) rather than raising the cap. | Low |
| BL-SS-247 | **Reuse a walked extraction for Activate** - rejected in this plan (D8). The honest shape if it is ever wanted: let Activate consume the newest READY pull snapshot (immutable, hashed, TTL'd) instead of re-walking, never a hidden config-hash cache. | Low |
| BL-SS-248 | **Operator Cancel for a BUILDING pull snapshot** - the preview job gets Cancel in this plan; a build can only be stopped by the orphan path or the time limit today. | Medium |
| BL-SS-249 | **A "measure throughput" control on the connection form** - S6 chooses N from an ops ramp recorded in the test report. A button that runs the ramp and suggests N would remove the manual procedure. | Low |
| BL-SS-250 | **Fail RUNNING jobs whose queue's worker is provably dead** (using the AC-11-86 per-queue liveness ping) - not added to the sweep in this plan (D21); the heartbeat rule plus the queue split plus the time limit close the observed incident. | Low |
| BL-SS-251 | **Vendor: `page=2&pageSize=1000` answered HTTP 400 after 30 s once on db1** (2026-09-21) while page 1 answered 200/657 KB. Carry the S0 probe results to the wrapper vendor beside the BL-SS-219 latency measurements. | Medium |
| BL-SS-252 | **`BL-SS-236` correction** - the row claims AC-10-87's `progress` shipped on the public gateway header; it had shipped nowhere. Closed by this plan (AC-11-41/42); recorded so the audit trail shows the text was wrong, not the implementation. | Low |

## 7. Verification rig (read before running any `[E2E]` or `[T]` item)

- Backend on 8001, frontend on 3001, a fresh `rm -rf .next && npm run build`, and - for every
  `[E2E]` item - a REAL Celery worker per queue (`-Q workflow` and `-Q jobs`) with
  `CELERY_TASK_ALWAYS_EAGER=false`. Eager mode hides the entire feature.
- Check port ownership before blaming the code (`lsof -p $(lsof -ti :3001) | grep cwd`); one
  Postgres serves every worktree, so never reseed from another branch mid-verification.
- Timestamp every created name; the measurement matrix (AC-11-12) records book, N, wall time,
  request count, error statuses and the snapshot id for each run.
- Evidence lands under `documentation/plans/sprint-5/11-evidence/<slice>/` with a README run
  log, at 375 AND 1280, real clicks from the sidebar - never a URL shortcut, never Playwright.
