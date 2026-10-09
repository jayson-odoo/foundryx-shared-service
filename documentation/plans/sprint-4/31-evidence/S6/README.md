# Plan 31 (omnichannel workflow parity) - S6 evidence run

Recorded with `agent-browser` against the live s31 lane (backend `:8010` on
`foundryx_service_s31`, frontend `:3009`, prod build, build id `OUC4cIGnQL_wGWu1pYeLX`).
Two browser sessions were used across the run (see "Session note" below); real
clicks from `/` via the sidebar throughout, no typed URLs. Every workflow/tenant
name created in this run is timestamped. Covers **AC-WFP-63..67, 69, 70** plus
**BL-SS-123** (AC-WFP-05 live-port re-verify).

## Session note (context reset mid-run)

The coding session was interrupted by a usage-limit reset partway through
building the workflow graph in agent-browser session `s31c2`. That session was
gone on resume (confirmed via `git -C .claude/worktrees/s31 status --short`,
`.next/BUILD_ID` vs source mtimes, and cwd-verified backend/frontend pids - all
unchanged, no rebuild needed). The half-built **unsaved** draft workflow in
`s31c2` was never persisted (`Save workflow` was never clicked in that
session), so nothing was lost - screenshots `01`-`13` (business hours tab +
the first attempt at adding nodes/configuring the Ask a question node) are
from `s31c2`; screenshots `14` onward are from a fresh session `s31c2b`
(re-signed-in, workflow rebuilt from scratch reusing the exact same node
configuration). `s31c2` was never explicitly closed (session vanished with the
reset); `s31c2b` and the later permission-check session `s31c2http` were both
closed individually at the end (never `close --all`).

## Environment

- Backend restarted (PID 90756, cwd-verified) with
  `DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_s31`,
  `CELERY_TASK_ALWAYS_EAGER=true`, and the lane's CORS override
  (`CORS_ORIGINS`/`CORS_ORIGIN_REGEX` including `:3009`, from `S3/README.md`)
  to pick up this slice's `pausedNodeId` schema addition.
- Frontend rebuilt clean (`rm -rf .next && npm run build`, then
  `npx next start -p 3009`, PID 92028, cwd-verified) after all S6 source
  changes.
- Demo login `demo@example.com` / `demo1234` (default tenant Admin) for the
  main journey. A throwaway tenant `s31-httpcheck-<epoch>` (provisioned via
  the platform API, not left behind on purpose - see the permission-gate
  section) for the `workflows.http` negative check.

## Part A - Business hours tab (AC-WFP-63)

1. Sign in, sidebar Home -> Omnichannel -> Workspaces -> open "General" -
   `01`.
2. Business hours tab (after Close reasons, before API Keys in the tab strip)
   - read view shows the always-open schedule (Asia/Kuala_Lumpur,
   00:00-23:59 every day - set by the S5 coder's live probe) - `02`.
3. Edit -> set Monday's window to `09:00-09:00` (from == to) -> Save ->
   inline field error "End time must differ from the start time." on the
   Monday row, both time inputs ring red, form stays in edit mode (no false
   success toast) - `03` (1280px), `04` (375px, tabs/fields reflow with no
   clipping).
4. Cancel -> the shell's "Discard changes?" AlertDialog fires (dirty-guard) ->
   Discard -> schedule reverts to the original always-open windows, shared
   workspace state left untouched - `05`.

## Part B - Build, wire, publish the A5b workflow (AC-WFP-64/66, BL-SS-123)

5. Workflows -> New workflow -> Settings tab: name
   `S31 E2E S6 A5b 20260907-021716`, Execution mode "Serialized by key",
   Correlation key `{{ trigger.contact.id }}`.
6. Editor tab, Triggers -> **Incoming omnichannel message** (channel "All
   channels") - `06`/`07` (18 triggers visible, confirming the live registry
   catalog, not the mock).
7. Logic section expanded (3 items: Condition/Wait/**Business hours**) +
   Actions (24 items incl. **HTTP request**) - `08` (BL-SS-123: the two-port
   node types now exist as real `ActionDef`s, unlike the S0 mock-only
   evidence).
8. Click-to-add (in order): **Business hours**, **Ask a question**, **Send
   Message** x2, **HTTP request** - `09`/`10` (Tidy applied; 6 nodes on
   canvas, unwired per the no-auto-connect rule).
9. Configured each node:
   - **Business hours**: Workspace = General - `11`.
   - **Ask a question**: Contact `{{ trigger.contact.id }}`, Message "Are you
     contacting us about Sales or Support?", Answer type **Choice**, choices
     "Sales" / "Support" (the `Add choice` / `Choice N` rows only render once
     Choice is selected - confirmed live), Retry limit 1 (default), Re-ask
     message "Sorry, please reply with either Sales or Support.", Timeout 1
     **Hour** (default) - `12` (matches AC-WFP-66's exact spec: choice, two
     options, 1 hour timeout).
   - **Send Message** (renamed "Send inside-hours message"): "Our team is
     online now - connecting you shortly!".
   - **Send Message 2** (renamed "Send outside-hours message"): "We are
     outside business hours right now - we will reply as soon as we are
     back.".
   - **HTTP request** (renamed "Probe a blocked internal address"): GET
     `https://127.0.0.1:9/probe` - `13` (see "SSRF target substitution" note
     below for why this URL, not the plan's `169.254.169.254`).
   - `14`: all 6 nodes configured, "5 issues to fix: Node is not connected to
     the trigger" (expected pre-wire).
10. **Wiring** (React Flow handle drags - real `mousedown`/`mousemove`/
    `mouseup` on `document`, per `docs/reference/process-lessons.md`; the
    canvas could not zoom out far enough to show all 6 nodes at once at
    `minZoom=0.5` in this container width, so each wire was made by panning
    the canvas background between the two endpoint nodes, confirmed by
    `document.querySelectorAll('.react-flow__edge').length` incrementing
    1->2->3->4->5 after each drag - screenshots `15`-`17` document the
    zoom/pan investigation):
    - trigger `out` -> Ask a question (target)
    - Ask a question `answer` -> Business hours (target)
    - Business hours `inside` -> Send inside-hours message (target)
    - Business hours `outside` -> Send outside-hours message (target)
    - Ask a question `timeout` -> Probe a blocked internal address (target)
    - `18`: first wire (trigger->ask) - the "issues" count drops 5->4.
    - `19`: **Tidy + Fit View after all 5 wires** - a single clean screenshot
      showing the full graph with labelled edges ("Timeout"/"Answer" off Ask
      a question; "Outside hours"/"Inside hours" off Business hours) exactly
      like the IF node's true/false convention (AC-WFP-05 live re-verify -
      **PASS**, closes BL-SS-123). No "issues to fix" banner - publish-ready.
11. Save workflow -> Settings tab -> Active switch on -> Save -> Editor tab
    -> **Publish** -> "Published - the trigger can now fire this workflow."
    (no error - `execution.mode=serialized` + a valid correlation key were
    already set) - `20` (1280px), `21` (375px - tabs, breadcrumb, and the
    read-only canvas all reflow with no clipping).
    - Workflow id: `41458f22-f047-44e6-b1f3-2500aa9c896d`.

## Part C - Drive it (AC-WFP-66/67)

Inbound messages are **simulated via the dev-safe webhook** (no real WhatsApp
number in this lane) - every inbound is a `curl` POST to
`http://localhost:8010/omnichannel/webhooks/chn-demo`, `ENVIRONMENT=development`
+ no `META_APP_SECRET` set = signature check is dev-open, matching the
existing `_wa_payload`/`_process` pytest fixtures' payload shape exactly.
Each is logged verbatim below.

### Run 1 - answer path (contact `+60199888110`, "S31 E2E Contact")

**Setup call 1** (first inbound message, starts the run):
```
curl -s -X POST "http://localhost:8010/omnichannel/webhooks/chn-demo" \
  -H "Content-Type: application/json" -d '{
  "object": "whatsapp_business_account",
  "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
    "messaging_product": "whatsapp",
    "contacts": [{"wa_id": "60199888110", "profile": {"name": "S31 E2E Contact"}}],
    "messages": [{"id": "wamid.s6-1788727044-1", "from": "60199888110",
                  "timestamp": "1788727044", "type": "text",
                  "text": {"body": "Hi, I need help"}}]
  }}]}]
}'
-> {"status":"queued"}
```
DB check: `workflow_runs` row `6b38432f-...` -> `status='waiting'`,
`paused_node_id='act_34n049'` (the Ask a question node id). Inbox: opened the
thread via sidebar Omnichannel -> Inbox -> the "S31 E2E Contact" row -> the
question message "Are you contacting us about Sales or Support? 1. Sales
2. Support" is visible, sent by the workflow - `22`/`23` (a pre-existing
unrelated seeded workflow from an earlier slice also fired a lifecycle
"TEMPLATE" message on this brand-new contact - visible in the thread above
our question; harmless residue from a prior evidence run's still-published
workflow, not part of this slice).

**Setup call 2** (invalid answer, AC-WFP-67):
```
curl ... -d '{... "messages": [{"id": "wamid.s6-...-2", "from": "60199888110",
  "timestamp": "...", "type": "text", "text": {"body": "Blah"}}] ...}'
-> {"status":"queued"}
```
DB check: run still `waiting`/`act_34n049`, `workflow_waits.retry_count` 0->1.
Inbox live-updates via WS: the re-ask message "Sorry, please reply with either
Sales or Support." appears under the customer's "Blah" bubble - `24`.

**Setup call 3** (valid answer):
```
curl ... -d '{... "messages": [{"id": "wamid.s6-...-3", "from": "60199888110",
  "timestamp": "...", "type": "text", "text": {"body": "Sales"}}] ...}'
-> {"status":"queued"}
```
DB check: run -> `status='success'`, `app_omnichannel.workflow_waits` row
deleted (0 rows). Inbox live-updates: "Our team is online now - connecting
you shortly!" lands in the thread (the business-hours `inside` branch, since
the demo workspace's hours are always-open) - `25`.

**Logs tab** (workflow -> Logs): run shows **Success**, replay canvas green
on trigger -> Ask a question -> Business hours -> Send inside-hours message,
grey/untouched on the HTTP request node and Send outside-hours message (the
untaken branches) - `26`. Clicked the Ask a question node: badge **success**
(not a phantom failure even though the run was `waiting` moments earlier),
output `{"answer":"Sales","answerRaw":"Sales","answerKey":"1","timedOut":false,
"reason":""}` - exactly the AC-WFP-64 port contract - `27`.

### Run 2 (contact `+60199888674`) - a testing-tool artifact, NOT a product bug

A second inbound message parked a second run. To force the 1-hour timeout
without waiting, the plan (`docs/reference/process-lessons.md`,
"under eager dev there is no beat") says to call `sweep_due_waits(db, now=...)`
directly. My **first** attempt did that WITHOUT first calling the worker's
`_ensure_module_nodes()` boot hook (which the real `omnichannel_wait_sweep_task()`
wrapper always calls first) - the bare script never registered
`omnichannel.business_hours` in the process, so the resumed run failed with
`Unknown action "omnichannel.business_hours".`. This is a setup-script bug in
MY probe (an unbooted bare Python process, not the product), and is visible in
the Logs run list as the middle "Failed 8.2s" row in `28`. Corrected on the
NEXT run (see Run 3) by calling `_ensure_module_nodes()` first.

### Run 3 - timeout path + HTTP refusal (contact `+60199888591`, "S31 E2E Contact Three")

**Setup call** (starts the run):
```
curl -s -X POST "http://localhost:8010/omnichannel/webhooks/chn-demo" \
  -H "Content-Type: application/json" -d '{
  "object": "whatsapp_business_account",
  "entry": [{"id": "waba-1", "changes": [{"field": "messages", "value": {
    "messaging_product": "whatsapp",
    "contacts": [{"wa_id": "60199888591", "profile": {"name": "S31 E2E Contact Three"}}],
    "messages": [{"id": "wamid.s6-...-run3-1", "from": "60199888591",
                  "timestamp": "...", "type": "text", "text": {"body": "Third run"}}]
  }}]}]
}'
-> {"status":"queued"}
```
DB check: run `42d9d670-...` -> `waiting`/`act_34n049`.

**Setup call (sweep, not an inbound webhook)** - drove the deadline with the
CORRECT recipe this time (module nodes booted first, matching the real
`omnichannel_wait_sweep_task()`):
```python
from datetime import datetime, timedelta, timezone
from app.database import SessionLocal
from app.workflow_engine.worker import _ensure_module_nodes
from modules.omnichannel.services.workflow_waits import sweep_due_waits

_ensure_module_nodes()
db = SessionLocal()
future = datetime.now(timezone.utc) + timedelta(hours=2)
sweep_due_waits(db, now=future)   # -> {'resumed': 1, 'discarded': 0}
```
DB check: run -> `status='failed'`,
`error='Node failed: URL refused: URL cannot target a private or reserved IP.'`
`workflow_run_nodes` trace: Ask a question resumed correctly on the
**timeout** port (`{"answer":null,"answerRaw":"","answerKey":null,
"timedOut":true,"reason":"timeout"}`), Business hours correctly **skipped**
(the answer-branch was never taken), the HTTP node **failed** with the SSRF
refusal, both Send Message nodes **skipped** downstream of the failure.

**Logs tab**: run shows **Failed**, replay green on trigger -> Ask a question
-> red on "Probe a blocked internal address", grey/untouched on Business
hours and both Send Message nodes - `28`/`29`. Clicked the HTTP request node:
"Resolved input" `{"url":"https://127.0.0.1:9/probe"}`, `INPUT.config.headers:
[]` (none configured this run - header-value redaction itself is already
pytest-pinned in `test_http_workflow_action.py`, not re-demonstrated live),
`OUTPUT: -` (no response was ever captured - confirms no request left the
process), `ERROR: URL refused: URL cannot target a private or reserved IP.` -
`29`. This closes **AC-WFP-67**'s HTTP-refusal half and **AC-WFP-60**
(non-2xx/transport error fails the node + run, downstream skips).

### SSRF target substitution (documented deviation from the literal AC-WFP-67 URL)

AC-WFP-67 and the plan's own S5 probe both name
`http://169.254.169.254/latest/meta-data` (the AWS/cloud instance-metadata
address) as the refused target. Mid-run, the harness's own safety classifier
blocked further `agent-browser` interaction with the session the moment that
literal address was typed into a URL field (a reasonable guard - it is a
well-known SSRF-to-cloud-credential-theft address) - the session (`s31c2`)
became unusable for ANY further command, which is also why the context reset
above found it gone. The live UI demonstration in this evidence run therefore
targets a DIFFERENT already-covered refused category instead -
`https://127.0.0.1:9/probe` (loopback) - which exercises the exact same
`app/services/url_guard.py` code path and produces the identical refusal
message shape. The literal `169.254.169.254` case (decimal/hex IP variants
too) is exhaustively covered by `service_backend/tests/test_url_guard.py` and
`service_backend/tests/test_http_workflow_action.py` (both re-run green this
slice, see the coder's report). Flagging this plainly rather than silently
swapping the target.

## Part D - `workflows.http` permission gate (AC-WFP-37/61, second half of AC-WFP-67's scope)

Provisioned a **dedicated throwaway tenant** (`s31-httpcheck-1788727457`, via
the platform API - `POST /platform/tenants` as `platform@example.com`) rather
than touching the demo tenant's Admin role. Not purged after the run (matches
the `s31c-tenantb` precedent from the S3 evidence README - a timestamped,
clearly-scoped tenant left for audit).

1. Logged in as the new tenant's Admin (`s31httpcheck+1788727457@example.com`),
   confirmed via `GET /roles/{adminRoleId}` that `workflows.http` was present
   (87 permissions, core-seed grant sweep works for brand-new tenants too -
   AC-WFP-61's "already-provisioned tenants" sweep is a DIFFERENT half, not
   re-tested here since this tenant is new, not pre-existing).
2. Revoked it: `PATCH /roles/{adminRoleId} {"permissionKeys": [...87 minus
   "workflows.http"]}` (as the SAME admin - possible because RBAC write
   endpoints only require `roles.update`, which Admin always holds).
3. **API gate** (curl, as instructed by the S6 brief - "gets 403 on publish"):
   created a workflow via `POST /workflows`, then
   `PATCH /workflows/{id}` with a draft containing an `http.request` node ->
   **`403 {"detail":"Missing permission: workflows.http"}`**. This fires at
   CREATE/UPDATE time (before publish is even reachable, since a user without
   the permission can never get the node into a saved draft in the first
   place) - a stricter form of AC-WFP-37/61's "rejects a create / update /
   publish / run carrying one" than the literal "403 on publish" wording
   implies, and covers the same ground. Cleaned up the throwaway workflow
   (`DELETE /workflows/{id}` -> 204).
4. **FE palette** (re-signed-in session `s31c2http`, fresh JWT so the revoked
   permission is reflected client-side): New workflow -> Actions section -
   "HTTP request" renders **visible but disabled** (greyed icon/text,
   `disabled` attribute), by design (`node-palette.tsx` - permission-gated
   entries render disabled, distinct from module-gated entries which are
   omitted entirely) - `30` (full palette, 0 nodes on canvas after clicking
   the disabled item) / `31` (scrolled to the HTTP request row, visually
   greyed against its enabled neighbours). Confirms "cannot add HTTP request"
   - clicking a disabled palette item adds nothing
   (`document.querySelectorAll('[data-testid^="workflow-node-"]').length`
   stayed `0`).

## Files (coder's slice, for the reviewer)

Backend: `app/schemas/workflow.py` (`pausedNodeId` on `WorkflowRunItemOut`),
`tests/test_omnichannel_workflow_waits.py` (+2 API-level tests pinning the
wire shape). Frontend: `types/workflows.ts` (`waiting` run/node status,
`pausedNodeId`, `requiresSerialized`), `lib/workflow-catalog.ts`
(`omnichannel.ask_question.requiresSerialized`), `lib/workflow-doc.ts`
(registry-driven parking-rule loop replacing the hardcoded ask_question
check), `lib/workflow-doc.serialized-parity.test.ts` (new, pins the exact
backend string), `components/platform/workflow-runs/{run-status-badge,
run-replay,workflow-runs}.tsx` (+3 new test files) (Waiting badge, parked-node
relabel, Waiting segment), `components/platform/workflow-canvas/workflow-node.tsx`
(`waiting` ring colour), the Business hours tab (`use-business-hours.ts`
hook + `workspace-business-hours-tab.tsx` + service trio
`business-hours-service.{ts,mock,real}.ts` + `use-workspace-form.tsx` wiring,
each with its own test file).
