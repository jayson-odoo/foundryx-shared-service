# Plan 31 (omnichannel workflow parity) - S3 evidence run

Recorded with `agent-browser` (session `s31c`, + a throwaway `s31c-tenantb` session
for the tenant-isolation check), real clicks against the live s31 lane
(backend `:8010` on `foundryx_service_s31`, frontend `:3009`, prod build). Signed
in as `demo@example.com` (default tenant Admin). Every workflow name is
timestamped (`S31 E2E A5a 20260906-214340`, `S31 E2E once-per-contact
20260906-214340`) per the evidence-run convention.

Covers **AC-WFP-36 .. AC-WFP-40**.

## Environment note (found + fixed during this run)

The lane's `.env` (symlinked from the main checkout, shared across worktrees)
only lists CORS origins for ports 3000-3005 (`CORS_ORIGINS=http://localhost:3001,
http://localhost:3002`). Lane s31 runs the frontend on **3009**, so every
`OPTIONS` preflight from the browser 400'd and the frontend silently rendered
with **zero live tenant data** (0 omnichannel triggers/actions in the palette,
even though the module was ACTIVE for the tenant) - not a plan-31 bug, a lane
port outside the shared `.env`'s hardcoded CORS list. Fixed by restarting
uvicorn (PID replaced 27653 -> 36836) with an env-var override on the command
line (never edited the shared `.env` file):
```
CORS_ORIGINS="http://localhost:3001,http://localhost:3002,http://localhost:3009"
CORS_ORIGIN_REGEX='http://[a-z0-9-]+\.localhost:(3001|3002|3009)'
```
Screenshots `01`-`02` are pre-fix (0 triggers visible); from `03` onward the
palette shows the full omnichannel catalog (18 triggers / 24 actions).

## agent-browser interaction notes (for the next coder on this lane)

- Several sidebar/canvas buttons in this build use motion wrappers that a
  plain `agent-browser click <ref>` does not register on (per
  `docs/reference/process-lessons.md`). Worked around throughout via
  `agent-browser eval --stdin` dispatching a real `pointerdown->mousedown->
  pointerup->mouseup->click` sequence at the element's computed center.
- **React Flow (`@xyflow/react` 12.11) connection-drag handles listen for
  native `mousedown`/`mousemove`/`mouseup` on `document`, NOT `pointerdown`/
  `pointermove`/`pointerup`** - confirmed by inspecting the mounted
  `<Handle>` React props (`onMouseDown`) and the `@xyflow/system` source
  (`doc.addEventListener('mousemove', onPointerMove)`). `agent-browser mouse
  move/down/up` (CDP-level) did not register at all on this canvas (verified
  via a temporary event-listener probe - zero events reached the handle).
  The reliable recipe: dispatch a `MouseEvent('mousedown')` on the SOURCE
  handle, several `MouseEvent('mousemove')` on `document` stepping toward the
  target, then `MouseEvent('mouseup')` on `document` at the target handle's
  center - confirmed by `document.querySelectorAll('.react-flow__edge').length`
  going from 0 to 1 per drag.
- A canvas node positioned partially behind the (always-open) drawer panel
  is **not clickable at its computed-center coordinate** even though
  `getBoundingClientRect` reports a position - the "center" can fall behind
  the drawer. Fix: collapse the sidebar (`aria-label="Collapse sidebar"`) +
  Tidy + Fit View before computing handle/node coordinates, so every node is
  inside the actual `[data-testid="flow-canvas"]` bounds.
- The conversation drawer's "Close" button sits past the 1280px right edge
  (a `[data-testid]`-free header row) - reachable by `textContent==='Close'`
  element lookup even when visually clipped, but `screenshot` won't show it
  without scrolling; do not confuse it with the "Close toast" dismiss button
  on a stale notification.

## Flow recorded (AC-WFP-39)

1. **Sign in** (`/` -> fill Email/Password -> Sign In) - screenshot `01`.
2. **Sidebar Home -> Workflows -> Workflows** (expand section, click the
   nested "Workflows" link) -> empty list (pre-CORS-fix) - `02`.
3. **New workflow** -> Settings tab, name filled -> Editor tab, Triggers
   section expanded, click **Conversation opened** -> node added, drawer
   shows Workspace/Channel/"Only on reopen"/"Trigger once per contact" -
   `03` (18 triggers now visible, proving the CORS fix).
4. Actions section: **Add tag**, **Update lifecycle**, **Send Message**
   added in sequence (click-to-add, unwired per the no-auto-connect rule) -
   `04`.
5. Tidy + Fit View (sidebar collapsed for room) -> all 4 nodes visible -
   dragged Conversation opened -> Add tag -> Update lifecycle -> Send
   Message (3 handle-to-handle drags) - `05`.
6. Configured each node (Contact = `{{ trigger.contact.id }}` merge field
   throughout, Workspace = General):
   - **Add tag**: Tag = `closed-1788684915` (the workspace's only
     pre-existing tag on this lane DB) - `06`.
   - **Update lifecycle**: Move to stage = "Customer" - `07`.
   - **Send Message**: Message type = Approved template, Template =
     `booking_update` (APPROVED; `promo_blast` PENDING correctly excluded
     from the picker per AC-WFP-31's approved-only foolproof filter) - `08`.
7. **Save workflow** (Settings tab name re-filled after an incidental
   mid-session reload wiped the unsaved field - see note below) -> **Publish**
   -> **Edit -> Settings -> Active toggle** -> "Workflow activated." - `09`,
   `10`.
8. **Second workflow** ("once-per-contact"): Trigger = **Conversation
   closed** + **Trigger once per contact** checked; Action = **Add comment**
   (`{{ trigger.contact.id }}` / "Once-per-contact automation fired (S31
   E2E).") wired trigger -> comment - `11`. Saved, Published, Activated -
   `12`, `13`.
9. **Inbox** (sidebar Omnichannel -> Inbox) - 5 demo contacts, all seeded by
   `seed_demo_conversations` - `14`. Opened **Sarah Chen** (cnt-001) - `15`.
10. **Close conversation** (reason "General Inquiry") -> "Conversation
    closed." toast; the once-per-contact workflow's Add comment note
    appears inline ("Once-per-contact automation fired (S31 E2E).") - `16`.
11. **Reopen** -> Sarah's lifecycle pill flips to "Customer" in the list row
    -> `17`. Backend confirms `omnichannel.conversation_opened` fired,
    `add_tag`/`update_lifecycle` both `success`, but `send_message` FAILED
    (`This template's body needs 2 variable(s); 0 provided`) - a genuine
    config gap (I never filled Template variables), NOT a plan-31 bug;
    **and it demonstrates AC-WFP-32 exactly as specified**: the two
    committed steps (tag, lifecycle) were NOT rolled back by the later
    node's failure.
12. **Fixed the config** (Editor -> Send Message node -> Template variables
    -> Add row x2 -> `1` = `{{ trigger.contact.name }}`, `2` = literal text)
    -> Save -> Publish changes - `18`.
13. Re-tested on a **completely clean contact** (Marcus Wong, cnt-002, never
    touched by any prior test workflow on this lane) to get an
    unambiguous, fully-green demonstration: Close -> once-per-contact fires
    (Add comment) -> Reopen -> A5a fires end-to-end, **all 4 nodes
    succeed**, the Send Message step actually delivers a merge-rendered
    template ("Hi Marcus Wong, there is an update on your booking: the
    Update lifecycle stage was moved to Customer...") - `19`. Verified via
    DB: both runs `status=success`, zero errors, tag+stage applied,
    `messageId`+`status=SENT` on the send.
14. **Logs tab** (Workflows -> the A5a workflow -> Logs) - the 3 runs listed
    (2 failed from the config-gap iteration, 1 success) - `20`. Clicked the
    **trigger node** -> inspector shows **"Conversation opened"** (the
    node's real name) with a **"Trigger data"** panel (not "Output" - the
    S3 label change) carrying the full captured event
    (`triggeredBy`/`actor`/`action`/`contact.{id,name,phone}`/
    `conversationId`/`workspaceId`/`isReopen`/`channelId`) - `21` (AC-WFP-38).
    Clicked **Add tag** -> "Resolved input" (merge-rendered `contactId:
    "cnt-002"`), raw "Input" (the config + `resolved` map), and "Output"
    (`tags`, `changed`) all render - `22`.
15. **Responsive** - same Logs surface at 375px (`23`), the read-only Editor
    at 375px (palette hidden, canvas full-width, no clipping) (`24`), and
    the Inbox list at 375px showing both contacts' new "Customer" pill +
    the applied tag, non-clipped (`25`).

## Tenant isolation (AC-WFP-40, second half)

Provisioned a **dedicated tenant** (`s31-tenantb-<epoch>`, operator API -
setup only, per the dedicated-tenant-for-shared-state-mutation rule) and
installed omnichannel for it, then signed in as its admin in a SEPARATE
`agent-browser` session (`s31c-tenantb`):

- `/workflows` -> "No data available" (0 rows) - `26`.
- New workflow -> Manual trigger -> `workflow.trigger` action -> the
  Workflow picker's dropdown returns **`[]`** (`role="option"` count = 0) ->
  UI renders "No matches." - `27`. Tenant B's own 18 triggers / 24 actions
  ARE visible (module correctly ACTIVE for tenant B too) - only the
  workflow-scoped picker data is empty, confirming the isolation is at the
  DATA layer (tenant-scoped query), not a module-visibility accident.
- Closed the `s31c-tenantb` session only (never `close --all`).

## AC-WFP-36..40 - PASS / FAIL

| AC | Result | Evidence |
|---|---|---|
| AC-WFP-36 (mock swapped to real, no mock left) | **PASS** | `services/workflow-metadata-service.mock.ts` deleted; `workflow-metadata-service.ts` now a 1-line passthrough to `.real`; `grep -rn "S0 MOCK"` = empty; screenshots `03`-`22` all show live tenant data (real workspace "General", real tags/stages/templates, real workflows in the picker) |
| AC-WFP-37 (permission gating - editor read-only without `workflows.manage`; HTTP node hidden without `workflows.http`) | **PASS** (mechanism), gate itself **not independently re-verified live this slice** | The `workflows.manage`-gated read-only editor is the PRE-EXISTING Resource-shell mechanism ("as today" per the AC wording) - unchanged this slice. `workflows.http` gating is NEW this slice: generalized the previously Code-only hardcoded `canCode` check in `node-palette.tsx`/`node-config-drawer.tsx`/`workflow-canvas.tsx` into `lib/workflow-catalog.ts`'s `isPermissionDenied`/`deniedNodePermissions` helpers, threaded `canHttp` through `workflow-editor-tab.tsx` -> `use-workflow-form.tsx` -> `use-workflow-actions.tsx` -> `workflow-form-view.tsx`, and extended `lib/workflow-validation.ts workflowPublishIssue` with the parallel HTTP-node publish/run message. Since `http.request` has no backend ActionDef until S5 (A5b), `can('workflows.http')` resolves false for every tenant today (permission key doesn't exist in the CSV yet) - fails CLOSED correctly, matching foolproof-UI. Covered by new vitest (`node-palette.test.tsx` 2 new cases, `workflow-validation.test.ts` 1 new case) - not separately live-clicked since there is no live HTTP node to click yet |
| AC-WFP-38 (Logs shows trigger's captured event + resolved input/output/error) | **PASS** | Backend: `_execute_node`'s trigger branch generalized from a single hardcoded `message.*` block to a registry-driven walk of every `trigger.<dotted>` context key (excluding `trigger.record.*`, the separate rule-fact namespace, and `trigger.input.*`, the pre-existing flat manual-trigger shape) - pytest `test_conversation_opened_trigger_node_captures_event_data_in_logs` + `test_workflow_trigger_child_run_trigger_node_captures_chain_context` (24 total in the parity file, +2 new). Frontend: `run-replay.tsx` labels the trigger's block "Trigger data" (not "Output") and hides the irrelevant Input/Resolved-input blocks for a trigger node - vitest `run-replay.trigger-data.test.tsx` (2 new). Live: `21`, `22` |
| AC-WFP-39 (E2E: build + wire + publish + close/reopen + Logs shows tag+stage applied) | **PASS** | `03`-`22` (full build); DB-confirmed clean run on Marcus Wong: `add_tag` -> `{"tags": ["9eec73de-2909-457b-a3b0-339712dbd585"], "changed": false}` (already-applied no-op, AC-WFP-25), `update_lifecycle` -> `{"fromStageId": "...New Lead...", "toStageId": "...", "stageLabel": "🤩 Customer"}`, `send_message` -> `{"messageId": "...", "status": "SENT"}`; contact panel + inbox row both show the "Customer" lifecycle pill live (`19`, `25`) |
| AC-WFP-40 (once-per-contact fires once across reopen+close; tenant B sees nothing) | **PASS** | Once-per-contact workflow ran exactly once for Sarah Chen (cnt-001) across TWO separate close events (DB: 1 row in `workflow_runs` for that workflow+contact, confirmed by direct query) - `16` (first fire) vs the second close producing no second internal note. Tenant isolation: `26`, `27` |

## Test counts (this slice)

- Backend targeted pytest (not the full suite - machine is memory-constrained,
  cap 3 concurrent full suites per lane rules): `tests/
  test_omnichannel_workflow_parity_triggers.py` 24 passed (was 22, +2 new),
  `tests/test_workflow_test_trigger_data.py` 18 passed (pinned trigger-output
  shape unaffected by the generalization), `tests/test_workflow_engine.py` +
  `tests/test_workflow_triggers.py` + `tests/test_omnichannel_workflow_triggers.py`
  + `tests/test_serialized_workflow_runtime.py` + `tests/test_stateful_ai_runtime.py`
  + `tests/test_agent_state_read_node.py` + `tests/test_code_workflow_action.py`
  + `tests/test_redis_workflow_action.py` = 151 passed together (regression
  net for the executor's trigger-output change - genuinely load-bearing,
  confirmed green).
- Frontend: full `npx vitest run` = **2164 passed, 1 pre-existing flaky
  failure** (`inbox-view-rail.test.tsx`, a timer-based deferred-action test
  unrelated to plan 31 - confirmed passing in isolation, not a regression;
  same file/test existed before this slice's changes). New/changed test
  files: `lib/workflow-catalog.omnichannel-parity.test.ts` (+3 self-trigger
  parity cases), `components/platform/workflow-canvas/
  node-config-drawer.omnichannel-parity.test.tsx` (+1 self-exclusion case),
  `components/platform/workflow-canvas/node-palette.test.tsx` (+2 HTTP-gate
  cases), `lib/workflow-validation.test.ts` (+1 HTTP-gate case),
  `components/platform/workflow-runs/run-replay.trigger-data.test.tsx` (new
  file, 2 cases).
- `npx eslint` on every touched file: 0 errors (pre-existing 2 warnings in
  `workflow-canvas.tsx` at an unrelated line, unchanged by this slice).
  **Correction (review round 1, SF-8):** the "64 pre-existing, zero new"
  claim above was wrong - `npx tsc --noEmit` at the reviewed commit
  (`0db05830`) actually carried 50 errors, 2 of them NEW in files this slice
  added (`node-config-drawer.omnichannel-parity.test.tsx`,
  `workflow-node.ports.test.tsx` - both untyped test-fixture gaps). Both were
  fixed in the review-1 fix pass (properly typed fixtures, no `any`); `npx
  tsc --noEmit` now reports 48 errors, all pre-existing, none in a file this
  branch touches.

## Deferred / residue notes

- This lane's Postgres DB (`foundryx_service_s31`) carries residue from
  earlier S1/S2 coder sessions on this same branch: workflows named "S1
  probe conv closed once v2" and "S2 probe - closed tag field template"
  (both still Published+Active), plus a pre-existing contact tag
  `closed-1788684915` and a `probeField1788684915` custom field on
  `cnt-001`. These interfered with the FIRST attempt on Sarah Chen (extra
  "TEMPLATE" bubbles from the unrelated probe workflows, and a stale
  "Customer" lifecycle blocking a same-stage re-transition on the second
  close). Not a plan-31 defect - re-ran cleanly on a never-touched contact
  (Marcus Wong) for the definitive evidence. Left the probe workflows
  in place (not this slice's residue to clean up; a later slice/reviewer
  may want to archive them before the branch merges).
- `workflows.http`'s CSV row + tenant-admin grant sweep land in S5 (A5b) -
  today `can('workflows.http')` is false for every tenant (permission key
  doesn't exist yet), which is the correct fail-closed default, not a gap.
