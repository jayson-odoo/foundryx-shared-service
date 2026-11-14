# Plan 27 S0 - agent-browser evidence run

Lane: `agent-browser --session s27`, frontend `:3005`, backend `:8006`, DB
`foundryx_service_s27`. Logged in as `demo@example.com` / `demo1234` on the
`default` tenant (real auth, real backend for everything except the four
plan-27 mock methods - see the coder report for the exact mock/real split).

**Manual, non-code, smoke-only DB grant**: since `close_reasons.manage`,
`inbox_views.manage` and `conversations.shortcut` don't exist yet (S1-S3
backend work), three rows were inserted directly into `foundryx_service_s27`
(`permissions` + `role_permissions` for the tenant's Admin role) purely so
this run could exercise the gated controls. No code changed; a reseed of this
lane's DB will need the same manual grant again until the real CSV rows land.

## Run log (real clicks from `/`, agent-browser CLI only)

1. Signed in, clicked the **Omnichannel** sidebar section, clicked **Inbox**.
   `01-inbox-1280.png` - view rail (All/Mine/Unassigned, Lifecycle stages,
   Views incl. 3 seeded saved views), filter bar (Show/Sort/Priority/
   Unreplied), 5 real demo threads.
2. Clicked the **Hot Lead** lifecycle stage -> list correctly filtered to
   "No conversations here" (none of the real seeded demo threads are in that
   stage) -> clicked back to **New Lead** (all 5 threads, since the real
   backend seeds every demo contact at the initial stage).
3. Set **Show = Open** (`02-show-open-1280.png`, 3 threads), **Sort = Longest
   waiting** + **Unreplied = on** (`03-sort-unreplied-1280.png`, 2 threads -
   Priya Raj then Sarah Chen, both with unread inbound, ordered by
   `lastIncomingMessageAt`).
4. Clicked **Save view**, named it "Waiting 20260906", toggled **Shared**,
   saved - `04-save-view-1280.png` shows the toast, the new rail entry
   selected, and `?view=view-5` in the URL (AC-IVE-22).
5. Reloaded the exact URL for the SEEDED "Hot leads" view
   (`?view=view-2` - the freshly-created view's mock state does not survive a
   full page reload, see the coder report's "S0 mock-state" caveat) -
   `05-reload-restores-view-1280.png` shows it re-selected from the URL with
   its stored filter re-applied (AC-IVE-20's "reload restores it").
6. Opened the **Sarah Chen** thread (`06-thread-open-1280.png`), clicked
   **Activities** - `07-activities-tab-1280.png` shows the merged feed: day
   pills, `Conversation opened` / `... assigned to ...` / `... sent the first
   reply` event lines interleaved with the existing internal-note bubble.
7. Added an internal note via the Activities composer -
   `08-note-added-1280.png` - the note renders as an authored bubble with NO
   duplicate `comment_added` event line next to it (AC-IVE-34).
8. Clicked **Close**, dialog required a reason (Close disabled until chosen -
   `09-close-dialog-1280.png` shows "Payment Issue" + a note filled in),
   submitted - `10-closed-1280.png` shows the "Conversation closed." toast,
   the status chip flipped to Closed, and the Activities feed shows the close
   line with its reason.
9. Clicked **Reopen** - `11-reopened-1280.png` - status back to Open, feed
   KEEPS both the note and the close-with-reason entry.
10. Opened the **Shortcuts** control (`Run a shortcut`), listed the 3 mock
    workflows, ran "Send NPS survey" - `12-shortcut-run-1280.png` shows the
    "Shortcut started. Run run-1" toast.
11. Settings -> Workspaces -> clicked the **General** workspace row -> clicked
    the **Close reasons** tab (registered after Tags) -
    `13-close-reasons-tab-1280.png` - the 4 seeded reasons on the full
    Resource shell (Name/Sort order/Active/Uses/Date added).
12. Clicked **Create close reason**, named it "Refund 20260906", submitted -
    `14-close-reason-created-1280.png` - toast + the 5th row.
13. Resized to 375px, reloaded `/omnichannel/inbox` -
    `15-inbox-list-375.png` - single pane, rail collapsed into a View
    `SearchSelect` + a Save-view icon button, filter bar wraps, no
    horizontal scroll (`document.documentElement.scrollWidth === 375`).
14. Opened a thread at 375px - `16-inbox-thread-375.png` - single pane with a
    "‹ Conversations" back control; Activities tab -
    `17-activities-375.png` - merged feed readable, note composer visible.
15. Workspace detail at 375px, Close reasons tab -
    `18-close-reasons-tab-375.png` - toolbar stacks, table scrolls within its
    own container, page itself does not scroll horizontally.

No console errors observed at any point (`agent-browser errors` empty
throughout).

## Traps hit (for the next lane / tester)

- **Radix `Popover` (SearchSelect) + cmdk options do not reliably respond to
  `agent-browser click @ref` or a plain scripted `.click()`** in this
  environment - both silently no-op more often than not. The reliable pattern
  found: dispatch a full `pointerdown -> mousedown -> pointerup -> mouseup ->
  click` sequence (all bubbling, with `clientX/clientY` at the element's
  center) via `agent-browser eval --stdin`, both on the trigger AND on the
  `[cmdk-item]` option. `agent-browser fill @ref "text"` DOES reliably filter
  the list (it types real key events some other way), just not select.
- **Radix `Tabs` triggers are the same** - a plain `.click()` sometimes no-ops
  (the Activities tab, the workspace form's tab strip); the same synthetic
  pointer-event sequence fixed it every time it was needed twice.
- **A `document.querySelectorAll('button')` text-match can hit the WRONG
  button** when a dialog's submit button shares its exact label with the
  toolbar trigger that opened it (e.g. two "Create close reason" buttons are
  in the DOM at once, the dialog's UNDER an overlay). Scope the query to
  `document.querySelector('[role=dialog]')` first.
- **A hard `agent-browser open <url>` navigation resets every S0 in-memory
  mock** (module-level `let` state in the browser's JS - not server state).
  A freshly-created saved view / a bumped `usesCount` will NOT survive it;
  only a real in-app client-side route transition (a real link click) would
  preserve it. Seeded rows (the 4 close reasons, the 4 saved views) always
  come back since they re-seed on module load.
- `agent-browser click "[data-testid=...]"` (CSS-selector click) also
  no-op'd on the lifecycle-stage rail buttons; `document.querySelector(...).
  click()` via `eval` worked immediately for those (plain, non-Radix
  `<button>`s - so this one is likely a CLI/CDP coordinate-targeting quirk
  rather than a Radix-specific issue).
