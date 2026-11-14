# S4 smoke evidence (plan 27, sprint-4) - wire to real backend

Coder smoke run for slice **S4** (wire inbox views/close/events/shortcuts to the real
backend :8006, DB `foundryx_service_s27`). Not the formal recorded E2E (that's the
tester's `AC-IVE-49/50` run) - this is the DoD-required live-verify pass before
declaring the slice done. `agent-browser --session s27` against the freshly rebuilt
frontend (:3005) + the already-running backend (:8006), tenant `default`, user
`demo@example.com`.

## Steps + screenshots

1. **01-inbox-1280.png** - Sidebar Omnichannel > Inbox at 1280px, real clicks from `/`.
   Rail (All/Mine/Unassigned + Lifecycle stages + two pre-existing saved views), filter
   bar, thread list with real seeded contacts.
2. Clicked **Mine** -> only Priya Raj (assigned to Demo User) shown; clicked
   **Unassigned** -> Priya Raj drops out, the rest remain. Both server-filtered (no
   client-side `applyInboxViewFilters` proxy involved anymore - it was deleted this
   slice).
3. **02-show-sort-unreplied-1280.png** - Show=Open (Snoozed/Closed drop out),
   Sort=Longest waiting, Unreplied=on (server-computed via `last_agent_message_at`,
   not the old `unreadCount>0` mock proxy) - Marcus Wong then Priya Raj, matching the
   real `unreplied_first`/`longest_waiting` SQL ordering.
4. **03-save-views-1280.png** - Saved a PERSONAL view ("Waiting on me `<ts>`") and a
   SHARED view ("Team Waiting `<ts>`", Shared switch on) over that filter state; each
   selects itself in the rail immediately, `?view=<id>` in the URL. Reloaded the page -
   the shared view + its Show/Sort/Unreplied state restored from the URL param
   (AC-IVE-20).
5. **04-activities-real-1280.png** - Opened Marcus Wong's thread, Activities tab shows
   the REAL `opened` event (`GET /contacts/{id}/events`). Added an internal note -
   appears in the feed as an authored bubble alongside the event line (see Findings -
   a live dedup bug was caught and fixed here).
6. **05-close-dialog-1280.png** - Close dialog: real `close_reasons` list (General
   Inquiry/Sales Inquiry/Payment Issue/Others via `GET /workspaces/{id}/close-reasons`),
   picked "Payment Issue", typed a note, submitted -> `POST /contacts/{id}/close`.
7. **06-closed-row-disappeared-from-open-filter-1280.png** - Back in the list (still
   Show=Open), Marcus Wong's row disappeared with NO manual refresh (AC-IVE-23 - the
   WS `contact.updated` push reconciled the filtered list). Re-selected Show=Closed:
   the row appeared there with the Closed chip.
8. **07-reopened-1280.png** - Reopened from the drawer; Activities feed kept BOTH the
   `closed` (with "Payment Issue" reason) and `reopened` entries; back in the
   Show=Closed list the row disappeared live again (still Open per the real status).
9. **08-shortcuts-control-1280.png** - Published a shortcut workflow via the backend
   API as setup (see "Shortcut workflow setup" below - not a UI build, per the
   fallback the brief allows). Reloaded the drawer -> the **Shortcuts** `SearchSelect`
   appears (`can('conversations.shortcut')` + a non-empty
   `GET /contacts/{id}/shortcuts` list).
10. **09-shortcut-run-toast-1280.png** - Ran it: `POST /contacts/{id}/shortcuts/{workflowId}`
    -> `{runId, status}` -> toast "Shortcut started." with the run id. Verified via
    `GET /workflows/{id}/runs`: one `status:"success"` run, `triggeredBy:"event"`; the
    contact's `countryCode` flipped to `MY` (the action's `{{ trigger.record.id }}`
    correctly resolved to the contact).
11. **10-inbox-thread-375.png** / **11-inbox-list-375.png** - 375px: single-pane
    conversation with a back control, then single-pane list with the collapsed
    **View** `SearchSelect` above the filter bar (D-A3-15) - no horizontal scroll
    (`document.documentElement.scrollWidth === 375`, verified via `eval`).
12. **12-close-reasons-tab-1280.png** through **14-close-reason-created-1280.png** -
    Settings > Workspaces > General > **Close reasons** tab: 4 seeded reasons with real
    `usesCount` (Payment Issue=1 after the close above); created "Refund `<ts>`" (0
    uses) -> Delete offered; "Payment Issue" (used) -> only Edit/Deactivate offered,
    no Delete (foolproof-UI). Deleted the unused "Refund `<ts>`" successfully.
13. **15-workspace-close-reasons-375.png** - Same tab at 375px: tab strip + table both
    scroll horizontally, Create button reachable, no clipping.
14. **Tenant isolation probe** (API, dedicated tenants per the process convention -
    UI mutation tests get a dedicated tenant): provisioned `s27-iso-<ts>` (module
    installed) and `s27-nomod-<ts>` (module NOT installed). From tenant B, every new
    route against tenant A's ids (`close-reasons`, `inbox-views`, `contacts/{id}/events`,
    `contacts/{id}/close`, `contacts/{id}/shortcuts*`, and `?viewId=`) returned a
    uniform **404**. From the no-module tenant, `GET /omnichannel/workspaces` returned
    **403** "Module not installed" - the same `require_module` gate that hides the
    entire Omnichannel sidebar section (no separate close-reasons/inbox-views menu
    item exists to gate - they're tabs inside the already-gated Workspaces page).

## Shortcut workflow setup (API, not UI-built)

Built via the backend API (`POST/PATCH/active/publish /workflows`) rather than the
canvas UI: `entity.shortcut` trigger (`entityType: omnichannel_contact`) -> one
`entity.update` action (`recordId: "{{ trigger.record.id }}"`, sets `countryCode: "my"`).
Rationale: CLAUDE.md already documents that dnd-kit palette drag is not reliably
scriptable and this session hit a harness quirk (below) on every dialog/dropdown/menu
click that would have made a full canvas build very slow; the omnichannel wiring under
test is the shortcut ROUTES + drawer control, not the workflow builder (covered by
plan 27 S3's own pytest + the workflow-engine's existing E2E coverage). Recorded here
per the brief's "if not feasible, via API - record it."

## Findings (fixed this slice)

- **Note WS-echo duplicate (bug caught live, fixed).** `hooks/use-messages.ts addNote`
  appended the HTTP response's note unconditionally; the backend publishes
  `message.created` on the very same commit, so the WS push frequently lands before
  (or racing) the HTTP response resolves and the SYSTEM bubble rendered TWICE - in
  both the Messages tab and the new merged Activities feed. Fixed with the same
  id-dedup `send` already uses (`prev.some((m) => m.id === note.id) ? prev : [...]`).
  Pre-existing bug (plan 05), surfaced by this slice's real backend + WS combination;
  regression test `hooks/use-messages.note-dedup.test.ts` pins it (simulates the WS
  push arriving before the HTTP response resolves).
- **`unreplied=false` override bug (caught in code review, fixed before this run).**
  `conversation-service.real.ts threadQueryString` only sent `unreplied` when truthy,
  so toggling the switch OFF while a saved view with `unreplied:true` was active would
  silently keep the view's value (AC-IVE-17 requires the explicit param to override).
  Now sends an explicit `unreplied=<bool>` whenever `viewId` is set. Covered by
  `services/conversation-service.real.test.ts`.
- **Rail "Manage view" hardcode (caught in code review, fixed before this run).**
  `inbox-view-rail.tsx` compared `view.ownerUserId === 'usr-demo'` (an S0 mock
  convention) instead of the real signed-in user id - now reads
  `useSession().data.user.id`. Covered by `inbox-view-rail.test.tsx`.
- **Shortcut 409 message swallowed (caught in code review, fixed before this run).**
  The Shortcuts control toasted a generic "Could not run the shortcut." on ANY
  failure, including the server's specific 409 "unauthorized Code node" message.
  `useShortcuts.run` now rethrows (matching `lifecycle-move.tsx`'s pattern) so the
  component can show `ApiError.message` directly. Covered by `shortcut-menu.test.tsx`.
- **Mid-run backend fix: 409 `already_closed`.** A concurrent backend fix-round
  (same worktree, different lane) added a 409 `{code:"already_closed", message}` when
  closing an already-closed thread. `close-thread-dialog.tsx`'s error handler now
  reads a structured `{code, message}` detail (same pattern as `lifecycle-move.tsx`),
  not just `fieldErrors` - covered by a new case in `close-thread-dialog.test.tsx`.

## Harness gotchas (not product bugs)

- **CDP `click` on most Metronic dialog/dropdown/tab controls silently no-ops** in
  this session (Radix/shadcn triggers wrapped in the plan-23 spring/motion
  transitions) - `agent-browser click @eN` on a thread row, a tab trigger, a
  `SearchSelect` combobox/option, a dialog submit button, or a row action-menu item
  consistently left the DOM unchanged. The reliable path was a native JS event
  dispatch via `agent-browser eval --stdin`: `pointerdown` -> `mousedown` ->
  `pointerup` -> `mouseup` -> `click`, all `bubbles:true`, targeting the real element
  (found by `data-testid`, `[role=option]`/`[role=menuitem]` text match, or
  `[role=dialog]`-scoped query to avoid matching a same-labeled trigger button behind
  the dialog). A bare `el.click()` worked for plain thread-row buttons but NOT for
  Radix Tabs (which listen on pointer/mouse events, not a synthetic `.click()`).
  Matches the CLAUDE.md-documented "eval native click on plan-23 motion wrappers"
  gotcha; not a regression in this slice's code.
- **`eval --stdin` shares one JS realm across calls in the same session** - a bare
  `const x = ...` on a later call collides with an earlier one ("Identifier already
  declared"). Wrap each script in an IIFE.
- **jsdom `window.history` persists across vitest test cases in the same file** (only
  the React tree is unmounted between tests) - `app/(protected)/omnichannel/inbox/page.test.tsx`
  needed a `beforeEach` resetting `window.history.replaceState(null, '', '/')` or a
  later "below lg" test inherited the previous test's `?thread=` selection.
- **A dropdown-trigger button and a dialog's submit button can share the exact same
  visible text** ("Create close reason") - `Array.from(document.querySelectorAll('button')).find(...)`
  matches the FIRST one in document order (the still-mounted trigger behind the open
  dialog), silently reopening/no-op'ing instead of submitting. Scope the query to
  `document.querySelector('[role="dialog"]')` first.

## Suite counts

- `npx vitest run`: **268 files / 2035 tests passed, 0 failed** (baseline before this
  slice's edits: 267/2033 - net +1 file / +2 tests from the note-dedup regression test
  and the close-thread-dialog 409 case; `inbox-view-rail.test.tsx`,
  `conversation-service.real.test.ts` and `app/.../inbox/page.test.tsx` are new files
  whose counts are folded into the totals above alongside a few now-deleted mock-layer
  tests).
- `npx eslint .`: **0 errors**, 210 warnings (pre-existing, unchanged in kind/count).
- `rm -rf .next && npm run build`: clean.

## Files touched this slice (frontend only - no backend edits)

- Rebound to real: `services/inbox-view-service.ts`, `services/close-reason-service.ts`,
  `services/conversation-service.ts` (dropped the four mock overrides).
- Server-side filtering: `hooks/use-conversations.ts` (removed the client-side
  `applyInboxViewFilters` layer, deleted `lib/inbox-view-filter.ts` + its test),
  `services/conversation-service.real.ts` (`unreplied` override fix).
- Bug fixes: `app/(protected)/omnichannel/inbox/components/inbox-view-rail.tsx` (real
  session user id), `hooks/use-shortcuts.ts` + `components/platform/conversation-drawer/shortcut-menu.tsx`
  (409 message surfacing), `hooks/use-messages.ts` (note WS-echo dedup),
  `components/platform/conversation-drawer/close-thread-dialog.tsx` (409
  `already_closed` structured message).
- New/extended tests: `services/conversation-service.real.test.ts`,
  `app/(protected)/omnichannel/inbox/components/inbox-view-rail.test.tsx`,
  `app/(protected)/omnichannel/inbox/page.test.tsx`, `hooks/use-messages.note-dedup.test.ts`,
  plus new cases in `components/platform/conversation-drawer/shortcut-menu.test.tsx` and
  `close-thread-dialog.test.tsx`.
