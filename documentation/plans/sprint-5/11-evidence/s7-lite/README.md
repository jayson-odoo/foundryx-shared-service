# Sprint 5 / 11 - S7-lite real-Celery-worker smoke (pre-merge, PR #73)

Lane `s41`, branch `sprint-5/11-autocount-extraction-speed`, worktree
`.claude/worktrees/s41` (HEAD `751c4687`, rebased on main). Backend `:8010`, frontend `:3010`,
DB `foundryx_service_s41`, Redis db 11 (`redis://localhost:6379/11`,
`CELERY_TASK_ALWAYS_EAGER=false`), two real Celery workers (`-Q workflow`, `-Q jobs`). All
timestamps UTC unless marked "local" (system local = UTC+8; some `background_jobs`
`started_at`/`finished_at` columns round-trip through a `+09:00` tzinfo offset - both are noted
where relevant, the delta between them is not itself a bug this run investigated).

## Rig

- `alembic upgrade head` on the lane DB was already at `workflows_http_s31` (core) and
  `0022_autocount_preview_job` (autocount module) - both current; `python -m scripts.bootstrap_db`
  re-run anyway (idempotent, reseeded demo data).
- Backend started with `DATABASE_URL`, `CELERY_TASK_ALWAYS_EAGER=false`,
  `REDIS_URL=redis://localhost:6379/11` exported ad hoc (not written into the shared `.env`), plus
  `CORS_ORIGINS=http://localhost:3010,http://localhost:3011` for the ONE diagnostic dev-mode
  session described in Defect 1 below (reverted implicitly - never written to `.env`, so the
  restart landed back at the file's stock value on any future boot).
- Two Celery workers, `--loglevel=info` (plain `nohup ... &` runs at WARNING by default and hides
  the `[tasks]` roster + `ready.` line needed for check A).
- Frontend: `rm -rf .next && npm run build` (prod) then `npx next start -p 3010`. A SEPARATE
  diagnostic `next dev -p 3011` session was started mid-run to get a readable (non-minified) React
  stack trace for the crash in Defect 1 - **this clobbered the shared `.next/` build** (dev and
  `next start` write incompatible manifests into the same directory), producing a `ChunkLoadError`
  on `/settings/integrations` a few steps later. Recovered by killing both Next processes and
  running a fresh `rm -rf .next && npm run build` + `npx next start -p 3010`; logged here as a
  process lesson, not a product defect. **Lesson for the next lane: never point `next dev` at a
  worktree that also has a `next start` serving the SAME `.next/` directory - use a disposable
  worktree copy or accept an unreadable minified stack instead.**
- Login: `demo@example.com` / `demo1234`, tenant `default`, Admin. `DELETE FROM auth_throttle`
  run pre-emptively on the lane DB (0 rows - no throttle hit this run).
- Company: `AUTOCOUNT` (`228f0f18-1ca3-4ee8-874d-83789cf560f0`), connection `AutoCount`
  (`698813e4-0479-4d5a-a9c3-0b4d33e0ce20`, `baseUrl: https://hapi.sorento.cc.cd/api/db1` = book
  `SRT`, `auth: none`). No `product` entity task existed yet on this fresh lane DB - created via
  real clicks (AutoCount -> Companies -> AUTOCOUNT -> Entities -> Add entity -> Product ->
  Configure), which seeded the same HTTP preset used in earlier plan-10/11 evidence
  (`path: /itembypage`, `keyFields: ["ItemCode"]`, `watermarkField: LastModified`, one lookup
  `/itemuombypage` -> `BaseUOMPrice`).
- A Sorento connection + company sink was ALSO created (`S7-lite Sorento fixture
  20260921T141231Z`, `baseUrl: https://s41-sorento-fixture.invalid`, deliberately unroutable,
  mirroring the `sprint-5/10` S6 live-replay fixture pattern) so the FULL "Run preview" would
  actually walk pages (`previewable: true`) instead of short-circuiting instantly on "no consumer
  configured". This was NOT reverted at teardown (it lives only in the isolated `foundryx_service_s41`
  DB and does not affect any other lane); only the connection's `maxConcurrentPages` was reset to
  `1` per the brief.

## Check A - worker-path registration: PASS

`celery -A app.workflow_engine.worker inspect registered -d jobs_s41@<host>` (raw output
`logs/inspect_registered.txt`) lists `autocount.etl_sweep`, `jobs.run`, `jobs.sweep_orphaned`
alongside the platform tasks. A one-off `python -c` import after `app.workflow_engine.worker` boot
resolved both pieces directly:

```
registered job handlers: ['autocount_pull_snapshot', 'autocount_source_preview', 'autocount_sync',
  'meetings.bot_run', 'meetings.calendar_sync', 'meetings.transcribe', 'storage_migration']
autocount_source_preview handler -> type=autocount_source_preview queue=None heartbeats=True
autocount_http source impl OK: <class 'modules.autocount.http_source.source.HttpApiSource'>
```

`queue=None` rides the `jobs` worker's default queue exactly as the brief expects (both workers'
`[tasks]` roster in `logs/celery_jobs.log` / `logs/celery_workflow.log` list the full platform +
autocount task set, and both logged `ready.` within 2s of boot).

## Check B - preview-job UI flow: PARTIAL PASS, one P0 defect

### Test (sample scope), Source tab - PASS

Screenshots `01-test-running-1280.png` (caught the transient "Reading source" spinner + Cancel
button mid-flight, ~0.4s after click) and `02-test-result-1280.png` (result grid landed: "Paged -
11,845 total - 12 pages of 1000 - a run walks every page"). Network log: `POST
/autocount/http/preview` answered `202` immediately (well under 1s, confirmed by the immediate
`GET /autocount/previews/{jobId}` chain that followed in the SAME event-loop tick), then a handful
of ~1s polls until `done`. `celery_jobs.log` shows the underlying job (`373b2454-...`) ran
`source` stage once and finished in 3.02s wall time (single 50-row sample page). No crash, no
console error.

### Run preview (full scope), Review & Activate tab - PASS for the mechanics, FAILS on render

**Mechanics (job lifecycle, progress, cancel, re-attach, API responsiveness): all correct.**

- `04-run-preview-running-1280.png` / `05-run-preview-running-1280.png` caught the "Queued..."
  then "Reading source - page 1 of 12" states with a live Cancel button, within ~1.5s of the
  click - `POST /autocount/companies/.../etl-task/preview` answered `202` immediately (confirmed
  by network log: POST + first GET landed in the same tick).
- `07-run-preview-progress-375.png` confirms the SAME running state renders correctly, non-clipped,
  at 375px.
- Cancel mid-walk (`08-cancel-preview-1280.png`): clicked while on "page 1 of 12"
  (`progress_done=1` of `progress_total=12` at the moment of cancel); the job's DB row landed
  `status='aborted'`, `progress_done=1`, `finished_at` ~1s after the click - i.e. it stopped
  within the one page already in flight, exactly per AC-11-24. The UI returned to a clean idle
  state (`Run preview` re-enabled, no "Dry-run preview" card), and `ac_entity_config.preview_job_id`
  was confirmed `NULL` (claim released) via direct DB read.
- Re-running "Run preview" immediately succeeded (no stale-claim lock), progressed to "page 2 of
  12" (`06-run-preview-progress-1280.png`, `09-run-preview-progress2-1280.png`), and a mid-walk
  page RELOAD re-attached cleanly - `10-reattach-after-reload-1280.png` / `10b-...` show the SAME
  running job's progress ("page 2 of 12") re-rendering after a full browser reload, per AC-11-23/27.
- API responsiveness during the walk: 5x `curl /docs` at 5s intervals while the jobs worker was
  mid-walk answered `200` in 18-30ms every time (`no request blocked the API process`).
- The task DID configure a real (dummy, `.invalid`-TLD) Sorento sink so `previewable: true` and a
  genuine 24-page walk occurred (12 pages of `/itembypage` + 12 pages of the `/itemuombypage`
  lookup, confirmed via `progress_total` changing from 12 to 24 partway through and via
  `celery_jobs.log` HTTP request lines). Total wall time for this full run: `started_at
  23:21:13` -> `finished_at 23:39:29` (local, `+09:00` tz-labeled in the DB) = **18m16s**, ending
  `status='failed'` with an operator-safe message: `"The dry run against the consumer failed... 
  Consumer unreachable: ConnectError: [Errno 8] nodename nor servname provided, or not known"` -
  correct behaviour for an intentionally-unroutable sink, and consistent with AC-11-25 (task
  received NO `lastPreviewAt`/`resultColumns` stamp from a failed dry run - only the SOURCE-side
  `preview_http`/Test path stamps those independently). `13-run-preview-failed-1280.png` (a FRESH
  page load after the job had already failed) shows a clean idle Review & Activate tab with no
  crash and no error text, which is correct by design - the failure toast/message is a live-poll
  artifact scoped to the tab session that started the run, not a persisted banner; a reload after
  the job is already terminal has nothing left to re-attach to (`preview_job_id` released).
  Confirming the LIVE failure banner render (not just the DB row) was not directly observed in
  this run because the tester stepped away mid-walk to exercise check D concurrently - flagged
  here as a real test-sequencing gap, not a code claim either way.
- Check C (queue isolation) piggy-backed on this same long window: `celery -A
  app.workflow_engine.worker call ops.ping --queue=workflow` was fired twice, once early (while
  the jobs worker had already been running the 24-page walk for ~1 minute) and once again later
  (this time overlapped with a FRESH sample "Test" click, i.e. genuinely concurrent jobs-worker
  activity). Both answered in the `workflow` worker's own log within 0.14s and 0.005s
  respectively (`celery_workflow.log`), on the `workflow` queue, never touching `jobs`. The
  `jobs` worker itself kept advancing its own long-running task the entire time (heartbeats every
  ~20s in `celery_jobs.log`). **PASS: the two queues are demonstrably isolated.**

**Defect 1 (P0, blocks the AC-11-28 script as written): the Review & Activate page crashes to the
generic error boundary ("Something went wrong") the FIRST time it renders a preview job's DONE (or
in-flight-then-mounted) task echo for an `autocount_http` task**, both observed live:

1. The FIRST reproduction: "Run preview" on the ORIGINAL logging-sink company (before the Sorento
   fixture was added) completed near-instantly (`previewable: false`, no consumer configured -
   the pre-existing, documented `preview_task` short-circuit) and crashed on render.
2. The SECOND reproduction (after the Sorento fixture unlocked a real walk): a plain "Test" click
   on the Source tab crashed the same way later in the same browser tab's lifetime, AFTER an
   earlier full "Run preview" cycle had already run in that tab.

Console error both times (`agent-browser console`): `TypeError: Cannot read properties of
undefined (reading 'trim')`, `"The above error occurred in the <TaskEditorView> component."`
(caught with dev-mode sourcemaps in a disposable diagnostic browser session - never part of the
recorded evidence run itself).

**Root cause (read, not guessed - cited by file/line):**

- `service_frontend/app/(protected)/autocount/companies/[id]/entities/[entityType]/components/
  task-editor-view.tsx:599-600` computes, unconditionally inside the page's `resourceConfig`
  `useMemo` (runs on every render once `task`+`config` are truthy):
  ```ts
  const querySaved =
    task.sourceConfig.query.trim().length > 0 || Boolean(task.sourceConfig.path?.trim());
  ```
  with NO optional chaining on `.query`. An `autocount_http` task's `source_config` JSON column
  NEVER contains a `query` key (confirmed directly against the DB row) - so `task.sourceConfig.query`
  is `undefined` for THIS task shape whenever the raw, un-normalized wire shape reaches this
  component.
- The NORMAL "GET task" path avoids the crash because `service_frontend/services/
  autocount-service.real.ts:304-308` runs every `getEtlTask`/`updateEtlTask`/`activateEtlTask`/
  `pauseEtlTask`/`resumeEtlTask`/`runEtlTaskNow` response through `normalizeEtlTask()`, which
  back-fills `SQL_SHAPE_DEFAULTS` (`query: ''`, `lineQuery: ''`, ...) onto an HTTP task's
  `sourceConfig` (the file's own comment at line 79-82 names this exact list of endpoints as
  "EVERY endpoint that returns or embeds an `AutocountEtlTask`", and calls out that the list was
  "extended past the first two" in an earlier review round).
- **`startPreviewJob`, `getPreviewJob` and `cancelPreviewJob` (same file, lines 449-463) were NOT
  added to that list** - they call `apiFetch` directly with no `normalizeEtlTask` wrapper. When a
  `full`-scope job reaches `done`, `hooks/use-autocount-etl.ts:245`'s `onTask(job.result.task)`
  (wired to `apply()` -> `setTask(next)`) lands this UN-normalized shape straight into the shared
  `task` state that `TaskEditorView` renders from, and the very next render of the `resourceConfig`
  memo throws.
- Backend side is innocent here: `modules/autocount/preview_job.py`'s `_task_echo_model` /
  `_task_echo` deliberately builds the SAME wire shape the router's own `_task_response` builds
  (`sourceConfig=view.source_config`, a raw `Dict[str, Any]` per `schemas.py:823`) - AC-11-26's own
  contract ("the SAME task echo the route used to return") is honoured correctly. The gap is
  purely that the FRONTEND's own defaulting layer, applied everywhere else, was never wired onto
  the three new preview-job endpoints.

**Blast radius:** every `autocount_http` task (the ONLY source impl this plan's HTTP concurrency
work touches) will hit this on its FIRST successful "Run preview" completion once any consumer is
reachable enough to reach the `dry_run`/`no-consumer` branch and return a `done` result with a
task echo - i.e. this is not a corner case, it is the MAIN success path AC-11-28 is written
against. It is a genuine regression introduced by this plan's job-ification of preview
(`autocount_source_preview`), not a pre-existing issue - the OLD synchronous `preview_task` route
never had this class of bug because its response went straight through the router's own
`_task_response` (also missing `normalizeEtlTask`, but the OLD flow never stored/replayed the raw
dict through client state the way `apply()` now does for the job's polled result).

**Recommendation: this is a merge blocker for PR #73 as currently proposed**, or at minimum
must ship with a documented, tracked follow-up landing in the SAME PR before any tenant relies on
the job-ified preview surface - a crash on the primary success path of the feature under test is
not an edge case. Suggested fix (for the coder, not applied here per the tester's remit): wrap
`getPreviewJob`/`startPreviewJob`/`cancelPreviewJob`'s nested `.task` field through
`normalizeEtlTask` in `services/autocount-service.real.ts`, matching the pattern already used by
every other task-echoing endpoint in that file.

## Check D - `maxConcurrentPages` connection field: PASS

`12-connection-concurrency-field-1280.png` shows the field present on the AutoCount connection's
edit form ("Max concurrent pages", blank = default). Validation confirmed via real submits:
- `0` -> rejected, toast `"maxConcurrentPages must be between 1 and 8."`
- `9` -> rejected, SAME message (valid range is 1-8, not 1-9 - the brief said "rejects 0 and 9",
  both DO reject; noting the upper bound is 8 for the report's own accuracy).
- `1` -> accepted, `"Connection saved."` toast, confirmed in the DB (`config_json.
  maxConcurrentPages: '1'`).

N=4 concurrency was NOT separately measured in this run (see Deviations below) - the field's
validation contract is confirmed; the wall-time comparison (N=1 vs N=4) that AC-11-12's measured
proof calls for was already carried in the `sprint-5/11` S6 ops run per the plan's own citation
rule and was out of scope for this lighter S7 smoke, which the brief scoped to "real-worker smoke"
rather than a full concurrency re-measurement.

## Check E - teardown: PASS

- Killed only this lane's own pids (uvicorn `25334`, `wf_s41` `16270`, `jobs_s41` `16271`,
  `next start` `34352`) - each cwd-verified against the worktree path before the kill. All four
  confirmed gone within 6s (the two Celery workers took a graceful warm-shutdown beat).
  `agent-browser --session s41diag close` cleaned up the one disposable diagnostic browser
  session (never `close --all`).
- Ports `8010`/`3010`/`3011` confirmed free (no LISTEN sockets) after teardown.
- Connection `maxConcurrentPages` left at `1` on the lane DB (confirmed via direct read, see
  Check D).
- Evidence dir + this README left in place; nothing else in the worktree touched (`git status`
  after teardown shows only the new evidence files - no application code edited by the tester, per
  the tester's remit).

## Deviations from the brief, stated plainly

- The brief assumed a `product` HTTP task already existed with an Open-API task pre-seeded on the
  lane; this lane's DB was actually fresh (freshly bootstrapped for this run), so the task was
  created via real UI clicks first (Add entity -> Product -> Configure), seeding the SAME
  `/itembypage` preset used in earlier plan-10/11 evidence. This is a real click-through, not a
  shortcut, and is the reason the very first "Run preview" ran against a `logging`-sink company
  (no Sorento configured yet) rather than exercising a genuine page walk - a Sorento fixture
  connection was added mid-run (real clicks, Settings -> Integrations -> Connect integration,
  timestamped name `S7-lite Sorento fixture 20260921T141231Z`) specifically so the SECOND "Run
  preview" would walk real pages and let Cancel / progress / re-attach be verified properly.
- The N=1 vs N=4 full-build wall-time/hash comparison (part of AC-11-12, not explicitly re-asked
  by this S7-lite brief beyond the field's existence) was NOT run - a full N=4 product build
  against `db1`/SRT is a ~2-9 minute live call each way and was judged out of scope for a
  "real-worker smoke," especially after the crash discovered in check B made a full successful
  render of that result moot until Defect 1 is fixed. Flagging this explicitly rather than
  padding the report with a check that was not actually performed.
- One `next dev` diagnostic session briefly clobbered the shared `.next/` prod build (see Rig
  section) - recovered with a clean rebuild before continuing; logged as a process lesson.

## PASS/FAIL summary

| Check | Result | Notes |
|---|---|---|
| A - worker-path registration | **PASS** | `autocount_source_preview` + `autocount_http` resolve on the `jobs` worker; both workers `ready.` with full `[tasks]` rosters |
| B - preview-job UI flow | **PARTIAL** | Job lifecycle/progress/cancel/re-attach/API-responsiveness all correct; **P0 render crash** (Defect 1) on the primary success/done path for an `autocount_http` task - recommend merge blocker |
| C - queue isolation | **PASS** | `ops.ping` on `workflow` answered in 0.14s and 0.005s while `jobs` was mid-walk on a 24-page live run |
| D - `maxConcurrentPages` field | **PASS** | Present, defaults blank->1, rejects 0 and 9 (valid range 1-8), accepts 1 |
| E - teardown | **PASS** | Own pids only, cwd-verified; ports free; connection reset to N=1; evidence committed |

**Merge recommendation: DO NOT merge PR #73 as-is - fix Defect 1 first** (or ship it in the same
PR with a passing re-verification of check B). Everything else - the job/queue architecture that
is this plan's actual subject (worker registration, non-blocking POST, cooperative cancel,
progress reporting, re-attach, queue isolation) - is solid and matches the AC-11-2x/AC-11-40/41
contract exactly. The defect is narrowly scoped (one un-normalized field on three service-layer
functions) and should be a fast fix, but it sits directly on the feature's own primary success
path and must not ship un-fixed.

## Recheck (commit `84e6c4ae`, same day) - Defect 1 fix verification

Rig brought back up identically (lane `s41`, same ports `:8010`/`:3010`, Redis db 11, two real
Celery workers, `rm -rf .next && npm run build` + `npx next start -p 3010`; `next dev` never run
against this `.next`). `git log -1` confirmed HEAD `84e6c4ae` ("normalise the preview-job task
echo like every other task endpoint") before starting any process; all rig pids started after
that confirmation. Evidence in `recheck/`.

### B-recheck: Run preview (full scope) -> done render - PASS, Defect 1 confirmed fixed

Same task (`AUTOCOUNT` / `product`), sink switched back to `logging` (the exact `previewable:
false` scenario that crashed before) so "Run preview" completes in ~1s and lands `done`.
`recheck/01-idle-logging-sink-1280.png` (idle before) -> `recheck/02-run-preview-done-1280.png`
(done result rendered: "Nothing to preview - No consumer is configured..." card, "Preview passed
21 Sept 2026, 22:42" badge, `Activate` button enabled, **no error boundary**) ->
`recheck/03-run-preview-done-375.png` (same, 375px, no clipping). `agent-browser console` showed
**zero errors** across this whole flow (checked with an explicit `console --clear` immediately
before the click). Activate state is correct: enabled because the Source tab's own earlier Test
had already stamped `lastPreviewAt` independently (by design, per `preview_task`'s docstring - an
`autocount_http` task earns activation through Source-tab Test regardless of consumer
reachability). **Confirms `normalizePreviewJob`'s handling of the FULL-scope `job.result.task`
closes Defect 1 exactly as intended.**

### B-recheck: Source tab Test (sample scope) -> done grid - FAIL, Defect 2 (NEW, same class, not yet fixed)

Reproduced twice independently, including on a **fresh page reload** (ruling out any stale state
from the Run-preview cycle above): clicking `Test` on the Source tab crashes to the SAME generic
error boundary, `recheck/04-test-done-1280.png` and `recheck/05-test-crash-1280.png`
("Something went wrong"). Console error this time: `TypeError: Cannot read properties of
undefined (reading 'filter')`, `"The above error occurred in the <TaskEditorView> component."`

**Root cause, proven directly against the raw wire payload** (patched `window.fetch` in the live
page to capture the exact `GET /autocount/previews/{jobId}` response body before the crash -
never `next dev`, no sourcemaps needed): the DONE job's body is
`{scope:"sample", status:"done", result:{scope:"sample", preview:{..., "task":{...}}}}` and the
captured `result.preview.task.sourceConfig` is the RAW, un-normalized dict - `{connectionId,
path, keyFields, watermarkField, comparedFields, distinctOf, ..., combine}` - with **no `query`,
`keyColumns`, `comparedColumns`, `watermarkColumn`, `lineQuery`, `fromDate`, `docDateColumn` or
`filterFormula` keys at all**, exactly the same un-normalized shape Defect 1 had.

**Why the fix commit (`84e6c4ae`) doesn't cover this:** `normalizePreviewJob`
(`services/autocount-service.real.ts`) is:
```ts
function normalizePreviewJob(job: AutocountPreviewJob): AutocountPreviewJob {
  if (job.result?.scope !== 'full') return job;
  return { ...job, result: { ...job.result, task: normalizeEtlTask(job.result.task) } };
}
```
This only normalizes a **top-level** `job.result.task`, present only on the `full` scope. The
`sample` scope's task echo is nested one level deeper, at `job.result.preview.task` (confirmed by
`types/autocount.ts:993-999`'s `HttpPreview.task?: AutocountEtlTask` - a flat, optional field ON
the preview object itself, matching the backend's `preview_job.py` `_run_sample`/`HttpPreview`
response shape). The `scope !== 'full'` guard returns the WHOLE job untouched for `sample`, so
`preview.task` never gets normalized.

**Where it then crashes:** `SourceTab`'s own `onHttpPreviewSuccess` callback
(`source-tab.tsx:505`, `if (result) onHttpPreviewSuccess?.(target, typeof result === 'object' ?
result.task : undefined)`) forwards this un-normalized nested task up to
`TaskEditorView.onHttpPreviewSuccess` (`task-editor-view.tsx:372-384`), which calls `apply
(previewedTask)` unconditionally whenever a task is present (`if (previewedTask)
apply(previewedTask)`) - landing the raw shape straight into the shared `task` state. The crash
site itself is one of `source-tab.tsx`'s SQL/DB-branch pickers (`filterKnownColumns` at line 205
being the most likely single call: `pickerColumnOptions(previewColumns, config.keyColumns)`,
alongside `savedPicks` at 220-226 and the `comparedOptions`/`keyColumnOptions`/`watermarkOptions`
chain at 234/250/258) - these read `config.keyColumns`/`config.comparedColumns`/
`config.watermarkColumn` **directly, with no `?? []`/`?? null` guard**, unlike the HTTP-branch's
own `httpKeyFields`/`httpComparedFields` (lines 415-416) which the original fix commit's
belt-and-braces pass DID guard. `pickerColumnOptions`'s own body
(`lib/autocount-etl.ts:50-56`, `saved.filter((c) => !seen.has(c))`) throws exactly "Cannot read
properties of undefined (reading 'filter')" when its second argument is `undefined` - matching
the observed error character-for-character, confirmed by reading the corresponding minified
function body directly out of the shipped chunk (`function o(e,t){let n=new Set(e);return
[...e,...t.filter(e=>!n.has(e))]}` - byte-identical to `pickerColumnOptions`'s source).

**Blast radius:** every `autocount_http` task's Source-tab "Test" click that lands a `task` echo
(which per the docstring at `preview_job.py`/`use-autocount-etl.ts` happens on essentially every
successful sample preview once the backend has a saved config to echo) will crash the whole page
the moment `onHttpPreviewSuccess` fires with a real task. This is the SAME severity as Defect 1 -
a crash on a primary, everyday success path (Source tab Test), not an edge case - and was NOT
caught by the original P0 fix or its own regression test
(`autocount-service.real.test.ts`, which per the diff only exercises `getPreviewJob`/
`cancelPreviewJob`'s TOP-LEVEL `result.task`, never the SAMPLE scope's nested `preview.task`).

**Recommendation:** extend `normalizePreviewJob` to also normalize `job.result.preview.task` when
present (regardless of scope - a `preview.task` field can appear on a `sample`-scope done result),
and/or add the same `?? []`/`?? null` guards already applied to the HTTP-branch pickers onto the
five un-guarded SQL/DB-branch call sites in `source-tab.tsx` (lines 205, 220-226, 234, 250, 258) as
defense-in-depth, matching the pattern the original fix already established for `.query`. This
should also block merge until fixed and re-verified, same as Defect 1 was.

### Screenshots (`recheck/`)

| File | What it shows |
|---|---|
| `00-review-activate-idle-1280.png` | Review & Activate, idle, before the recheck (Sorento sink still configured from the original run) |
| `01-idle-logging-sink-1280.png` | Idle after switching the company back to `logging` sink (real click, Overview tab -> Edit -> Push delivery target -> No delivery) |
| `02-run-preview-done-1280.png` | **Defect 1 fixed** - Run preview done, clean render, 1280px |
| `03-run-preview-done-375.png` | Same, 375px |
| `04-test-done-1280.png` | **Defect 2 (new)** - Source tab Test crash, first reproduction |
| `05-test-crash-1280.png` | Defect 2, second reproduction (fresh page reload, rules out stale-state explanation) |

### D-full (N=1 vs N=4 page-walk measurement): NOT RUN - descoped mid-task

The coordinator cut scope mid-recheck ("SKIP D-full entirely - it moves to post-merge S7") after
setup had begun (the `product` entity's `deliveryMode` was switched to `pull` to unlock a
"Build snapshot" dialog, in preparation for a pull-based N=1/N=4 measurement that avoids the
Test-flow crash entirely). That setup was **reverted** before teardown - `deliveryMode` switched
back to `push` via a real click (Schedule tab -> Edit -> Push -> Save task, confirmed "Task
saved." toast) - no pull API key or snapshot was ever created, so there is no residue beyond the
already-existing Sorento fixture connection/sink from the original run (left in place, isolated to
this lane DB, not reverted per the original brief's own instruction).

### Recheck teardown

Killed only this recheck's own pids (uvicorn `75725`, `wf_s41` `75858`, `jobs_s41` `75859`, `next
start` `76828`/`76855`) - each cwd-verified against the worktree before killing. All confirmed
gone. Ports `8010`/`3010` confirmed free after. `agent-browser --session s41 close` (never
`close --all`).

### Recheck summary

| Item | Result |
|---|---|
| B-recheck: Run preview (full) -> done render | **PASS** - Defect 1 confirmed fixed |
| B-recheck: Source tab Test (sample) -> done render | **FAIL** - Defect 2, same crash class, `normalizePreviewJob` doesn't cover the sample scope's nested `preview.task` |
| D-full (N=1 vs N=4) | Not run - descoped to post-merge S7 by the coordinator mid-task |

**Merge call (unchanged in spirit, updated defect): still do not merge PR #73 as-is.** Defect 1 is
verified fixed. Defect 2 is a new, same-class regression discovered by this recheck, on an
equally primary success path (Source tab Test, likely exercised MORE often in practice than a
full Run preview) - it must be fixed and re-verified before merge, exactly as Defect 1 was.
