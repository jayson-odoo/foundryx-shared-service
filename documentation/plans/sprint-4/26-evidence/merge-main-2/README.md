# Merge evidence - plan 27 A3 (origin/main, PR #43) into plan 26 A2 lane

Branch `sprint-4/26-contacts-module`, worktree `s26` (`:8005`/`:3004`,
`foundryx_service_s26`). Verifies the merge of `origin/main` (`048162b`, plan
27 A3 inbox-views/close-reasons/events/shortcuts) into this lane (plan 26 A2
contacts module) did not regress either side. Real clicks via `agent-browser
--session s26e`, no typed URLs except the two `open` calls that establish the
starting page for each pass (login page, then plain sidebar/link navigation
throughout).

## Runs

1280px pass, then a 375px pass, single continuous session (`s26e`).

### 1280px

- `01-contacts-list-1280.png` - `/omnichannel/contacts` list renders with real
  seeded + prior-session-residue rows (A2's list, toolbar: Filters / Import /
  Export / Columns / Add contact).
- `02-contacts-segment-dropdown-1280.png` - the "View segment" SearchSelect
  opens with "All contacts" (no saved segments yet in this DB - A2's segment
  feature present and functional, just empty).
- `03-contact-detail-conversation-tab-1280.png` - a contact with no message
  history ("CleanProbe") shows the compact `ConversationDrawer` embed with
  "No messages yet." - confirms A2's contact-detail page still mounts A3's
  (restyled) `ConversationDrawer` with the `compact` prop honoured (header/
  Activities/Close hidden in compact mode by design).
- `04-contact-detail-sarah-conversation-1280.png` - the demo seed contact
  (`cnt-001`, Sarah Chen) opened from Contacts shows real message history in
  the compact embed (internal note rendered inline, timestamps, read ticks).
- `05-inbox-1280.png` - `/omnichannel/inbox` with the A3 rail (All / Mine /
  Unassigned / lifecycle-stage filters), Show/Sort/Priority filters,
  Unreplied toggle, and "Save view" button all present alongside real thread
  rows.
- `06-inbox-thread-open-1280.png` - opening Sarah Chen's thread shows the
  FULL (non-compact) drawer: Messages/Activities tabs + Close button in the
  header.
- `07-inbox-activities-feed-1280.png` - the Activities tab renders the A3
  `ConversationEvent` audit trail seeded/backfilled by the merged
  `event_service.backfill_tenant` call ("Conversation opened", "System
  assigned to Demo User") plus the existing internal note.
- `08-after-close-click-1280.png` / `09-close-dialog-1280.png` - the Close
  dialog opens with a "Close reason" `SearchSelect` populated by all four
  A3-seeded reasons (General Inquiry / Sales Inquiry / Payment Issue /
  Others) - confirms `close_reason_service.seed_for_workspace` /
  `backfill_tenant` (merged into `bootstrap.update_tenant`) actually ran
  against this DB.
- `10-closed-thread-1280.png` - after picking "Sales Inquiry" and confirming:
  toast "Conversation closed.", status badge flips to Closed, and the
  Activities feed logs "Demo User closed this conversation - Sales Inquiry."
  Thread was then Reopened to restore state for later manual testing.

**Note (pre-existing, not merge-introduced):** at exactly 1280px the thread
header's rightmost "Close" button sits partially past the viewport edge
(`x=1237, width=76` vs a 1280px viewport) - it is still clickable (verified
via a JS `.click()` fallback when `agent-browser find text "Close" click`
matched ambiguously against the header/label text). This is A3's shipped
header row, unrelated to the A2⇄A3 merge; not filed as a new backlog item
here since it wasn't touched by this merge, but worth a follow-up pass on
the drawer header's responsive breakpoints.

### 375px

- `11-inbox-list-375.png` - Inbox list column reflows to full width, filter
  row wraps cleanly (All / All / Newest, then priority + Unreplied on their
  own row), search box full-width, thread rows readable with wrapped badges.
- `12-inbox-thread-375.png` - opening a thread on mobile swaps to a
  single-pane "Conversations ‹ back" view (list hidden), header condenses
  (assignee dropdown visible, Messages/Activities tabs), message bubbles
  full width, composer pinned at the bottom.
- `13-contacts-list-375.png` - Contacts list reflows to a single scrollable
  column; toolbar buttons (Filters/Import/Export/Columns/Add contact) wrap
  onto two rows; table scrolls horizontally for additional columns (Name/
  Phone visible, rest scroll).

## Console / errors

`agent-browser console --session s26e` and `agent-browser errors --session
s26e` were both empty (no console messages, no page errors) across the
entire run (login through both viewport passes).

## Backend verification (companion to this browser pass)

- Module Alembic chain fixed to a single linear head (`0008 -> 0009 -> 0009a
  -> 0010`); applied to this DB via a stamp-to-0008 + `upgrade head` (details
  in the merge commit message). `close_reasons`/`inbox_views`/
  `conversation_events` tables now exist alongside A2's `contact_segments`;
  event/close-reason backfills produced 28 events + 8 close reasons (2
  workspaces x 4 seeded reasons) on this DB.
- Real App-Store update path exercised: reset the default tenant's
  `tenant_modules.installed_version` to `0.3.1`, called
  `POST /app-store/modules/omnichannel/update` as `demo@example.com`, got
  back `installedVersion: "0.4.0"`, `updateAvailable: false` with zero
  errors in the uvicorn log - confirms the merged `update_tenant` runs BOTH
  lanes' backfills unconditionally and idempotently.
- Backend suite: `3052 passed, 1 skipped, 18 deselected, 0 failed` (up from
  main's pre-merge baseline; includes A2's `test_omnichannel_contacts_module.py`
  / `test_omnichannel_deferred_actions.py` and A3's `test_omnichannel_
  conversation_events.py` / `test_omnichannel_inbox_views.py` /
  `test_omnichannel_shortcuts.py` / `test_workflow_shortcuts.py` all green
  together).
- Frontend: `npx vitest run` - 283 test files, 2119 tests, all passed.
  `npx eslint .` - 0 errors (216 pre-existing warnings, unrelated to this
  merge). `npx tsc --noEmit` - pre-existing baseline errors only (all in
  files untouched by this merge - `css/design-tokens.test.ts`, `autocount`
  test files, `no-playwright.guard.test.ts`, etc. - a root-tsconfig-vs-vitest-
  target mismatch that predates this branch; confirmed by `git log -1` on
  the one omnichannel-adjacent file in the list,
  `structured-messages.test.tsx`, showing it was last touched by plan 12,
  long before this merge). `rm -rf .next && npm run build` succeeded clean.
