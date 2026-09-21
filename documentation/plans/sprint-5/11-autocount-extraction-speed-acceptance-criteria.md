# 11 - AutoCount HTTP extraction speed + non-blocking preview: acceptance criteria

Companion to `11-autocount-extraction-speed.md`. Ids are `AC-11-nn`, tagged `[BE]` (backend),
`[FE]` (frontend), `[E2E]` (a recorded `agent-browser` run, real clicks, 375 AND 1280) and
`[T]` (a measured/ops proof). The Test Execution Report keys PASS / FAIL / DEFERRED back to
these ids.

Scope reminder (non-goals, pinned here so a reviewer can reject drift): no change to the
Sorento cross-repo contract (`sprint-5/10` Appendix A) beyond the OPTIONAL `progress` field
that appendix already specifies; no change to mapping, combine or lookup semantics; no change
to what a snapshot contains.

## 0. Baseline this plan is measured against (recorded 2026-09-21)

- Vendor wrapper `https://hapi.sorento.cc.cd/api/db1/itembypage?page=N&pageSize=1000` answers in
  about 21 s per 1000-row page. `itemuombypage` answers a page in about 0.18 s.
- `SRT` product = 11,840 rows = 12 pages; measured full pull build 9m00s. `db2` (Mocha, 3,445
  rows, slow wrapper) 8m01s.
- One probe of `page=2&pageSize=1000` on db1 answered HTTP 400 after 30 s, once, unexplained;
  page 1 the same minute answered 200 / 657 KB. Treated as a risk to probe (AC-11-13), never
  as a known behaviour.
- The page walker is serial (`http_source/source.py` `_walk_path`, `page += 1`); lookups walk
  serially after it.
- Review and Activate "Run preview" (`POST .../etl-task/preview`) and the Source tab "Test"
  (`POST /autocount/http/preview`) are each ONE blocking HTTP request. Production sits behind
  Cloudflare (about 100 s proxy cut), so the browser receives a 524 while the server keeps
  working and later stamps `lastPreviewAt` - the operator sees an error, then "Preview passed"
  after a reload.
- `AC-10-87`'s `progress` hint is NOT implemented anywhere today (no `pagesDone` symbol exists
  in the repo). The sprint-5/10 test report's PARTIAL is the accurate record; `BL-SS-236`'s
  text, which claims it landed on the gateway header, overstates the state.

## Group A - bounded-concurrency page fetch (`[BE]` / `[T]`)

- **AC-11-01 [BE]/[FE]** **Concurrency is a per-CONNECTION setting, defaulting to today's
  behaviour.** `AutoCountProvider.fields()` gains `maxConcurrentPages` (number, default 1,
  range 1..8) carrying the EXISTING `showWhen: {field: "auth", values: ["none"]}` mechanism,
  beside `pageSize` and `requestTimeoutSeconds`. Save-time validation rejects a non-integer or
  out-of-range value with a 422 naming `maxConcurrentPages`. It is read through the ONE shared
  reader that already serves `pageSize`/`requestTimeoutSeconds`
  (`http_source/client.py::connection_sizing`, which now returns a `ConnectionSizing` object
  rather than a 2-tuple), so the run path, the preview path and the column probe can never
  disagree. Given a connection saved before this branch (no value stored), the effective value
  is 1 and every walk is byte-identical to today.
- **AC-11-02 [BE]** **Page 1 is always fetched alone, and concurrency is opt-in per walk.**
  Pages 2..`TotalPages` are fetched concurrently only when ALL of: the page-1 envelope is
  paged; the echoed `TotalPages` is >= 2; the echoed `Page` is PRESENT on page 1 and equals 1;
  and the effective `maxConcurrentPages` > 1. If any condition fails the walk falls back to the
  EXISTING serial loop with no behaviour change. One test per condition (bare array, absent
  `TotalPages`, absent echoed `Page`, `TotalPages == 1`, `maxConcurrentPages == 1`).
- **AC-11-03 [BE]** At most `maxConcurrentPages` requests are in flight at any instant, pinned
  by a counting stub transport that records the maximum simultaneous entries, and the total
  request count never exceeds `TotalPages` (plus any retry-ladder attempts). A walk of 12 pages
  at N=4 issues 12 page requests.
- **AC-11-04 [BE]** **Order is by requested page, never by completion.** The assembled row list
  is ascending page order with intra-page order preserved, proven with a stub that answers
  pages in shuffled order with randomised delays. The row that de-duplication keeps
  (first-occurrence-wins, AC-08-22) is therefore the same row the serial walk would have kept.
- **AC-11-05 [T]/[BE]** **Serial-versus-concurrent parity is mandatory and pinned by a test.**
  A recorded fixture (at least 7 paged pages, at least one duplicate key spanning a page
  boundary, a watermark column, one lookup endpoint, and separately a combine-carrying task) is
  run through `HttpApiSource.fetch_changes` at N=1 and at N=4. Byte-identical for both:
  `records` (order and content), `rows_scanned`, `reported_total`, `added_count`,
  `updated_count`, `delete_refs`, `current_refs`, `cursor`, `envelope_kind`,
  `lookup_verification`, `combine_metadata`; the persisted `ac_row_hash` map; and, end to end,
  a `_run_pull_snapshot` at each N produces the SAME `content_hash` and `record_count`. A
  mutation check accompanies it: flipping one cell in the fixture changes the hash at BOTH
  values of N, so the parity assertion cannot pass for the wrong reason.
- **AC-11-06 [BE]** **Echoed-page verification replaces the non-advancing guard in the
  concurrent path.** Any page whose echoed `Page` is present and does not equal the page that
  was requested fails the whole walk with code `shape`, naming the requested page. The serial
  path keeps its existing SF-5 guard unchanged. Test: a stub that echoes `Page: 1` for every
  request fails at N=4 on the first mismatched page and issues no further pages.
- **AC-11-07 [BE]** **Every existing guard survives concurrency, with the same codes and the
  same fail-before-state rule.** Shape change, non-JSON body, 4xx, and the row cap all fail the
  run before any hash, watermark, staged row or snapshot row is written. The row cap is checked
  twice: a pre-flight projection (`TotalPages` x echoed page-1 `PageSize` > `row_limit` fails
  before page 2 is requested) and an exact post-assembly check, both with code `row_limit`.
  Test: a 4xx on page 5 of 12 at N=4 fails the run with `http_status` naming page 5, writes
  nothing, and submits no page after the failure is observed.
- **AC-11-08 [BE]** **AC-10-75 is preserved exactly.** The per-page retry ladder is unchanged
  (one timeout retry; a second timeout of the same page at the same size raises the halving
  signal; a connect error or other 5xx gets the separate 1 s / 4 s ladder; a Cloudflare 524 is
  a timeout). A halving aborts the in-flight set, DISCARDS every partial result (AC-10-24),
  halves the page size, and restarts from page 1 - serial page 1 first, then concurrent again -
  at most `MAX_PAGE_HALVINGS` times. Test at N=4 with a stub that times out page 3 twice.
- **AC-11-09 [BE]** **Worker threads never touch the database.** Threads perform HTTP plus JSON
  parse only; the heartbeat / abandonment callback fires once per completed page from the
  draining (calling) thread, so the SQLAlchemy session stays single-threaded. Test: a heartbeat
  that raises `_BuildAbandoned` on the 3rd completed page at N=4 stops the walk, submits no new
  page, and lets at most N already-in-flight requests drain. A static check (or review gate
  recorded in the test report) asserts the concurrent worker body references no `Session`.
- **AC-11-10 [BE]** **Politeness back-off (owner ruling R2).** At N > 1 an HTTP 429 on any page
  aborts the concurrent attempt, records one `CallRecord` note, waits the response's
  `Retry-After` (clamped to 1..30 s, default 5 s when absent) and restarts the walk ONCE
  serially at N=1. A second 429 fails the run exactly as any other 4xx does today. At N=1 the
  429 path is byte-identical to today (immediate failure, no retry, no wait).
- **AC-11-11 [BE]** **The effective concurrency of a run is recorded**, beside the existing
  `sourcePageSize`: `metadata_json.sourceConcurrency` on a pull snapshot, and one activity note
  on any run whose walk ran concurrently (naming N, the page count and the wall time). A run
  that fell back to serial for any AC-11-02 reason records `1` and names the reason in the
  note.
- **AC-11-12 [T]** **Measured proof, per book.** The S6 ops run records, for db1 (`SRT`) and
  db2 (`MCH`), at N in {1, 2, 4}: wall time of a full product extraction, request count, and
  any 429 / 5xx / 524. Exit criterion: at the chosen N, db1's product build wall time is at
  most 50 percent of the recorded 9m00s serial baseline, and its `content_hash` equals the
  N=1 run of the SAME session (or, if the source changed between runs, the diff is explained in
  the report). The chosen N is written onto each connection and cited by id in the report.
- **AC-11-13 [T]** **The unexplained page-2 400 is probed before concurrency is enabled on a
  book.** `page=2&pageSize=1000` on db1 is requested 5 times serially and the status, byte size
  and latency of each are recorded in the report. If it reproduces, concurrency stays at N=1 for
  that book and the finding is raised with the wrapper vendor (backlog row), because a
  page-specific 4xx fails a concurrent walk exactly as it fails a serial one.

## Group B - preview and Test as a background job (`[BE]` / `[FE]` / `[E2E]`)

- **AC-11-20 [FE]** **Mock first.** Every preview state is built and tuned against
  `services/autocount-service.mock.ts` before any backend exists: queued, running with a stage
  and `pagesDone/pagesTotal`, running with no page count known, cancelling, cancelled, failed
  (with the message), done (sample result), done (full dry-run result), and re-attached after a
  page reload. The mock is swapped at the service boundary in S2 and no mock reaches the
  evidence run.
- **AC-11-21 [BE]** **One job kind, two scopes (owner ruling R3).** A new background job type
  `autocount_source_preview` is registered through `register_job_handler` with
  `heartbeats=True`, and its module is imported on the Celery worker path exactly as
  `autocount_sync` is (otherwise jobs sit Pending forever). Its payload carries
  `{companyId, entityType, scope, request}` where `scope` is `sample` (the Source tab Test:
  today's `EtlService.preview_http`, unchanged) or `full` (Review and Activate Run preview:
  today's `EtlService.preview_task`, unchanged). Neither service function's logic changes; only
  its caller does.
- **AC-11-22 [BE]** **No request waits for a walk (the Cloudflare-safe rule).** `POST
  /autocount/http/preview` and `POST .../etl-task/preview` return 202 with
  `{jobId, status}` and no extraction happens in the request. Pinned by a stub transport whose
  first page sleeps 5 s: the POST returns in under 1 s and the job reaches `done` afterwards.
  A second pin asserts neither route handler calls `preview_http` / `preview_task` directly.
  `GET /autocount/previews/{jobId}` answers in well under a second for a job in any state.
- **AC-11-23 [BE]** **One preview per task, re-attachable.** The in-flight preview job id is
  claimed onto the module's own `ac_entity_config.preview_job_id` with a conditional update
  (`WHERE preview_job_id IS NULL`), so two concurrent clicks cannot start two walks: the loser
  re-attaches to the winner's job id, exactly as `PullService.request_build` re-attaches to a
  live build. The claim is RELEASED on every terminal path - done, failed, cancelled, and the
  orphan sweep's module hook. Test: two concurrent POSTs yield one job id; a hook-closed job
  leaves `preview_job_id` NULL so the next Test is not blocked forever.
- **AC-11-24 [BE]/[FE]** **Cooperative cancel.** `POST /autocount/previews/{jobId}/cancel`
  (tenant-scoped, `autocount.companies.manage`) sets the job to `aborted` from `pending` or
  `running` only, and the handler's per-page checkpoint re-reads the FRESH status and stops
  within one page - no further page is requested, nothing is stamped on the task, the claim is
  released. A cancel against a terminal job is a no-op 200 carrying the terminal status (never
  a 409 the UI has to explain). Test: cancel mid-walk at N=4 stops within N in-flight requests.
- **AC-11-25 [BE]** **Failure mid-walk is reported, never silently swallowed.** A source page
  failure, a lookup failure, a shape change, a row-cap breach or an unreachable Sorento sink
  during the dry run leaves the job `failed` with the operator-safe message the synchronous
  route used to return, and stamps NOTHING on the task (no `lastPreviewAt`, no `resultColumns`,
  no `lastPreviewFailedCount`). The UI shows that message in place of a result. Test one case
  per fault class.
- **AC-11-26 [BE]** **The AC-08-20 save gate is preserved exactly.** A successful `sample` job
  stamps `result_columns` and `last_preview_at` on the named task (the same write
  `preview_http` performs today) and its job result carries the SAME task echo the route used
  to return, so the Source tab adopts the fresh stamp with no second GET racing a concurrent
  Save. A successful `full` job stamps `last_preview_at` and `last_preview_failed_count`
  exactly as `preview_task` does. Activate's gate behaviour is unchanged; a cancelled or failed
  preview never unlocks it.
- **AC-11-27 [FE]** **The operator sees stage and page progress, and nothing instructional.**
  Both Test and Run preview render: the running state with the stage label (Reading source /
  Reading lookup <alias> / Combining / Mapping / Checking with the consumer / Storing) and
  `pagesDone of pagesTotal` when known (omitted, never guessed, when not); a Cancel control
  while running; the result or the failure message when terminal. Both buttons stay disabled
  while their own job is in flight. Reloading the page re-attaches to the running job and keeps
  showing progress. No percentage bar is fabricated from an unknown total, and no hint copy
  explains the mechanism.
- **AC-11-28 [E2E]** Recorded `agent-browser` run at 375 AND 1280, evidence under
  `documentation/plans/sprint-5/11-evidence/preview-job/`: AutoCount -> Companies -> a company
  -> an HTTP entity -> Source tab -> Test -> the running state with a stage appears within a
  couple of seconds -> the result lands -> Review and Activate -> Run preview -> running state
  -> Cancel -> the cancelled state -> Run preview again -> completes. Every screen non-clipped
  at both widths, with a README run log.
- **AC-11-29 [BE]** **The column probe stays synchronous, but Cloudflare-safe.** `POST
  /autocount/http/preview-columns` remains a single request (the Lookups editor needs it
  inline), and its client timeout is the MINIMUM of the connection's `requestTimeoutSeconds`
  and a new `PREVIEW_REQUEST_TIMEOUT_CEILING_SECONDS` (45). Exceeding it returns the existing
  named `path` error, never a hung request. Test pins the effective timeout for a connection
  configured at 100 s.
- **AC-11-30 [BE]** **The stored result is bounded (owner ruling R4).** A `full` job's stored
  result caps `predictions` at 500 entries and sets `predictionsTruncated: true`; `summary`
  counts stay authoritative and uncapped. A `sample` job's result is already bounded by
  `PREVIEW_PAGE_SIZE` (50). Test pins that a 900-prediction dry run stores 500 rows, the flag,
  and the full summary totals.
- **AC-11-31 [BE]** **Eager mode still works, honestly.** With `CELERY_TASK_ALWAYS_EAGER=true`
  (the local default) the job runs inline and the POST returns a job that is already terminal;
  the UI's first poll resolves immediately. The plan's ops note states plainly that a long
  preview in development needs a real Celery worker, and the `[E2E]` lane runs one - the
  non-blocking behaviour is otherwise unobservable.

## Group C - the AC-10-87 progress hint, on both headers (`[BE]` / `[FE]`)

- **AC-11-40 [BE]** **Progress costs no extra write.** The handler stamps
  `{pagesDone, pagesTotal, stage}` in the SAME UPDATE as its heartbeat (one
  `JobService.beat_progress(job_id, done=, total=, stage=)` writing `heartbeat_at`,
  `progress_done`, `progress_total` and `cursor_json.stage`), so a per-page beat costs exactly
  what it costs today. The same helper serves the pull snapshot build AND the preview job -
  one progress mechanism, not two. Stages are `source`, `lookup:<alias>`, `combine`, `mapping`,
  `dry_run` and `storing`.
- **AC-11-41 [BE]** **The gateway `building` header carries `progress` when it is known.**
  `{pagesDone, pagesTotal, stage}` exactly as `sprint-5/10` Appendix A specifies, derived from
  the snapshot's own `job_id` row, tenant-scoped. It is OMITTED entirely when unknown (before
  page 1 answers, for a bare-array endpoint, during a stage with no page count) - never
  guessed, never a percentage. A `ready` or `failed` header never carries it. No other key of
  the agreed wire shape changes.
- **AC-11-42 [BE]** **The operator header carries the same hint** - `PullSnapshotOut.progress`
  (optional, same three fields, same omission rule), closing `BL-SS-236`. The backlog row is
  updated with the correction that `progress` had never landed on EITHER header.
- **AC-11-43 [FE]** The in-app snapshot detail shows the stage and `pagesDone of pagesTotal`
  while building (reusing the same presentation component as the preview job's running state,
  extended with a prop - never a second widget), and shows nothing extra when the hint is
  absent. Verified at 375 and 1280 in the AC-11-59 run.

## Group D - pending-job orphan recovery (`[BE]` / `[FE]` / `[T]`)

Incident 2026-09-21 (production): a deploy restarted the worker while a `sales_order`
`autocount_sync` job was queued. The Celery message was lost; the job stayed `pending` with
`started_at` NULL for over 8 hours, and every scheduler tick wrote a `skipped` run ("A run for
this task was still in progress"). The existing sweep is RUNNING-only by design. Precedent for
the RUNNING case: production 2026-09-07, PO sync killed by a deploy drain, already cited in
`app/jobs/service.py` and `modules/autocount/bootstrap.py`.

- **AC-11-50 [BE]** **A core sweep for undispatched jobs (owner ruling R6: fail, do not
  re-dispatch).** `JobService.fail_undispatched_pending_jobs(*, older_than=None, now=None,
  job_id=None)` fails every job with `status == 'pending'` AND `started_at IS NULL` AND
  `created_at < now - older_than`, stamping a NEW `UNDISPATCHED_ERROR` sentence ("Interrupted:
  the worker never picked this job up (the queued message was lost).") distinct from
  `ORPHANED_ERROR`, plus `finished_at`, and fanning out the SAME `on_job_orphaned` module hooks
  the running sweep uses (same per-hook SAVEPOINT, same failure isolation). Unlike the running
  sweep it is NOT restricted to `heartbeats=True` types: a lost message is type-agnostic.
  Returns the count; idempotent.
- **AC-11-51 [T]/[BE]** **Exclusions are pinned by a unit test.** The sweep never touches:
  `needs_review` (explicitly asserted), `running`, `done`, `failed`, `aborted`; a pending job
  younger than the window; a pending job with `started_at` set. Control: exactly the one
  qualifying row is failed and its count returned.
- **AC-11-52 [BE]** **The module hook closes the AutoCount bookkeeping for this case too.** An
  `autocount_sync` job failed this way has its open `ac_sync_run` row(s) closed with
  `outcome = FAILED`, `finished_at`, a duration and the job's own new error sentence (the hook
  already prefers `job.error`), so the Runs list shows what happened instead of a run that is
  forever in progress. An `autocount_pull_snapshot` job additionally fails its `building`
  snapshot with `BUILD_ABANDONED`, and an `autocount_source_preview` job releases
  `ac_entity_config.preview_job_id` (AC-11-23). Staged rows are untouched, exactly as for the
  running sweep.
- **AC-11-53 [BE]** **The scheduler consumes it, and the tick proceeds.** In the AC-22-14
  overlap guard, an in-flight job that is `pending` with `started_at IS NULL` and older than
  the window is swept by exactly that `job_id`; when the sweep returns 1, the tick continues as
  if nothing were in flight and enqueues a fresh job, mirroring the existing RUNNING branch
  one-for-one. Test replays the incident: a pending `autocount_sync` job aged past the window,
  one scheduler tick -> the job is `failed`, its run row is FAILED / Interrupted, a NEW job is
  enqueued, and no `skipped` run is written for that tick.
- **AC-11-54 [BE]** **AC-22-14 is preserved for a genuinely fresh pending job.** A pending job
  created one minute ago still causes the tick to write a `skipped` run with the existing
  reason, and is not swept. Test.
- **AC-11-55 [BE]** **The manual-run 409 path is unaffected.** `Run now` against a task with a
  FRESH pending or running job still 409s with the existing message; against a task whose only
  in-flight job has been swept, it succeeds. `needs_review` continues not to count as in flight
  (the existing carve-out). Test both.
- **AC-11-56 [BE]** **One periodic entry point for both sweeps.** A beat task
  `jobs.sweep_orphaned` (every 5 minutes, registered in `app/workflow_engine/worker.py` beside
  the existing ticks, failure-isolated like every other tick) runs the RUNNING sweep and the
  new undispatched sweep, so every job type - not just the ones with a scheduler in front of
  them - recovers without a restart. App startup keeps calling both as it does today.
- **AC-11-57 [BE]** **One explicit setting, not a multiplier.**
  `background_job_undispatched_after_minutes` (default **150** - amended from 60, owner-approved
  2026-09-21 review round 1; inert defaults, measured before enabling per the cross-field rule
  below; validator floor 15) in `app/config.py`, documented beside
  `background_job_orphan_after_minutes`. A validator test pins the floor. A
  `model_validator(mode="after")` additionally rejects a value whose window (in seconds) does not
  EXCEED `background_job_soft_time_limit_seconds` - a message that is merely queued behind a
  legitimately long `jobs.run` build on a busy `-c 2` `worker_jobs` must never be mistaken for a
  lost message and failed out from under it. A test pins this cross-field rejection too.
- **AC-11-58 [FE]** **A finished skip row never reads as "Running".** In
  `app/(protected)/autocount/companies/components/use-runs-list-config.tsx`, a run with
  `finishedAt` set and `outcome` null renders the neutral `StatusBadge status="SKIPPED"` via
  the existing `AC_RUN_OUTCOME_REGISTRY` (which already carries a `SKIPPED` entry, tone
  secondary), keeping the `skipReason` line exactly as today; the "Running" badge appears ONLY
  when `finishedAt` is null. Vitest on the config covers all three rows: outcome set, outcome
  null with `finishedAt` (Skipped), outcome null without `finishedAt` (Running).
- **AC-11-59 [E2E]** Recorded `agent-browser` run at 375 AND 1280, evidence under
  `11-evidence/orphan-recovery/`: AutoCount -> Companies -> a company -> Runs tab -> the
  recovered run shows FAILED with the "worker never picked this job up" reason and the
  skip rows beside it show Skipped, not Running; then the snapshot detail with a building
  progress hint (AC-11-43). README run log, both widths.
- **AC-11-60 [T]** **Incident replay on the lane.** The 2026-09-21 scenario is reproduced end to
  end on the lane database (create a pending `autocount_sync` job with `started_at` NULL and a
  backdated `created_at`, leave the open `ac_sync_run` row, run one scheduler tick) and the
  before/after rows are recorded in the test report, including that the owner's manual SQL
  reset is no longer needed.

## Group E - cross-cutting

- **AC-11-70 [BE]** **No new permission.** Every new or changed route reuses
  `autocount.companies.read` / `autocount.companies.manage`, so no CSV row, no grant sweep and
  no existing-tenant 403 risk. Pinned by the permissions parity test.
- **AC-11-71 [BE]** **Tenant scoping.** Every new read or write (preview job create, poll,
  cancel; the progress read behind the gateway header; the claim column) resolves ids WITH the
  tenant from the JWT or, for the gateway, from the API key row - never from client input. A
  cross-tenant test per new route: another tenant's job id reads as a uniform 404.
- **AC-11-72 [BE]** **Migration hygiene.** Module Alembic `0022_autocount_preview_job` (down
  `0021_autocount_pull_gateway`, id under 32 characters, no id collision) adds the single
  nullable `ac_entity_config.preview_job_id`. NULL is the correct value for every existing row,
  so no data backfill is required - stated explicitly in the plan and verified on live Postgres
  with `alembic upgrade head` (the pytest rig uses `create_all` and cannot see migrations).
- **AC-11-73 [FE]** **Responsive and shell-compliant.** Every surface touched is verified
  non-clipped and usable at 375 AND 1280; lists and forms stay on the Resource shell; the
  progress/stage presentation is ONE component extended with a prop, used by the preview panel
  and the snapshot detail alike; no raw CSS, no bare `<Select>`, no instructional copy.
- **AC-11-74 [T]** **Green suites.** `python -m pytest -q` and `npm test` pass; `npx eslint` on
  every changed frontend file passes before a fresh `rm -rf .next && npm run build`.

## Group F - the worker starvation that froze production (`[BE]` / `[T]`)

Root cause, 2026-09-20/21: `foundryx_ss_worker_workflow` runs
`celery -A app.workflow_engine.worker worker -Q workflow` with no `-c` on a 1-vCPU host, so
there is exactly ONE ForkPoolWorker, and every scheduled tick in the platform shares it with
`jobs.run`. A `jobs.run` for an AutoCount supplier sync started at 2026-09-20T17:15:33Z and
never returned; from then on every beat task (`autocount.etl_sweep`, `workflows.run_due`,
`omnichannel.wait_sweep`, `omnichannel.broadcasts_due`, `meetings.*`, `webhooks.retry_due`,
`pending_actions.commit_due`, `status.reevaluate_time_based`) was received by MainProcess and
never executed for 8+ hours. Beat itself was healthy. The workflow Celery app declares NO
`task_time_limit` / `task_soft_time_limit` and no `worker_prefetch_multiplier`, and
`create_engine` passes no `statement_timeout` / `lock_timeout`, so nothing bounded the hang.
The vendor client, the Sorento sink and the SQL source all carry their own timeouts, so the
hang is something that has none (a Postgres lock wait, or a driver socket); the owner is
capturing `ss -tnp` plus `pg_stat_activity` before the restart and that evidence is appended to
the test report when it lands.

This is also why the pending-job symptom lasted 8 hours rather than 15 minutes: the recovery
machinery (the AutoCount scheduler tick, which is the only thing that sweeps an orphaned job
outside app startup) was itself queued behind the hung job.

- **AC-11-80 [BE]** **`jobs.run` gets its own queue and its own worker.** The workflow Celery
  app routes `jobs.run` to a `jobs` queue (`task_routes`), a new compose service `worker_jobs`
  consumes it (`celery -A app.workflow_engine.worker worker -Q jobs -c 2`), and
  `worker_workflow` keeps `-Q workflow`. An explicit `apply_async(queue=...)` override (the
  `stt` / `bots` queues that `JobHandlerDef.queue` already declares) still wins. Tests pin the
  resolved route for a default job type and for a type with a declared queue. Rollout is
  lossless: `worker_workflow` still has the `jobs.run` task registered, so any message already
  sitting on the `workflow` queue at deploy time is still executed.
  Raising `-c` on the existing worker INSTEAD is rejected and the reason is recorded: it lowers
  the probability without removing the coupling (N concurrent ETL jobs still starve every
  tick), and it buys no isolation on a 1-vCPU box.
- **AC-11-81 [BE]** **A long job never holds another message hostage.**
  `worker_prefetch_multiplier = 1` on the workflow app (this is what made every beat tick read
  as "received, never executed": they sat in the blocked process's prefetch buffer).
  `task_acks_late` stays OFF for `jobs.run`, deliberately: redelivery after a hard kill plus
  `run_job`'s crash-resume semantics for a RUNNING row equals a double push. The undispatched
  sweep (AC-11-50) is the safe recovery for a lost message; redelivery is not.
- **AC-11-82 [BE]** **Time limits, per task kind.** Workflow-app defaults bound the tick
  family: `task_soft_time_limit = 300`, `task_time_limit = 330`. `jobs.run` overrides them with
  a generous bound from settings (`background_job_soft_time_limit_seconds`, default 7200; hard
  limit soft + 300), sized above the longest legitimate build measured in this plan (a 25-plus
  minute Mocha snapshot). Tests pin both the app defaults and the task's own declared limits.
  **Review round 1 (B2):** `workflows.run_workflow` and `workflows.wake_serialized` previously
  had NO declared limit of their own and silently inherited the 300s/330s tick-family default -
  wrong for a run that legitimately executes many nodes, or a serialized drain that legitimately
  processes several queued runs in one wakeup. Both now declare their own bound from
  `workflow_run_soft_time_limit_seconds` (default 1800s / 30 min; hard = soft + 300s), mirroring
  `jobs.run`'s own settings-driven pattern. Tests pin both tasks' declared limits AND that the
  app-level tick-family default is unmoved.
- **AC-11-83 [BE]** **A job that blocks forever is failed at the limit, cleanly.** On
  `SoftTimeLimitExceeded` the job is stamped `failed` with a dedicated sentence naming the
  limit, and the SAME module close hooks the orphan sweep uses are fanned out (the
  `ac_sync_run` row is closed FAILED with that sentence, a `building` snapshot fails
  `BUILD_ABANDONED`, a preview claim releases). The next scheduler tick then finds nothing in
  flight and proceeds. Unit test with a handler that raises `SoftTimeLimitExceeded`; the hook
  fan-out is factored out of `fail_orphaned_running_jobs` into one reusable helper so the three
  call sites (orphan, undispatched, time limit) can never drift. **Review round 1 (S3):** the
  SAME helper is now also called from `run_job`'s generic (non-time-limit) crash branch, so a
  plain handler exception closes an open `ac_sync_run` row too, not just a timeout. **Review
  round 1 (B2):** `workflows.run_workflow` and `workflows.wake_serialized` catch
  `SoftTimeLimitExceeded` BEFORE their own generic `except Exception`, stamping the run `failed`
  with a dedicated "exceeded its soft time limit" sentence (`workflow_runs.status` never left
  `running`). **Review round 2 (B3), superseding the round-1 wake_serialized shape:** the
  round-1 task-level catch in `wake_serialized_task` had two bugs - `drain_serialized_runs`'s OWN
  inner `except Exception` (around `execute_run`) is a bare catch that already swallowed
  `SoftTimeLimitExceeded` as a plain crash and kept draining the NEXT pending run past the
  worker's own soft limit; and when the task-level net DID fire (the limit landing between runs)
  it queried "whatever RUNNING row matches this tenant/workflow/digest" with no ownership check,
  which could fail a row this invocation never touched. Fixed by moving the catch INTO
  `drain_serialized_runs` itself, before its own generic except: it fails ONLY the exact `run_id`
  it was executing, then RE-RAISES so the loop stops immediately; `wake_serialized_task` now only
  logs and returns, querying nothing. Test: a real `drain_serialized_runs` call, `execute` raising
  `SoftTimeLimitExceeded` on the first of two pending runs in the same scope - the first carries
  the sentence, the second is never processed, and the exception propagates to the caller.
- **AC-11-84 [T]/[BE]** **A beat tick is never delayed more than one interval by a running
  job.** Regression test for the incident: with a deliberately blocked `jobs.run` occupying the
  `jobs` worker for 10 minutes, `autocount.etl_sweep` and `workflows.run_due` still execute
  every 60 s on the lane (timestamped evidence in the test report), and the new
  `jobs.sweep_orphaned` tick (AC-11-56) runs on the `workflow` queue - never on the queue whose
  jobs it recovers.
- **AC-11-85 [BE]** **Worker database sessions are bounded - inert defaults, measured before
  enabling.** `statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout` are
  settings-driven and applied via the engine's `connect_args` options string; unset (the API
  default) leaves today's behaviour exactly as is, and `worker_connect_args()` additionally
  returns `{}` for a non-Postgres `DATABASE_URL` (review round 1, S5 - the `options` GUC string
  is Postgres-only; the pytest suite's in-memory sqlite must never receive it). The compose
  worker services (`worker_workflow`, `worker_jobs`) carry the three envs with **INERT defaults
  (`0` = no timeout)** as of review round 1 2026-09-21 - R10's recommended values (120s/30s/300s)
  are NOT yet confirmed against the measured slowest statement of a full `SRT` build (S0 could
  not complete that measurement on the shared dev Postgres; see `11-evidence/s0-baseline/
  README.md` (c)). Sizing remains MEASURED, not guessed: the slowest single statement of a full
  `SRT` product build (the row-hash upsert and the `all_hashes` read are the candidates; a paged
  extraction is many short statements, verified in S1) is recorded first, and only then is a
  timeout set - well above it. When enabled, `idle_in_transaction_session_timeout` must stay AT
  LEAST 3x `AUTOCOUNT_SINK_TIMEOUT_SECONDS` (default 300s), because `sync_service.auto_push`
  holds an open transaction across the sink POST; recommended hot values once enabling: statement
  >= 600s, idle >= 900s. Stated honestly in the plan: this is defence in depth - it cannot rescue
  a hang in a non-Postgres socket, which is why the queue split and the time limits are the
  primary fixes.
- **AC-11-86 [BE]** **A frozen worker is visible within minutes.** Beat publishes a tiny
  `ops.ping` to EACH queue on a 60 s tick; the consuming worker stamps a Redis key per queue
  with a 300 s TTL; a platform-permission route reports per queue `{queue, lastSeen, stale,
  alive}`. A worker that is wedged stops answering within one TTL instead of being discovered 8
  hours later. Test: the route reports `stale: true` for a queue with no ping. **Review round 1
  (S2):** `alive` is added - a live Celery control-plane answer
  (`celery_app.control.inspect(timeout=1.0).ping()`, filtered to workers whose `active_queues()`
  name the queue), independent of the Redis-stamp `stale` signal above. `stale` means "no free
  slot OR dead" (a busy-but-alive worker still answers `ops.ping`); `alive` is the control
  plane's own synchronous answer. A dead/unreachable broker reads `alive: false` and never
  raises. Tests stub `control.inspect` for alive-true, alive-false (a reachable worker that does
  not consume this queue) and broker-unreachable. **Review round 2 (S6):** the round-1 shape
  called `control.inspect(...)` once PER queue from the route (two round-trips for two known
  queues); `consuming_workers_by_queue()` now makes ONE `ping()` + ONE `active_queues()` call for
  every queue in a single request, returning `{queue: {worker names}}`, and `queue_status(queue,
  *, consuming=...)` takes that precomputed map so a caller inspecting N queues costs the same
  one round-trip as inspecting one. The connection is also bounded so a dead broker fails FAST
  (`connection_for_read(connect_timeout=1, transport_options={"max_retries": 0})`) rather than
  risking an OS-level TCP hang against a black-holed address. Test: two `queue_status(...,
  consuming=...)` calls off one precomputed map cost exactly one `ping()`/`active_queues()` pair;
  a broker pointed at a closed localhost port returns in under 3 seconds.
- **AC-11-87 [BE]/[T]** **Compose and deploy documentation ship in the same PR.**
  `docker-compose.yml` gains `worker_jobs` and the worker timeout env; `DEPLOY.md` documents
  the new service, the queue split and the deploy-time steps (a new service is picked up by
  `docker compose up -d`; CI deploy already force-recreates; no manual step beyond that).
  **Review round 1 (S4):** a test also asserts `worker_workflow` and `worker_jobs` both carry
  `DATABASE_URL` and `FERNET_KEY` from the shared `x-backend-env` anchor - proving the
  per-service `environment:` override used `<<: *backend-env` (a merge) rather than replacing
  the mapping outright, which would silently strip every other required env. DEPLOY.md also
  notes to run `free -m` before `docker compose up -d` when raising `worker_jobs`' concurrency;
  `-c 1` is the memory-tight fallback.
- **AC-11-88 [T]** **The incident is written down where the next engineer will look:**
  `docs/reference/process-lessons.md` (AutoCount section) and the background-jobs part of
  `documentation/engineering/storage-and-background-jobs.md` /
  `docs/reference/integrations-email-storage.md` get the root cause, the symptom signature
  ("received by MainProcess, never executed"), and the rule: **the sweep must never share a
  queue with the jobs it sweeps**.
