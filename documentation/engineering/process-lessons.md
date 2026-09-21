# Process lessons and methodology detail (E2E rig, branching, worktrees, agent teams)

> Moved verbatim from `CLAUDE.md` on 2026-09-05 (slim-index restructure). The rules here still bind; `PRINCIPLES.md` governs on conflict. Update THIS file when the engine changes.

### Sprint-3 F4-foundations process lessons (08→11, learned the hard way)
- **Stale `next-server` port ownership is the #1 time sink.** A sibling worktree's `next start` (or a prior one) holding :3001 serves OLD chunks → the page 400s on chunk hashes / renders an old build / "ChunkLoadError". ALWAYS `pkill -9 -f next-server` + confirm `:3001` free before a clean `npm start`; check `lsof -p $(lsof -ti :3001) | grep cwd` + the next-server version. After ANY frontend change: `rm -rf .next && npm run build` then a single clean start. `next.config` has `output: standalone` so `next start` warns (harmless, still serves).
- **`uvicorn` WITHOUT `--reload` won't pick up new ROUTES/code after edits** - restart it. DB/migration/perm changes ARE seen live (queried fresh). After adding a migration, run `alembic upgrade head` on the LIVE Postgres before live-testing.
- **A browser "CORS / No Access-Control-Allow-Origin" on ONE endpoint while siblings work = a server 500 on that route** (a 500 thrown before CORS headers attach), NOT a CORS config problem - check the uvicorn log (bit us when a table/route was missing).
- **Alembic revision-id collision**: some migration files use `revision: str = "..."` so a bare `^revision = ` grep misses them - check ALL existing ids (a chosen id already belonged to `tenant_branding`). Collision → "present more than once" + a false "cycle detected".
- **A new core permission doesn't reach existing tenants' Admin roles automatically** - `tenant_admin_grant` is computed at provision/seed. A tenant provisioned before the perm shows "no access" until re-granted (`admin.permissions = tenant_admin_grant(db, tenant_id)`). Worth a migration sweep when adding a core perm.
- **Lint gates the prod build**: no statement-position ternaries (`a ? b() : c()` → `if/else`), no unused imports; **spreading a `Set` needs `Array.from`** (downlevelIteration). `npx eslint <files>` before `npm run build`.
- **Foolproof-UI (reinforced):** a workflow node's bold label is its **editable name**, the type is separate - a node named "Record created" was actually `entity.field_changed`. The card now shows the real type in the subtitle when a custom name diverges, so a name can't masquerade. Apply this "state what it IS" rule to any node/card with an editable name.
- **Live-verification via an agent-driven browser** (historically the retired browser MCP; since 2026-09-04 the `agent-browser` CLI, headless): drive a real session (set inputs via the value-setter + `requestSubmit`), navigate, assert DOM - invaluable for catching the stale-build + perm-grant issues that unit tests miss.

## Development methodology (mandatory order)

This is a strict, governed process - follow it for every feature. Source: the user's `/init` directive + `documentation/development_process/`.

1. **Design first in Figma.** Define design-system variables and components in Figma before coding. Build UI strictly from Figma components.
2. **Component-library discipline.** Reuse components wherever possible. If a new component or variant is needed, build it in the shared component library first, then consume it on the target page - never one-off inline.
3. **Grill → UAC → plan.** Every piece of work starts with a **`grill-me`** session: the user wants to be grilled on the design - frontend AND backend - before any code is written. The grilling resolves the full decision tree.
   - **UAC FIRST, then the plan (MANDATORY).** Once the grill settles the design, **write the User Acceptance Criteria file BEFORE the plan**: `documentation/plans/sprint-<N>/<NN>-<feature>-acceptance-criteria.md`. It is the independently-verifiable Given/When/Then list (per-AC id, grouped by slice, tagged `[BE]`/`[FE]`/`[E2E]`/`[T]`) the feature must satisfy - the **contract**. **THEN** write the plan (`<NN>-<feature>.md`) as the design that *fulfils* the UAC. The Test Execution Report (step 7) is keyed back to the UAC ids (PASS/FAIL/DEFERRED per id). **No plan ships without its UAC file**; a slice is "done" only when its UAC ids pass. Reference format: any existing `*-acceptance-criteria.md` (e.g. `sprint-4/03-...-acceptance-criteria.md`).
   - **Plans live in `documentation/plans/sprint-<N>/`**, numbered + clearly named (e.g. `01-login-page.md`). One plan + one UAC file per feature.
   - **Backlogs live in `documentation/backlogs/backlog.md`** - a single register table (`ID · Title · Source plan link · Priority · Status`). When a plan defers something (hardening, follow-ups, migrations), log it here with a link back to the source plan so it isn't forgotten.
4. **Frontend-first.** UI/UX is the top priority. Build and fine-tune the frontend **before** the backend, using a **mock service behind the service layer** (UI → hook → service → mock) so all states (loading/error/success) are tunable with no backend running. Iterate until the UI/UX is satisfactory.
5. **Backend second.** Only once the frontend is satisfactory, wire the real backend: implement/refactor endpoints (Service-Repository), then swap the mock service for the real `api-client` call. Behaviour swap should be a one-line change at the service boundary.
6. **TDD.** Red-green-refactor, both layers. Frontend component/validation tests (Vitest + React Testing Library) in the frontend phase; backend tests (pytest + httpx) in the backend phase. Tests precede implementation.
7. **Browser verification (former E2E runner retired - user ruling 2026-09-04, plan 23 D15; specs, config and dependency deleted. The lessons below were learned on the retired E2E suite and still apply to agent-browser evidence runs).** `[E2E]` = one recorded `agent-browser` CLI run per user flow, at 375px AND 1280px, evidence under `documentation/plans/sprint-<N>/<NN>-evidence/<slice>/`; it must **simulate real user clicks** (navigate by clicking through the UI) - never shortcut by navigating directly to a page URL, because real users don't know URLs. Run against the mock in the frontend phase, then re-run against the live backend. The QA step produces a Markdown Test Execution Report (User Story / Scenario / Precondition / Steps / Expected / Actual / Remarks) per `AI_Agent_Orchestration_Guide.md` §6.
   - **Spec isolation:** the suite runs `fullyParallel` - a spec that MUTATES shared tenant state (e.g. uninstalling a module on the `default` tenant) breaks concurrent specs mid-run. Such specs must provision a **dedicated tenant** first (operator-API setup is fine; the flow under test stays real clicks). Learned in plan 08: the app-store lifecycle spec on the default tenant intermittently broke a parallel omnichannel spec.
   - **Known env failure:** with real `NEXT_PUBLIC_META_APP_ID`/`NEXT_PUBLIC_META_ES_CONFIG_ID` set in `.env.local`, `omnichannel.spec.ts › connects a channel via Embedded Signup` fails by design (the wizard launches the real Meta SDK; the spec drives the simulated popup). Not a regression - passes with the Meta env unset.
   - **E2E residue accumulates** (learned plan 09): provisioned `e2e-*` tenants are never purged (BL-035) and eventually crowd seeded rows off the tenants list's page 1, breaking `tenants.spec.ts`; a fixed-name entity left by an interrupted run (e.g. `E2E Temp Role`) breaks its spec's next run on the unique-name check. Rules: timestamp every E2E-created name (never a fixed literal), and when the suite fails oddly, suspect residue before code - clean `e2e-%` tenants + leftover `E2E *` rows from the local DB.
   - **Wrong-build gotcha (learned plan 05):** with concurrent worktrees (`.claude/worktrees/*`), whichever process grabbed port 3001 first serves it - an `npm start` from THIS dir silently no-ops if a sibling worktree's server already holds the port, so E2E runs the WRONG branch's build and fails inexplicably (e.g. a menu item missing). Confirm ownership: `lsof -p $(lsof -ti :3001 | head -1) | grep cwd`. After any menu/route/config change, do a CLEAN rebuild (`rm -rf .next && npm run build`) before `npm start` + E2E - a stale `.next` renders the old menu.
   - **Mailbox-asserting E2E rig (learned plan 10):** specs that must READ delivered mail (reset links) need the maildir-handler smtpd, not the plain debug one: `python -m aiosmtpd -n -l localhost:1025 -c aiosmtpd.handlers.Mailbox /tmp/foundryx-e2e-mailbox` - pre-create `tmp/new/cur` subdirs (the handler doesn't) or every send 500s with FileNotFoundError, and check WHO owns :1025 first (a leftover plain `aiosmtpd` from an earlier session binds the port, swallows mail, stores nothing - the same port-owner discipline as 3001/8001). Wiring this into the retired E2E runner global-setup = BL-061. Quoted-printable bodies: strip soft breaks (`=\r?\n`) + decode `=3D` before regexing tokens out of the mail.
8. **Code review.** A code-review agent must approve before merge to `main`.
9. **Branching.** Each piece of development starts on a new branch named `sprint-<N>/<feature>` (e.g. `sprint-1/login-page`); merge to `main` only after review passes. (`git init` before starting branch-based work if the repo isn't yet versioned.)
   - **Concurrent plans:** park a branch with a `wip(...)` commit before switching to another plan's branch; finish/review/merge the parked branch from a **git worktree** (`.claude/worktrees/<name>`, symlink the backend `.env`/`.venv` + frontend `.env.local` in (gitignored); give the worktree its OWN `npm install --force` - NEVER symlink `node_modules`: a coder agent's `rm -rf node_modules/` follows the symlink and wipes the MAIN checkout's install, killing its dev server (learned 2026-09-04)) so the main checkout stays on the active plan.
   - **Servers track the checked-out code:** uvicorn `--reload` and the served Next build run whatever branch their directory has checked out. After any branch switch (or when working split across a worktree), restart/rebuild the side that moved - a frontend built from branch A against a backend on branch B fails with confusing 404s ("Not Found" alert on new pages was exactly this in plan 08). When a page 404s or perms vanish unexpectedly, check WHICH tree owns the port: `lsof -p $(lsof -ti :3001) | grep cwd`.
   - **One Postgres serves every worktree/branch** (learned plan 09): `init_db`/`bootstrap_db` run from a branch whose permission CSVs lack another branch's rows will DELETE those rows (`sync_permissions` is delete-by-module) - mid-session this silently 403s the other branch's features. Don't reseed from a stale branch while another branch's feature is under test; reseed from the branch you're serving.
   - **After a core migration merges, upgrade the shared local DB before live-verifying any worktree stack** (`alembic upgrade head` from any checkout at that head, never a reseed): on 2026-09-07 the shared Postgres sat four core revisions behind main and every connection PATCH on every post-#56 backend 500'd with `UndefinedColumn: background_jobs.heartbeat_at`, which looked like a feature bug until the stamp was checked.
   - **The user codes concurrently in the main checkout** (learned plan 10/sprint-2-01): uncommitted user edits appear mid-session and twice blocked a checkout/rebase. ALWAYS `git status` immediately before any branch operation (merge/rebase/checkout) - never assume the tree you saw earlier is still clean. In-flight user wip: ask before touching; `stash → rebase/merge → stash pop` with explicit consent is the proven recovery. Also: a parked branch's wip commit may be AMENDED or superseded by the user between your turns - re-read `git log` before building on it.

### Code-review hard-fail rules
The reviewer rejects: DB queries / raw SQL inside a router; a React component calling axios/fetch instead of going through a custom hook; `any` types (every component exports explicit TS interfaces); raw CSS / injected `<style>` tags; a module altering core DB tables.
Also reject (learned sprint-4/05): a "done" slice still serving a frontend mock with no real backend swap; a new entity column/engine adoption with no backfill for rows/tenants that already exist; code that hardcode-looks-up a tenant-editable key; a new permission with no grant path for existing tenants.

## Definition of Done + recurring-gap gate (learned the hard way - sprint-4/05 Cluster D)

As the codebase grows the early design principles (frontend-first, reuse, foolproof-UI) get lost and slices ship "done" while real user-facing gaps remain. A slice is NOT done until this gate passes - the reviewer checks it, and every subagent brief must carry it:

1. **Mock swapped to real.** A frontend-first phase-1 mock (an in-memory `*-service` like `event-billing-service.ts`) is DEBT, not done. The slice is incomplete until the real backend is wired AND verified showing real data. Tag every mock loudly (`PHASE 1 MOCK`) + log a backlog item; never let a mock reach a "verify from the user's perspective" QA pass. (Cost us a whole cluster of fake Aisha/Marcus ticket rows.)
2. **New column/engine on an EXISTING entity needs a BACKFILL migration**, not just seed-if-absent. Adding the status engine to `tickets` left old rows `status_id=NULL` (transition-from-None 500) and existing tenant graphs un-seeded. `update_tenant` seed-if-absent does NOT repair rows/graphs that already exist - ship a backfill (legacy enum → status_id; repair existing tenant graphs).
3. **Tenant-editable KEYS are a code contract.** Code that looks a status up by key (`"issued"`, `"transferred"`) breaks the instant a tenant renames it. Either lock keys from tenant editing (system rows) or never hardcode-lookup an editable key. (A tenant forked the ticket graph to Draft/Confirmed → every scan/transfer 409'd.)
4. **A new core/module permission does NOT reach existing tenants' Admin** - the grant is computed at provision/seed. Adding a perm needs a grant sweep (migration or `tenant_admin_grant` re-run) for existing tenants, else the feature silently 403s / the action is invisible. (Recurring - the Nominate action was hidden until re-granted.)
5. **Verify end-to-end with REAL data from the user's perspective**, at 375px AND 1280px, on a freshly REBUILT frontend (`rm -rf .next && npm run build`) against correctly-owned ports (3001 frontend, 8001 = Foundryx - kill any sorento squatting 8001). Tests passing ≠ user-verifiable: conftest uses `create_all`, so a broken Alembic migration (e.g. a revision id > 32 chars vs `alembic_version.version_num VARCHAR(32)`) passes the suite yet breaks every real deploy.

### Agents-team orchestration (what works - sprint-4/05)
Building a slice with a subagent team (coder → tester → reviewer, looped on findings) held quality far better than solo as the codebase grew. Make it repeatable:
- **Every coder/tester brief MUST embed the Definition-of-Done gate above + the hard-fail rules** - a subagent starts with zero project memory, so the brief is its only guardrail. Don't assume it knows frontend-first/reuse/foolproof-UI; state them.
- **Audit before building.** An Explore agent producing a per-AC gap matrix (backend exists? frontend exists/mock/missing?) before any coder runs prevents building blind and surfaces the mock/backfill/perm gaps early.
- **Sequential coders on a shared branch** (not parallel same-tree) when tasks touch overlapping files - parallel edits to one working tree race. Use worktree isolation only when tasks are file-disjoint AND each worktree has its own node_modules/.venv.
- **Tester verifies from the USER's perspective** (real clicks, real data, fresh build) and writes an AC-id-keyed PASS/FAIL/DEFERRED report - not just green pytest. The reviewer re-checks the recurring-gap gate, not only correctness.
- **A deploy drain is not a run boundary.** Blue/green stops the old colour after 30s; any worker job longer than that (a 4-minute PO sync, 2026-09-07) dies mid-run with its `running` status intact and its task skipped by every later tick. A long job must heartbeat at every checkpoint and a sweep (startup + scheduler) must release the orphan; a human running SQL is the failure mode, not the fix (`storage-and-background-jobs.md`, job liveness bullet).

## AutoCount Service reference tables + gotchas (plan 22, sprint-5/01..08)

`modules/autocount/` (ERP -> Sorento ESB): a task's `AcEntityConfig.source_impl` decides
which extraction engine reads it. `autocount_http` (sprint-5/08, AC-08-40) is the newest and
the ONLY open-(no-auth)-connection path; the earlier two stay the SQL/legacy-vendor-API
options.

### Source-impl table

| `source_impl` | Reads | Registered in | Notes |
|---|---|---|---|
| `sql_db` | Direct read-only SQL, any dialect | `sql_source/source.py` (`register_sql_db_source`) | plan 22; the paged watermark loop lives in `sync.py`'s `_run_paged_sql_db` |
| `autocount_http` | AutoCount's own open (no-auth) REST API, one page at a time | `http_source/source.py` (`register_http_source`) | sprint-5/08; only the six entities in `presets.HTTP_ENTITY_TYPES` (product, customer, warehouse, product_category, brand, unit_of_measure) |
| `autocount_read` | Legacy session-authenticated vendor HTTP wrapper | `sources.py` (`_autocount_read_factory`) | plans 13-16; still the path for SO/PO/SPO document tasks against a BASIC-auth connection |

### `autocount_http` preset table (`presets.HTTP_PRESETS`)

| Entity | Path | Key field(s) | Watermark | `distinctOf` |
|---|---|---|---|---|
| product | `/itembypage` | `ItemCode` | `LastModified` | - |
| customer | `/debtorbypage` | `AccNo` | `LastModified` | - |
| warehouse | `/location` | `Location` | none | - |
| product_category | `/ItemGroup` | `ItemGroup` | none | - |
| brand | `/ItemBrand` | `ItemBrand` | none | - |
| unit_of_measure | `/itembypage` | `value` (synthetic) | none | `BaseUOM`, `SalesUOM`, `PurchaseUOM` |

### Run-mode table (shared by `sql_db` and `autocount_http`)

| Mode | Trigger | Behaviour |
|---|---|---|
| `manual` | operator clicks Run Now / Preview | one pass against the watermark (a full extract only when the task has no watermark field) |
| `incremental` | sweep, due `next_incremental_at` | same read as `manual`, scheduled |
| `reconcile` | sweep, due `next_reconcile_at`, or an operator repush | full extract, hash-diffs every row against `ac_row_hash`, stages missing refs as deletes (20% / 50-row safety guard) |

### Gotcha: `pageSize` above ~1000 silently clamps, trust the ECHOED paging fields

`autocount_http`'s page walk REQUESTS `pageSize=1000` (`http_source/source.py:
DEFAULT_PAGE_SIZE`), but the live wrapper (`hapi.sorento.cc.cd`) has been observed CLAMPING a
larger request (5000 tried live) down to roughly 200 with no error status at all - it just
echoes the CLAMPED `PageSize`/`TotalPages`/`Page` back in the response body. The walk loop
must therefore trust the ECHOED values on every page, never the value it requested, and must
never assume the population fits in one page just because the requested `pageSize` implied it
would.

### AutoCount human-invoked pull (plan 10, sprint-5/10) - what each stage owns

The pull path is a SNAPSHOT builder, not the push path's staged-diff machinery - no
`ac_staged_record`, no `ac_row_hash`, no watermark advance, ever (D6). Four stages, in order:

- **Delivery mode** - `delivery_mode` on the EXISTING `ac_entity_config` task row (`push`
  default), activated per (company, entity) pair. A `pull` task never runs on the 60 s sweep; a
  build is always operator- or consumer-triggered (D1/D2). `stock_balance` is pull-only today,
  gated by contract version (D4) - the Push option is hidden, not removed, and opens with no code
  change once Sorento serves contract 2.5 (BL-SS-207).
- **Lookups / enrich** - a GENERAL, operator-configurable ordered list on ANY HTTP task (D3, R9),
  not a product-only block: N endpoints, N join pairs, operator-named aliases, multi-hop by
  evaluation order. Values MERGE onto the source row before de-dup/hash/mapping, so an alias reads
  as an ordinary column everywhere downstream. Preview matched/missed counts are a 50-row SAMPLE
  of BOTH the main page and the lookup page (BL-SS-222) - never the population; the S2 editor must
  label them as samples, not totals. A formula naming an alias fails to PARSE (not just returns
  null) on a row that missed the lookup, because the miss leaves the alias key absent from
  `known_variables` (BL-SS-221).
- **Combine/reduce** - a general, operator-configurable step on ANY HTTP task (D5, R11): computed
  columns, require rules, group-by with measures and carried columns, per-measure rounding,
  ordered drop rules - bounded (one per task, no joins, no nested grouping) and expressed entirely
  in the EXISTING formula engine, never a hand-rolled reducer. Each formula stage gets its OWN
  variable scope (D32) - a forward reference or a post-group name used pre-group is a save-time
  422, not a runtime surprise. `combine: null` on the wire CLEARS the stored block; an omitted key
  KEEPS it; a cleared combine is never auto-reseeded from the preset (D29). The ONLY place a
  require/drop formula's return-type is checked against REAL sample data is `preview_http`
  (BL-SS-226) - a real task Save has no stored sample to check against.

### The 2026-09-20/21 worker-starvation incident, and the rule it teaches (plan 11 S1)

`foundryx_ss_worker_workflow` ran `celery -A app.workflow_engine.worker worker -Q workflow`
with no `-c` on a 1-vCPU host, so there was exactly ONE `ForkPoolWorker` on the whole
`workflow` queue - and `jobs.run` (the generic `background_jobs` dispatch task; in this case
an AutoCount supplier sync) shared that ONE process with every 60s beat tick in the platform
(`workflows.run_due`, `autocount.etl_sweep`, `status.reevaluate_time_based`, ...). A `jobs.run`
for that sync started 2026-09-20T17:15:33Z and never returned. Every beat tick after it was
published, received by the worker's `MainProcess`, and never executed for 8+ hours - **the
diagnose signature is "received by MainProcess, never executed"**, not a missing/failed
publish; check `celery events`/logs for a task that shows as received with no matching
"succeeded"/"failed" line, not a broker-connectivity symptom. Beat itself was healthy the
whole time (it kept publishing on schedule) - a beat-side heartbeat would have reported
everything fine, which is why the liveness signal has to be stamped by the CONSUMING worker,
per queue, not by beat.

Three compounding gaps, all present at once: (1) no `task_time_limit`/`task_soft_time_limit`
anywhere on the app, so a hung task holds its slot forever; (2) no
`worker_prefetch_multiplier` set (Celery default 4), so the blocked child could hold several
beat messages in its prefetch buffer at once; (3) `create_engine` passed no `connect_args`, so
worker Postgres sessions had no `statement_timeout`/`lock_timeout`/
`idle_in_transaction_session_timeout` - the vendor HTTP client and the Sorento sink both carry
their own timeouts, so whatever hung was something with none (a Postgres lock wait or a raw
driver socket). And the reason the symptom lasted 8 hours instead of 15 minutes: the ONLY
caller of the orphan sweep outside app startup was the AutoCount scheduler's own beat tick -
itself queued behind the very job it exists to recover from.

**The rule this incident teaches (D16): a sweep - or any recovery/liveness mechanism - must
never share a queue with the jobs it recovers from.** Concretely (sprint-5/11 S1,
`app/workflow_engine/worker.py`): `jobs.run` now routes onto a dedicated `jobs` queue with its
own compose worker (`worker_jobs`, lossless rollout - `worker_workflow` keeps the task
registered so an already-queued message still runs); `worker_prefetch_multiplier=1` on the
shared app; every task is time-limited (tick family: soft 300s/hard 330s app defaults;
`jobs.run`: its own generous settings-driven bound, `background_job_soft_time_limit_seconds`,
default 7200s, sized above the longest legitimate build); a wedged `jobs.run` fails
cooperatively on `celery.exceptions.SoftTimeLimitExceeded` (`app/jobs/service.py::run_job`,
caught BEFORE the generic `except Exception` so it gets its own sentence and closes module
bookkeeping via the shared `close_module_bookkeeping` helper, never the generic "Job crashed"
text); the orphan sweep gets its OWN 5-minute beat tick (`jobs.sweep_orphaned`) explicitly
routed onto `workflow`, decoupled from the AutoCount scheduler entirely; worker Postgres
sessions get settings-driven timeouts via `app/database.py::worker_connect_args()`, wired ONLY
into the worker compose services, never the API; and `ops.ping` stamps a per-queue Redis
liveness key every 60s, read by the operator route `GET /platform/ops/queues` - a wedged
worker is now visible within minutes, not discovered by hand hours later.

**The other half of the same incident class (2026-09-21), and the rule S2 teaches: a RUNNING
sweep does not cover a message that never arrives at all.** A `sales_order` `autocount_sync`
job was created `pending` right as a deploy restarted the `worker_jobs` process - the Celery
message itself was lost, so the job could never become `running` and therefore never trip
`fail_orphaned_running_jobs` (RUNNING-only by design). Every scheduler tick afterwards wrote a
`skipped` run ("A run for this task was still in progress") because the AutoCount overlap
guard's own liveness check only judged a RUNNING in-flight job; a PENDING one of any age read
as "a backlogged queue", exactly the assumption this incident breaks. The job sat for 8+ hours
until the owner reset it by hand in SQL (job -> `failed`, `ac_sync_run` -> FAILED/Interrupted).
Owner ruling R6 (D12/D13): undispatched pending jobs are FAILED, never re-dispatched - a
re-enqueue could race the original lost message if it is somehow delivered late, and two
workers executing the same job would double-push; failing costs one minute; the next tick
finds nothing in flight and enqueues a fresh job. `JobService.fail_undispatched_pending_jobs`
(sprint-5/11 S2, `app/jobs/service.py`) fails every job with `status == pending` AND
`started_at IS NULL` AND `created_at` older than
`background_job_undispatched_after_minutes` (default 60, floor 15 - higher than the
RUNNING-orphan floor of 5, because a busy queue can legitimately sit PENDING far longer than a
heartbeat gap) with its own `UNDISPATCHED_ERROR` sentence (never the RUNNING sweep's
`ORPHANED_ERROR` - a lost message and a dead worker are different incidents), and - UNLIKE the
RUNNING sweep - is NOT restricted to `heartbeats=True` types, because a job that never started
never had a chance to declare liveness at all. It closes module bookkeeping through the same
`close_module_bookkeeping` helper S1 extracted, so an open `ac_sync_run` row closes identically
regardless of which sweep caught the job. `jobs.sweep_orphaned` (the S1 beat tick, still on
`workflow`, still every 5 minutes) now runs BOTH sweeps in one invocation, so every job type
recovers without a scheduler in front of it; the AutoCount scheduler's own overlap guard gets a
sibling branch next to its RUNNING-orphan branch, sweeping exactly the stale PENDING in-flight
job by `job_id` and proceeding with the tick, one-for-one with the RUNNING case. A fresh
PENDING job (genuinely queued, not lost) is left untouched either way.
- **Snapshot store + gateway** - a pull run writes ONE immutable snapshot row + its pages, kept
  for the newest 3 per (company, entity) with a 24 h TTL (module constants today, BL-SS-231). The
  public gateway (`/api/v1/autocount`, D8/D9, `X-API-Key`) and the session-authed operator routes
  (`/autocount/pull`) both project the SAME `snapshot_header`/`gateway_snapshot_header` but with
  DIFFERENT field names by design (`id`/`entityType`/`companyId` vs `snapshotId`/`entity`/
  `companyCode`, BL-SS-228) - never assume the two schemas should converge. Every gateway response
  carries `Cache-Control: no-store`; `page` is REJECTED past `1000000`, never clamped (only
  `pageSize` clamps). See `documentation/plans/sprint-5/10-autocount-pull-review.md` Appendix A6
  for the full, code-verified error-code ladder (six codes were added by the S4 security round and
  went undocumented in the contract table for a full sprint - re-grep `code="` on every gateway
  file whenever that appendix is touched, don't trust the table alone).

### Agent-process lessons (plan 10 S6 docs pass, 2026-09-20)

- **A tester agent must never edit application code, even as a throwaway scratch check** - a
  scratch edit left uncommitted in a shared worktree is indistinguishable from a real change to
  the next agent reading `git status`, and a shared Postgres means a "just checking" code path can
  have side effects.
- **`git stash` is forbidden in a shared worktree** (repeated house rule, worth restating because
  plan 10's lane hosted coder, tester AND reviewer sessions across the same checkout at different
  times) - the stash stack is process-global; a bare `git stash`/`pop` can swallow or apply another
  session's work. Use a tagged WIP commit instead.
- **A coder should diff their OWN pathspec before committing**, not `git add -A` - a shared
  worktree accumulates other agents' in-flight edits (evidence dirs, scratch files) that a broad
  add would sweep into an unrelated commit.
- **`pytest tests/test_s10_` (bare prefix, no glob) collects ZERO tests** - pytest treats a bare
  string as a path, not a name filter; the working forms are `pytest tests/ -k test_s10_` or a
  real glob the shell expands (`pytest tests/test_s10_*.py`).
- **`test_autocount*.py` does NOT match `test_s10_*.py`** - this plan's ~90 S1-S6 test files are
  ALL named `test_s10_<slice>_<topic>.py`, a disjoint prefix from the module's ~45 pre-existing
  `test_autocount_*.py` files. A "run the autocount suite" command using only the old glob silently
  skips every plan-10 test with no error.
- **A dirty working tree is not evidence of anything** - `git status --short` showing modified
  files proves edits exist, not that they are correct, tested, or even related to the task at
  hand; always re-run the specific test/build that proves the claim, never cite tree dirtiness as
  a substitute.
