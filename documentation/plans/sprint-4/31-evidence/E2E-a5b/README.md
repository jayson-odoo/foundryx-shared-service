# Plan 31 (omnichannel workflow parity) - A5b (S4-S6) independent tester evidence run

Recorded with `agent-browser` (session `s31t2`, plus a throwaway `s31t2http` session for the
`workflows.http` FE-palette-disabled re-check with a fresh JWT). Real clicks from `/` via the
sidebar throughout - no typed URLs except where explicitly noted as a setup call outside the UI
(operator tenant provisioning, direct API calls for permission grants/revokes, the dev-safe
webhook, and the inline sweep - all listed verbatim below). Lane: backend `:8010` on
`foundryx_service_s31` (restarted this run - see "Environment" below), frontend `:3009` (prod
build, unchanged/fresh from the S6 coder's own rebuild - no source file newer than `.next/BUILD_ID`).

Covers **AC-WFP-41..70** (A5b: waits, ask-a-question runtime, business hours, HTTP request),
plus a re-spot-check of AC-WFP-01..06 (palette catalog) incidental to this session's fresh-tenant
build. Independent from the coder's own `S6/README.md` run - no screenshots or run data reused.

## Environment

- **Backend restarted.** At session start `git log -1` showed HEAD `eb4ff83f` (S6 commit,
  2026-09-07 04:52:54) committed AFTER the running uvicorn process (PID 90756, started 02:09:28) -
  per the brief's restart rule, killed 90756 and started a fresh uvicorn (PID 80778) with the
  exact same env the lane's `.env` + prior README document (`DATABASE_URL=...foundryx_service_s31`,
  `CELERY_TASK_ALWAYS_EAGER=true`, `CORS_ORIGINS`/`CORS_ORIGIN_REGEX` including `:3009` - verified
  already present on the process's own env, re-supplied verbatim on restart). **`git status` was
  clean (nothing to commit) at the exact moment of this restart** - the running server therefore
  reflects committed `eb4ff83f` byte-for-byte for the ENTIRE duration of this tester's live
  E2E session (no `--reload`, so later on-disk changes - see below - never reached it).
- Frontend: `.next/BUILD_ID` predates every source file (S6 coder's own clean build); PID 92028
  cwd-verified into the s31 worktree; left untouched (no FE change this slice).
- Demo login used only for the pre-existing default tenant B check (`demo@example.com`); the main
  journey used a **dedicated timestamped tenant** (below).
- **Concurrent uncommitted changes observed** (discovered mid-session via `git status --short`,
  independently of the pytest surprise below): 18 modified files across
  `app/services/{url_guard,workflow_service}.py`, `app/workflow_engine/{executor,registry}.py`,
  `app/workflow_engine/actions/http_actions.py`, `modules/omnichannel/services/{business_hours,
  webhook_service,workflow_actions,workflow_waits}.py`, 4 backend test files, 2 frontend
  business-hours-tab files + their tests, plus `documentation/backlogs/backlog.md` and the plan
  file - **none of them touched by this tester**. The diff's own new test docstrings label
  themselves "review round 1" / "B1" - this is a reviewer or coder actively mid-fix on this
  shared worktree DURING this tester's session (same class of event the A5a report's own
  "Environment note" flagged). Per the concurrent-user-git convention, these files were left
  completely untouched - not read further than a `git diff` to understand one pytest failure
  (below), not staged, not stashed.

## Setup calls made outside the UI (verbatim)

**1. Provision the dedicated tenant** (operator API, `platform@example.com` on `platform.localhost:3009`):
```
POST /auth/login {"email":"platform@example.com","password":"platform1234","tenantSlug":"platform"}
POST /platform/tenants {"name":"S31 A5b Tester 20260907-045642","slug":"s31-a5b-tester-20260907-045642",
  "adminEmail":"s31a5b+20260907-045642@example.com","adminName":"S31 A5b Admin","adminPassword":"Tester12345!"}
```
Everything else on this tenant (installing Omnichannel, connecting the sandbox channel, building
the workflow, editing business hours) is real clicks - see the numbered flow below.

**2. Drive the workflow via the dev-safe inbound webhook** (`curl`, `ENVIRONMENT=development`, no
`META_APP_SECRET` = signature check dev-open) - channel id `8a8a28a2-b79c-4659-bc96-999ba3f97870`
(this tenant's own sandbox channel, NOT `chn-demo`):
```
POST http://localhost:8010/omnichannel/webhooks/8a8a28a2-b79c-4659-bc96-999ba3f97870
  {"object":"whatsapp_business_account","entry":[{"id":"waba-901","changes":[{"field":"messages",
   "value":{"messaging_product":"whatsapp","contacts":[{"wa_id":"<phone>","profile":{"name":"<name>"}}],
   "messages":[{"id":"wamid.a5b-<epoch>-<n>","from":"<phone>","timestamp":"<epoch>","type":"text",
   "text":{"body":"<text>"}}]}}]}]}
```
Run 4 times total across 3 contacts (`+60199771001` opening + invalid "Blah" + valid "Sales";
`+60199771002` opening only, then timed out via the sweep below; `+60199771003` opening + valid
"Sales" answered under the narrowed business-hours window).

**3. Force the 1-hour Ask-a-question timeout inline** (no beat under eager dev, exact recipe from
`docs/reference/process-lessons.md` / the S6 README - module nodes booted FIRST, else "Unknown
action" as the S6 coder also found):
```python
from datetime import datetime, timedelta, timezone
from app.database import SessionLocal
from app.workflow_engine.worker import _ensure_module_nodes
from modules.omnichannel.services.workflow_waits import sweep_due_waits
_ensure_module_nodes()
db = SessionLocal()
sweep_due_waits(db, now=datetime.now(timezone.utc) + timedelta(hours=2))
# -> {'resumed': 1, 'discarded': 0}
```

**4. Cancel a WAITING run** (no UI action exists for this - `BL-SS-109` "parked-run operator view"
is explicitly DEFERRED/not built; used the documented REST endpoint directly as the tenant admin):
```
POST /workflows/runs/{run_id}/cancel   (Authorization: Bearer <tenant admin JWT>)
-> {"status":"cancelled", ...}
```
Used twice: once on a real inbound-started run (AC-WFP-52), once to clean up the manual test run
parked for AC-WFP-53 after confirming its `is_test=true` wait row.

**5. `workflows.http` permission gate** (RBAC write endpoints only need `roles.update`, which
Admin always holds - same pattern the S6 README used):
```
GET  /roles/{adminRoleId}                          -> confirm workflows.http present (110 perms)
PATCH /roles/{adminRoleId} {"permissionKeys":[...109 minus workflows.http]}
POST /workflows {"name":"..."}                      -> 200 (bare create, no HTTP node yet)
PATCH /workflows/{id} {"name":"...","draftDefinition":{... an http.request node ...}}
-> 403 {"detail":"Missing permission: workflows.http"}
DELETE /workflows/{id}                              -> 204 (cleanup)
PATCH /roles/{adminRoleId} {"permissionKeys":[...110 incl. workflows.http]}   (restore)
```

**6. AC-WFP-51 publish-refusal re-check** (parallel-mode graph carrying an Ask node):
```
POST /workflows {"name":"S31 A5b publish-refusal probe"}
PATCH /workflows/{id} {..., "execution":{"mode":"parallel"}, draftDefinition with an
  omnichannel.ask_question node}
POST /workflows/{id}/publish
-> 422 {"detail":"Ask a question requires serialized execution and a Correlation key."}
DELETE /workflows/{id}   -> 204 (cleanup)
```

**7. Direct DB reads** (read-only `SELECT`s via the venv python, `foundryx_service_s31`) to pin
exact run/node/wait-row state between UI steps - never a write outside the app's own service
layer (all writes above went through the real REST API).

## Dedicated tenant + residue left behind (by design, timestamped, audit-kept)

- Tenant `s31-a5b-tester-20260907-045642` (admin `s31a5b+20260907-045642@example.com` /
  `Tester12345!`), Omnichannel installed, one sandbox channel ("Foundryx Events Co.",
  `+65 8900 1234`), workspace "General" with business hours narrowed to Monday 08:00-18:00
  Asia/Kuala_Lumpur (was always-open at session start, edited mid-run for the outside-hours
  test - AC-WFP-56).
- One published, Active workflow **`S31 E2E A5b Tester 20260907-050427`** (serialized by key,
  correlation `{{ trigger.contact.id }}`): trigger -> Ask a question (choice, Sales/Support, 1h
  timeout) -> Business hours -> two Send Message nodes, plus an HTTP request node off the
  timeout port. 4 runs on it: 2 Success, 1 Failed (SSRF refusal), 1 Cancelled.
- 4 contacts (`S31 A5b Contact One/Two/Three/Four Cancel`).
- Two throwaway probe workflows (HTTP-header-redaction check, publish-refusal check) were
  created and explicitly `DELETE`d after use - not left behind.
- Left intact for audit, same convention as the S6 README's `s31-httpcheck-<epoch>` tenant.

## Flow (numbered, screenshots in this directory)

1. Provisioned tenant (setup call). Signed in at
   `http://s31-a5b-tester-20260907-045642.localhost:3009/`.
2. Sidebar Apps -> App Store -> Omnichannel module card -> Actions -> Install -> sidebar gains
   the Omnichannel section (`01`).
3. Omnichannel -> Channels -> Connect channel -> "Connect (sandbox)" (Meta env unset on this
   lane, so even Embedded Signup is dev-safe) -> simulated Facebook popup -> Authorize -> Sandbox
   channel created -> Done (`02` 1280px, `03` 375px).
4. Omnichannel -> Workspaces -> General -> **Business hours tab** (AC-WFP-63): read view all
   "Closed" (fresh tenant, no S5-probe residue this time) - `04`. Edit -> set Monday's window to
   09:00-09:00 (from==to) -> Save -> inline "End time must differ from the start time." on the
   Monday row only, both time inputs ring red, shell stays in edit mode - `05` (edit view), `06`
   (1280px 422), `07` (375px 422, no clipping). Cancel -> "Discard changes?" AlertDialog (`08`,
   375px) -> Discard -> reverts to the pre-edit (empty/Closed) state, confirming the dirty-guard
   round-trips even from a fresh (never-saved) workspace - `09`. Edit again -> Asia/Kuala Lumpur +
   Monday 00:00-23:59 -> Save -> persists correctly - `10`.
5. Workflows -> New workflow -> Settings: name, execution mode **Serialized by key**, correlation
   key `{{ trigger.contact.id }}`. Editor: Triggers(18)/Logic(3)/Actions(24) confirmed on the REAL
   registry for a completely fresh tenant (re-spot-checks AC-WFP-01 independently of the demo
   tenant) - added **Incoming omnichannel message** (`11`/`12`).
6. Click-to-add: Ask a question, Business hours, Send Message x2, HTTP request - Tidy - `13`-`15`
   (collapsed sidebar for canvas room, matching the S3/S6 pattern).
7. Configured each node (`16`-`19`): Ask a question (contact merge field, message, **Answer type
   dropdown showing exactly Text/Choice/Number/Email/Phone** - AC-WFP-18/D-A5-18 - Choice selected,
   "Add choice" rendered ONLY after Choice was picked - AC-WFP-64 - two choices Sales/Support,
   re-ask message, default 1 Hour timeout); Business hours (Workspace = General, the tenant's
   only workspace - AC-WFP-03); two renamed Send Message nodes; HTTP request (renamed "Probe a
   blocked internal address", `GET https://127.0.0.1:9/probe` - **loopback substituted for the
   plan's literal `169.254.169.254`, per this brief's own instruction not to type the
   cloud-metadata address** - exercises the identical `url_guard` refusal path, pytest-pinned
   separately for the literal address). One duplicate unconfigured "HTTP request" node (an
   artifact of a `find text` locator matching the palette card instead of the canvas node) was
   caught via `document.querySelectorAll('[data-testid^="workflow-node-"]')` and deleted before
   wiring - `19` is the surviving, correctly-configured node.
8. **Wiring** - real React Flow handle drags (`mousedown` on the exact handle DOM element, several
   `mousemove` on `document`, `mouseup` on `document`) for all 5 edges: trigger->Ask, Ask
   `answer`->Business hours, Business hours `inside`->Send-inside, Business hours
   `outside`->Send-outside, Ask `timeout`->HTTP. One wire (trigger->Ask) initially silently
   no-opped because `document.elementFromPoint` at the handle's own screen coordinate resolved to
   the PALETTE aside sitting visually on top of it (confirmed via a diagnostic `elementFromPoint`
   call) - fixed by dispatching `mousedown` directly on the handle DOM element instead of via
   `elementFromPoint`. `document.querySelectorAll('.react-flow__edge').length` confirmed 5/5 -
   `20`-`22` (BL-SS-123-class live two-port re-verify: Ask's `answer`/`timeout` and Business
   hours' `inside`/`outside` both wireable and both fired correctly across the 3 real runs below).
9. Settings -> Active on -> Save. Editor -> **Publish** -> "Published - the trigger can now fire
   this workflow." (no error - AC-WFP-51's ACCEPT case) - `23` (1280px), `24` (fit-view),
   `25` (375px, tabs/breadcrumb/canvas all reflow with no clipping).
10. **Run 1** (contact `+60199888110`→ actually `+60199771001`, "S31 A5b Contact One") - 3 inbound
    webhooks (setup call #2): opening message -> question with numbered choices sent, run
    `waiting`/`paused_node_id=act_akr7cz` (DB-checked) -> `26`; invalid "Blah" -> live WS re-ask
    message, `retry_count` 0->1 -> `27`; valid "Sales" -> run `success`, wait row deleted (0
    remaining, DB-checked), inside-hours message landed (`28`). Logs: run Success, replay green
    end to end - `29`; Ask a question node clicked -> badge **success** (not phantom), output
    EXACTLY `{"answer":"Sales","answerRaw":"Sales","answerKey":"1","timedOut":false,"reason":""}`
    - AC-WFP-64's port contract - `30`.
11. **Run 2** (contact `+60199771002`) - opening webhook parks a second run; reloaded Logs BEFORE
    sweeping -> distinct blue **"Waiting"** badge in the run list (AC-WFP-65) - `31`/`32`; clicked
    into it, Ask a question node shows badge **"waiting"** (not success, not failure), output
    `{"parked":true,"waiting":true,"kind":"question",...}` - the exact S4 park contract - `33`.
    Forced the timeout (setup call #3, module-boot-hook-first recipe - the S6 coder's own
    documented gotcha, reproduced correctly on the first attempt this run). Reloaded: run **Failed**
    with the run-level banner "Node failed: URL refused: URL cannot target a private or reserved
    IP." - `34`; HTTP node clicked -> RESOLVED INPUT `{"url":"https://127.0.0.1:9/probe"}` (no
    header values - headers were empty this run), OUTPUT `-` (no response captured - confirms no
    request left the process), ERROR the exact refusal string - `35`; Business hours node clicked
    -> badge **"skipped"** (untaken branch, since the ANSWER port was never taken) - `36`.
12. **AC-WFP-56 outside-hours re-check** (this tester's own addition, not in the S6 coder's run):
    edited Business hours to Monday 08:00-18:00 (excludes the actual KL wall-clock time,
    05:19-05:22 across these steps) - `37`. **Run 3** (contact `+60199771003`) - opening + valid
    "Sales" answer BOTH sent immediately (no forced sweep) so Business hours evaluated for real
    at the current out-of-window time: DB + Logs UI both show
    `{"isOpen":false,"checkedAt":"2026-09-06T21:20:47Z","timezone":"Asia/Kuala_Lumpur",
    "branch":"outside"}` - the `outside` port fired, the outside-hours Send Message node
    succeeded, the inside-hours one skipped - `38` (closes AC-WFP-56 for BOTH branches
    independently, not just the always-open case Run 1 exercised).
13. **AC-WFP-52** (cancel a WAITING run): started Run 4 (contact `+60199771004`, "... Four
    Cancel"), no UI cancel action exists (`BL-SS-109` deferred, confirmed by inspecting the full
    Logs-tab snapshot - no such button rendered), cancelled via the documented REST endpoint
    (setup call #4) -> `{"status":"cancelled"}`; DB confirmed 0 wait rows remaining tenant-wide;
    Logs UI shows the distinct grey **"Cancelled"** badge - `39`.
14. **AC-WFP-53** (test/manual run parks with a sandbox wait): Editor -> Run -> Test workflow
    dialog (channel + contact + message, real picker) -> "Run started" -> Logs shows a fresh
    **Waiting** run - `40`; DB confirmed the new wait row `is_test=true` and the run `is_test=true`
    - the exact AC-WFP-53 contract. Cancelled it afterward via the same REST endpoint to leave no
    parked run behind.
15. `41`: Logs tab at 375px (4 runs by this point: Cancelled/Success/Failed/Success, each badge
    legible, run cards reflow with no clipping - the mobile half of AC-WFP-65).
16. **`workflows.http` permission gate** (AC-WFP-37/59-61, setup call #5): revoked the permission
    from this tenant's OWN Admin role, confirmed `PATCH /workflows/{id}` carrying an
    `http.request` node -> **403 "Missing permission: workflows.http"** at create/update time
    (stricter than "only at publish") on a bare probe workflow (cleaned up after). Fresh
    re-signed-in session (`s31t2http`) -> New workflow -> Actions -> **"HTTP request" renders
    visible-but-disabled** (`disabled` attribute confirmed in the snapshot, not omitted like a
    module-gated entry) - `42`; clicking it added 0 nodes
    (`document.querySelectorAll('[data-testid^="workflow-node-"]').length` stayed 0 before AND
    after the click). Restored the permission afterward.
17. **AC-WFP-51 refusal re-check** (setup call #6): a parallel-mode graph carrying an Ask node was
    refused publish with the exact documented message - `422 "Ask a question requires serialized
    execution and a Correlation key."` (the ACCEPT case was already demonstrated at step 9; this
    pins the REFUSE case too). Probe deleted after.
18. **AC-WFP-57/59 public-HTTPS + header-redaction re-check** (a focused throwaway workflow,
    Manual trigger -> HTTP request `GET https://example.com/` with header
    `X-Test-Secret: super-secret-value-should-not-appear-in-trace`) - `43` (node configured, real
    outbound internet confirmed reachable from this lane). Saved, wired (a second motion-wrapper
    "Add row"/"Save workflow" click-swallow was worked around the same way as the earlier
    "Add choice" case - real pointer-event dispatch on the exact button element), Run -> Logs ->
    **Success**, 200, real HTML body captured (`44`-`46`). **RESOLVED INPUT correctly showed ONLY
    `{"url":"https://example.com/"}` - no header values, matching AC-WFP-59's "resolved" half.**
    **However the separate raw "INPUT" panel (bound directly to `WorkflowRunNode.input_json` -
    confirmed via `components/platform/workflow-runs/run-replay.tsx:170`,
    `<DataBlock label="Input" value={selectedData?.inputJson}/>`) showed the header VALUE
    `"super-secret-value-..."` in full, verbatim, inside `config.headers[0].value`** - see
    "Defect" below. `47`: 375px screenshot of the same trace panel (still shows the leak at
    mobile width, ruling out a viewport-specific rendering difference).

## Defect found - AC-WFP-59 (header values reach the run trace)

**Given** an HTTP request node whose header value is a LITERAL string (the overwhelmingly common
authoring case - an API key pasted directly into the field, no merge token), **when** the node
runs successfully and an operator opens that run in the Logs tab (or calls
`GET /workflows/runs/{id}` with only `workflows.read`, a broader grant than `workflows.http`),
**then** the header VALUE is fully visible, verbatim, in the "INPUT" panel / `nodes[*].inputJson`
wire - contradicting AC-WFP-59's "header VALUES are never stored or logged (names only)".

**Root cause (read from source, not guessed):** the S5 slice's own design note
(`http_actions.py` docstring at the time of `393305f6`) correctly keeps the header field out of
the executor's MERGE-RENDERED "resolved" map (`ActionDef` fields are only auto-traced when flagged
`mergeable`, and `headers` is not) - this IS enforced and IS what "RESOLVED INPUT" correctly shows
(url only, confirmed live 3 times this run). But the RAW, UNRENDERED `config.headers[*].value`
- the literal string the author typed into the drawer, never a merge token in the common case -
is written into `WorkflowRunNode.input_json.config` regardless, via the SAME generic
`_node_input_json` helper every other action uses to store its raw config for the read-only
Editor/Logs display. Nothing masks it there. The plan's own risk section (`§7 "Header secrets"`)
anticipated exactly the merge-rendered half of this ("never written... via the raw config") but
the raw-config half was never actually masked.

**Independent corroboration found on this same worktree (not this tester's doing, not fixed by
this tester):** `git status` showed `service_backend/app/workflow_engine/actions/http_actions.py`
and `service_backend/tests/test_http_workflow_action.py` UNCOMMITTED-MODIFIED mid-session (see
"Environment" above). `git diff` on the test file shows a NEW/rewritten test
`test_a_literal_header_secret_never_reaches_the_run_trace` (docstring: "B1 (review round 1)")
asserting exactly `node.input_json["config"]["headers"][0]["value"] == "***"` - i.e. a reviewer
or coder on this shared worktree independently found and is actively fixing this SAME gap, in
flight, uncommitted. Running the full backend suite this run (see §Suites) surfaced this AS THE
ONLY failure in 3201 backend tests: `test_a_literal_header_secret_never_reaches_the_run_trace`
FAILED with `assert 'sk_live_LITERAL_SECRET' not in '...'` - the in-progress fix's own test,
failing against the not-yet-complete implementation. This tester did not touch either file; the
failure is reported as observed, corroborating (not duplicating) this tester's own independently
discovered live finding, made via the browser BEFORE this tester ran pytest or read any diff.

**Verdict:** genuine, reproducible defect against the code at HEAD `eb4ff83f` (verified live
against a server that loaded that exact commit and never reloaded). Appears to already be
mid-fix by another agent on this shared worktree (uncommitted) - not something for this tester to
fix (tester writes tests/evidence only) or wait on (an in-flight WIP is not "done" to build a
report against). Reported as **FAIL** against AC-WFP-59 below, with the repro above.

## Suites

| Suite | Command | Result |
|---|---|---|
| Backend | `python -m pytest -q -p no:warnings` (full suite, background, DATABASE_URL=foundryx_service_s31, CELERY_TASK_ALWAYS_EAGER=true) | **3200 passed, 1 FAILED, 1 skipped, 18 deselected** (1862s) - the 1 failure is the AC-WFP-59 defect above (`test_a_literal_header_secret_never_reaches_the_run_trace`); everything else green including the concurrently-modified `test_omnichannel_business_hours.py`/`test_omnichannel_workflow_waits.py`/`test_omnichannel_consumer_webhooks.py` |
| Frontend | `npx vitest run` (full suite, background) | **293 files / 2205 tests passed, 0 failed** |

**Caveat on the backend number:** this run's working tree carried the 18-file uncommitted WIP
described above for an unknown portion of its ~31-minute duration (first noticed mid-run, not
present at the run's start per the initial clean `git status`) - so "3200 passed" reflects a
MIXED committed-eb4ff83f-plus-in-flight-WIP tree, not a pristine read of the committed commit. It
is NOT re-run against a clean checkout of HEAD (would require stashing/disturbing another agent's
active uncommitted work, against the concurrent-user-git convention). The live-clicked E2E
evidence above is NOT subject to this caveat (the backend process loaded HEAD `eb4ff83f`
byte-for-byte at 04:54:56 and never reloaded, so every screenshot in this run reflects the
committed commit only).

Also observed (not investigated further, not this tester's process): two OTHER concurrent
`pytest` processes appeared and disappeared against the SAME `foundryx_service_s31` database
during this run (targeted subsets matching file lists from the S4/S5/S6 commit messages' own
"Verification" sections) - consistent with another agent iterating fixes+tests live on this
shared lane. `pgrep -fl 'python.*pytest'` before starting this tester's own suite showed zero
processes; the count never exceeded 2 machine-wide at any point this tester checked.
