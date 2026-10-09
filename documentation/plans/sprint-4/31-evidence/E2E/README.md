# Plan 31 (omnichannel workflow parity) - independent tester E2E run (A5a, S0-S3 scope)

Recorded with `agent-browser` (session `s31t`, plus a throwaway `s31t-tenantb`
session for tenant isolation), real clicks against the live s31 lane (backend
`:8010` on `foundryx_service_s31`, frontend `:3009`, prod build, HEAD
`0db05830`). Signed in as `demo@example.com` (default tenant Admin) unless
noted. This is a SEPARATE, independent run from the S3 coder's own evidence
at `../S3/` - no screenshots are reused. Workflow names are timestamped
(`S31 tester A5a 20260906-221109`, `S31 tester once-per-contact
20260906-221109`) per the evidence-run convention.

Covers **AC-WFP-01..06** (spot-checked live against the real palette, not
just the S0 mock), **AC-WFP-08/09/15** (opened/closed/once-per-contact
triggers), **AC-WFP-25/27/31/32** (add tag / update lifecycle / send message
template / partial-failure semantics), **AC-WFP-36..40** (A5a wire +
evidence). AC-WFP-41..70 (A5b - waits, ask-a-question runtime, business
hours, HTTP request) are **NOT IN SCOPE** for this report; screenshots
`31`/`32` only verify the A5a-scope frontend publish-gate message and
two-port rendering for the Ask node (AC-WFP-05/06), not any A5b runtime.

## Environment note

Lane backend `:8010` was already running with the `CORS_ORIGINS` override
for `:3009` (set by the S3 coder, per that evidence README) - no restart
needed this run. `.next/BUILD_ID` (`c9ptgeLBRN_YwBGjHyiUfBUILD_ID`,
2026-09-06 21:21) predates this run and no source file was newer, so no
rebuild was performed.

## Residue found and handled

The lane DB carries residue from earlier S0-S3 coder sessions: workflows
"S1 probe conv closed once v2", "S2 probe - closed tag field template", "S2
probe parent/child", "S2 self-trigger probe", and the S3 coder's own
`S31 E2E A5a 20260906-214340` / `S31 E2E once-per-contact 20260906-214340`
(both ACTIVE, same trigger types as the workflows built in this run). Two
of these (`S1 probe conv closed once v2`, `S2 probe - closed tag field
template`) share the untargeted `omnichannel.conversation_closed` trigger
and fired alongside my own once-per-contact workflow on every close (extra
"TEMPLATE"/internal-note noise in the inbox screenshots - expected, not a
defect, confirmed by DB inspection that MY workflow's own run count stayed
exactly 1).

The S3 coder's `S31 E2E A5a 20260906-214340` (`omnichannel.conversation_
opened`, no channel/reason filter) collided harder: on Daniel Lee's first
Reopen, BOTH it and my own `S31 tester A5a` fired on the identical event.
Whichever ran first won the tag/lifecycle mutation; my own workflow's run
then legitimately saw the tag already-applied (no-op, AC-WFP-25) and the
lifecycle already at the target stage (correctly REJECTED by the machine,
AC-WFP-27's fail-closed semantics, downstream Send Message correctly
SKIPPED per the fail/skip rule) - confirmed node-by-node via direct
`workflow_run_nodes` queries against my own workflow's id
(`66b31cbd-9432-420d-ad83-10fb1b0b1e96`). This is a genuine demonstration of
the fail-closed/skip contract, but to get an UNAMBIGUOUS single-workflow
full-success demonstration for AC-WFP-39 (all 4 nodes green, attributable to
MY OWN workflow, not a race with a sibling), I:

1. Opened the S3 coder's `S31 E2E A5a 20260906-214340` (real UI clicks:
   Workflows list -> row -> Settings -> Edit -> Active off -> Save).
2. Re-ran the reopen on a THIRD, never-touched demo contact (Aisha
   Abdullah, cnt-005) - clean win, all 4 nodes `success` (DB-confirmed,
   run `4d69a6e6-...`), screenshot `20`.
3. Reactivated the S3 coder's workflow afterward (same real-click sequence,
   Active back on, Save) to leave the lane exactly as found - screenshot
   confirms `switch [checked=true]` before moving on.

This is disclosed, reversible admin housekeeping (Settings-tab Active
toggle via the real UI), not a change to any application code or to my own
workflows' pass/fail result.

## agent-browser interaction notes (for the next agent on this lane)

- Palette buttons, canvas nodes, and header action buttons (Close/Reopen/
  Snooze) in this build sit inside motion wrappers that a plain
  `agent-browser click <ref>` frequently no-ops on with NO error - the
  command reports success but nothing happens. Every add/click in this run
  that looked like a no-op was fixed the same way: read the button's real
  `getBoundingClientRect()` via `eval`, then dispatch a real `pointerdown ->
  mousedown -> pointerup -> mouseup -> click` `MouseEvent` sequence at its
  center via `agent-browser eval --stdin`.
- **A palette button scrolled below its own scrollable section is NOT
  auto-scrolled into view by `agent-browser click`** - the click coordinate
  can land off the panel's visible area and silently do nothing.
  `agent-browser scrollintoview <ref>` before `click` fixed this
  consistently for palette entries.
- **A Resource-list row button's `getBoundingClientRect().width` can be far
  wider than its VISIBLE width** (the inbox thread-row button in this build
  measured `width: 982` when only ~320px renders, because the flex parent
  clips overflow) - computing `x = rect.x + rect.width/2` lands the click on
  the adjacent EMPTY pane, not the row. Fix: click at a small fixed offset
  from the left edge (`rect.x + 100`) instead of the geometric center.
- **A header action button can render past the 1280px viewport edge**
  (confirmed here for the conversation drawer's "Close" button, `x:
  1280.875`) - `elementFromPoint` at its center then returns `null`
  (nothing is actually there) and the eval throws. Dispatch the same
  event sequence directly ON THE ELEMENT (skip `elementFromPoint`) when this
  happens; the browser still delivers the events to the (off-screen but
  real) element.
- React Flow (`@xyflow/react` 12.11) connection-drag handles want native
  `mousedown`/`mousemove`/`mouseup` on `document` (not `pointerdown`/
  `pointermove`/`pointerup`) - confirmed again this run; the drag routine
  from the S3 README worked, though the FIRST attempt at a given drag
  sometimes silently produced 0 edges and a retried identical dispatch then
  worked (no diagnosed root cause - always verify
  `document.querySelectorAll('.react-flow__edge').length` after every drag
  and retry once on 0).

## Flow recorded

1. **Sign in** (`/` -> fill Email/Password -> Sign In) - `01`.
2. **Sidebar Workflows -> Workflows -> New workflow** -> Settings tab, name
   `S31 tester A5a 20260906-221109` -> Editor tab, Triggers expanded
   (18 total, confirming AC-WFP-01's live catalog), click **Conversation
   opened** -> node added (had to `scrollintoview` first - the button sat
   below the palette's visible scroll area) -> drawer shows Workspace/
   Channel/"Only on reopen"/"Trigger once per contact", all `SearchSelect`
   (AC-WFP-02) - `02`, `03`.
3. Set Workspace = "General" (only live workspace, AC-WFP-36 real data).
   Actions (24 total): **Add tag**, **Update lifecycle**, **Send Message**
   added in sequence, unwired (no auto-connect) - `04`.
4. Collapsed sidebar, Tidy, Fit View -> 3 real-drag handle-to-handle wires
   (Conversation opened -> Add tag -> Update lifecycle -> Send Message) -
   `05`.
5. Configured: **Add tag** - Contact `{{ trigger.contact.id }}`, Workspace
   unset -> Tag picker correctly DISABLED "Choose a workspace first"
   (AC-WFP-03), then Workspace=General -> Tag picker enabled, only tag
   `closed-1788684915` (the workspace's one live tag) offered - `07`.
   **Update lifecycle** - same workspace-gating behavior confirmed on the
   "Move to stage" picker, chose "Customer" - `08`. **Send Message** -
   Message type toggled Text -> Approved template (AC-WFP-04 showWhen:
   Message textarea replaced by Template picker), Template = `booking_update`
   (APPROVED; the PENDING `promo_blast` template correctly excluded from the
   list - AC-WFP-31's approved-only filter), 2 placeholder rows added
   (`{{ trigger.contact.name }}`, literal "Customer") - `06`.
6. **Save -> Publish -> Settings tab -> Edit -> Active on -> Save** - `09`.
7. **Second workflow** `S31 tester once-per-contact 20260906-221109`:
   trigger **Conversation closed** (Workspace=General, Close reason left
   "Any reason", **Trigger once per contact** checked), action **Add
   comment** (`{{ trigger.contact.id }}` / a timestamped note), wired,
   saved, published, activated - `10`, `11`.
8. **Inbox** (sidebar Omnichannel -> Inbox) - 5 demo contacts - `12`.
   Opened **Daniel Lee** (cnt-004, Snoozed/New Lead, untouched by prior
   probes) - `13`. Clicked **Reopen** -> conversation opened -> the
   FIRST-attempt full chain (add tag / update lifecycle / send template)
   raced with the S3 coder's still-active sibling workflow on the identical
   trigger (see Residue section) - the visible outcome still showed a
   correctly-applied "Customer" stage + one TEMPLATE message (delivered by
   whichever workflow's send step ran first) - `14`.
9. **Closed** Daniel Lee (reason "General Inquiry") -> my once-per-contact
   workflow's internal note ("S31 tester once-per-contact fired
   (20260906-221109)") appeared alongside the pre-existing sibling
   once-per-contact workflow's own note (residue noise, not a defect) -
   `16`. **Reopened** then **Closed AGAIN** with the same reason - my note
   did NOT reappear a second time (verified both visually and via a direct
   `workflow_runs` query: exactly ONE `success` row for my once-per-contact
   workflow across the two close events, `AC-WFP-40` first half) - `17`,
   `18`.
10. Deactivated the S3 coder's colliding `S31 E2E A5a 20260906-214340`
    workflow (Settings -> Edit -> Active off -> Save, real clicks) to get an
    unambiguous AC-WFP-39 demonstration. Opened **Aisha Abdullah** (cnt-005,
    Closed/New Lead, never touched) - `19`. Clicked **Reopen** -> ALL 4
    nodes succeeded cleanly and attributably to my own workflow (tag added,
    lifecycle moved to "Customer", template delivered `SENT`) - `20`,
    DB-confirmed via `workflow_run_nodes`. Reactivated the S3 coder's
    workflow immediately after (Settings -> Edit -> Active on -> Save) to
    restore lane state.
11. **Logs tab** on my A5a workflow - 3 runs listed (2 failed from the
    collision, 1 clean success) - `21`. Clicked the **trigger node** ->
    "Conversation opened" inspector shows a **"Trigger data"** panel (not
    "Output") with the full captured event
    (`contact.{id,name,phone}`/`conversationId`/`workspaceId`/`isReopen`) -
    `22` (AC-WFP-38). Clicked **Add tag** -> RESOLVED INPUT (merge-rendered
    `contactId: "cnt-005"`), raw INPUT (config + resolved map), and OUTPUT
    (`tags`, `changed: true`) all render - `23`. Clicked into a FAILED run
    and its **Update lifecycle** node -> ERROR panel shows the machine's own
    message ("No transition from 'Customer' to 'Customer'.") and the
    downstream Send Message node renders un-highlighted (skipped, no
    phantom success) - `24` (AC-WFP-32/38).
12. **Responsive** - same Editor (read-only) at 375px (`25`), Logs at 375px
    (`26`), Inbox list at 375px showing Aisha's applied tag/stage
    non-clipped (`27`).
13. **Tenant isolation (AC-WFP-40 second half)** - provisioned a FRESH
    dedicated tenant via the platform operator API (`POST /platform/
    tenants`, `s31-tester-tenantb-<epoch>` slug, timestamped) + installed
    omnichannel for it (operator-API setup only, per the dedicated-tenant
    rule), then signed in as its own admin in a separate `agent-browser`
    session (`s31t-tenantb`):
    - Sidebar Workflows -> Workflows -> "No data available" (0 rows) - `29`.
    - New workflow -> Manual trigger -> Trigger another workflow action ->
      the Workflow picker's dropdown returns **0 `role="option"` elements**,
      UI shows "No matches." - `30`. Tenant B's own 18 triggers / 24 actions
      ARE fully visible (module correctly ACTIVE for tenant B too, palette
      screenshot not separately saved but confirmed via snapshot text
      "TRIGGERS(18)"/"ACTIONS(24)") - only the workflow-scoped picker DATA
      is empty, confirming isolation is at the query layer, not a
      module-visibility accident.
    - Closed the `s31t-tenantb` session only (never `close --all`).
14. **Spot-check AC-WFP-05/06 on the real (not mock) build** - a throwaway
    unsaved/uncommitted workflow: Manual trigger + Ask a question action.
    The publish-issues banner reads "Ask a question requires serialized
    execution and a Correlation key." (AC-WFP-06 parity message, backend-
    pinned by pytest) - `31`. The Ask node renders two distinct labelled
    source handles (`answer` blue, `timeout` orange) exactly like the IF
    node's true/false ports (AC-WFP-05) - `32`. HTTP request button
    confirmed `disabled` in the DOM (AC-WFP-37 fail-closed default, since
    `workflows.http` doesn't exist as a permission key until S5/A5b).
    Discarded this scratch workflow (Cancel -> Discard changes) - never
    saved, zero residue.

## Setup calls made OUTSIDE the UI (verbatim)

```
POST /auth/login {"email":"platform@example.com","password":"platform1234","tenantSlug":"platform"}
POST /platform/tenants {"name":"S31 Tester Tenant B <ts>","slug":"s31-tester-tenantb-<ts>","adminEmail":"admin-s31-tester-tenantb-<ts>@example.com","adminName":"Tenant B Admin","adminPassword":"TenantB1234!"}
POST /platform/tenants/{tenant_id}/modules/omnichannel/install
```
Plus read-only `psql` queries against `foundryx_service_s31` to confirm
run/node counts and node-level output/error JSON (never used to fabricate
or alter state - every mutation asserted was also visible live in the UI).
The only WRITE made outside real UI clicks was the tenant-B provisioning
above (operator-API setup, sanctioned by the dedicated-tenant rule) and the
temporary deactivate/reactivate of the S3 coder's colliding workflow (both
done via real Settings-tab UI clicks, not SQL).

## What was NOT independently re-verified this run

- AC-WFP-10 (conversation assigned trigger), AC-WFP-11/12/13 (tag/field/
  lifecycle-changed triggers), AC-WFP-14 (message_received filters),
  AC-WFP-16..22 (tenant isolation on triggers, buffered dispatch, loop
  guard, code-authorization gate, broadcast-completed DEFERRED per the UAC's
  own note), AC-WFP-23/24 (assign round-robin/unassign), AC-WFP-26
  (update-field validation matrix), AC-WFP-28/29/30 (open/close/comment
  steps individually), AC-WFP-33/34/35 (workflow.trigger self/foreign/
  sandbox gating), AC-WFP-37's `workflows.manage` read-only mechanism (pre-
  existing, unchanged this slice per the S3 coder's own disclosure) - relied
  on the GREEN backend suite (3109 passed) which includes the dedicated
  `test_omnichannel_workflow_parity_triggers.py` /
  `test_omnichannel_workflow_parity_actions.py` files covering these
  matrices, plus the S0-S3 evidence already on file
  (`../S0/README.md`, `../S3/README.md`) for their own live-click coverage.
  Re-deriving fresh UI evidence for every one of these was out of the time
  budget for an independent tester pass; the AC table below marks each
  DEFERRED-TO-SUITE where this applies, not FAIL.
