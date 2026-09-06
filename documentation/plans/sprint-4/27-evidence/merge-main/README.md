# Merge-main smoke evidence (plan 27, sprint-4)

Merge of `origin/main` (`d302ea7` = plan 23 design-language restyle PR #41 +
plan 25/A1 contact data model PR #42) into `sprint-4/27-inbox-views-events`
(A3, S1 HEAD `58b410a`). Merge commit `b277484`. Smoke run via `agent-browser
--session s27` against the merged + rebuilt code, backend :8006 / frontend
:3005, tenant `default`, user `demo@example.com`.

Login: real sidebar clicks from `/` throughout. Two navigation-only actions
used a native DOM `.click()`/pointer-event dispatch via `agent-browser eval`
instead of `agent-browser click <ref>` - the CDP-level click intermittently
failed `DOM.getBoxModel` on elements inside the plan-23 spring/motion
transition wrappers (a harness quirk noted before in this repo's history,
not a product bug); the native click still fires on the real rendered
element found by text/testid, so real-click discipline is preserved.

## Steps + screenshots

1. **01-inbox-1280.png** - Sidebar Omnichannel > Inbox at 1280px. View rail
   (All/Mine/Unassigned + Lifecycle stages + Views) in its own column, filter
   bar (Show/Sort/Priority/Unreplied) above the thread list, lifecycle +
   tag chips on each row. Confirms S0's rail/filter-bar restyle survived the
   merge with plan 23's spring/tabs/toast guardrails applied.
2. **02-thread-open-1280.png** - Clicked the Sarah Chen thread row
   (`[data-testid="thread-row-cnt-001"]`). Conversation drawer opens with
   real seeded messages, Messages/Activities tabs, header actions (priority/
   status/assignee/snooze/close).
3. **03-activities-feed-1280.png** - Clicked the Activities tab. Feed shows
   REAL backend-driven conversation events ("Conversation opened",
   "Demo User assigned to Demo User") - confirms S1's conversation-events
   table/writers/read route are live post-merge, not a mock.
4. **04-close-dialog-1280.png** - Clicked Close in the drawer header. Close
   conversation dialog opens (Reason SearchSelect + Note + Cancel/"Close
   conversation" button - verb+noun label per plan 23's guardrail).
5. **05-close-reason-options-1280.png** - Opened the Reason picker: General
   Inquiry / Sales Inquiry / Payment Issue / Others (mock close-reasons
   service, searchable per the design mandate).
6. **06-workspace-detail-tabs-1280.png** - Settings > Workspaces > General.
   All 8 tabs present: Settings, Channels, Members, Lifecycle, Contact
   fields, Tags, Close reasons, API Keys - confirms the auto-merged
   `use-workspace-form.tsx` kept every tab from A1 (plan 25) + S0 (plan 27)
   + main (plan 23 alignment).
7. **07-close-reasons-tab-1280.png** - Close reasons tab: embedded Resource
   list with 4 seeded reasons (Others/Payment Issue/Sales Inquiry/General
   Inquiry), sort order, Active status, usage counts.
8. **08-workspace-close-reasons-375.png** - Same tab at 375px: tab strip
   scrolls horizontally, list table scrolls horizontally, no clipping.
9. **09-inbox-375-list.png** - Inbox at 375px: single-pane list view, rail
   collapsed into an "All" SearchSelect (D-A3-15), filter bar stacked above
   search.
10. **10-inbox-375-thread.png** - Tapped a thread row at 375px: single-pane
    conversation view with a "Conversations" back control, Messages/
    Activities tabs, composer - all reflow correctly, no clipping.

## Findings

- **Shortcuts control** (`components/platform/conversation-drawer/
  shortcut-menu.tsx`) renders nothing for the demo Admin - by design
  (foolproof-UI: it gates on `can('conversations.shortcut')`, and that
  permission key was never added to
  `service_backend/modules/omnichannel/permissions/permissions.csv` in S0
  (`d86f5cb`, pre-merge; confirmed via `git show 58b410a:...permissions.csv`
  - the row is absent both before and after the merge). Not a merge
  regression; flagged for whichever slice wires the real Shortcuts backend
  (the CSV row + a grant sweep for existing tenants will be needed then).
- Two post-merge alignment fixes were required for main's plan-23 guardrail
  tests (documented in the merge commit + the follow-up
  `fix(omnichannel): plan 27 post-merge alignment...` commit):
  `components/ui/tabs.inventory.test.ts` KEEPERS list (thread-list.tsx's
  Tabs were removed by S0, superseded by the view rail); six files' direct
  `sonner` imports swapped to `@/lib/toast`; two `useForm()` calls gained
  `mode: 'onTouched'`; `inbox-view-rail.tsx`'s three raw buttons gained
  `PRESSED_CLASS`.

## Suite counts (post-merge + post-alignment)

- Backend: `2861 passed, 1 skipped, 18 deselected, 0 failed` (>= expected
  baseline of main's ~2803 + S1's additions).
- Frontend: `265 files / 2022 tests passed, 0 failed` (main baseline 1980 +
  S0's 43, minus 1 `it.each` case removed from the tabs KEEPERS list =
  net 2022).
- `npx eslint .`: 0 errors, 210 warnings (pre-existing, unchanged in kind).
- `npx tsc --noEmit`: pre-existing noise only (autocount/ideation/products/
  badge/data-grid test-tooling errors unrelated to `--downlevelIteration`/
  top-level-await test config quirks); zero new errors touching any merged
  or modified file.
- `rm -rf .next && npm run build`: clean.
