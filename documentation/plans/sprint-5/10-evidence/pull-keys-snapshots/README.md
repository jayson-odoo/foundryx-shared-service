# Evidence: Pull page - Keys and Snapshots (AC-10-38, AC-10-48, AC-10-49)

Run date: 2026-09-20 (UTC). Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`.
Tenant/user: `default` tenant, `demo@example.com` (Admin). Real clicks from the sidebar:
AutoCount -> Pull.

## Steps and checks

1. Sidebar -> AutoCount -> **Pull** -> reaches `/autocount/pull`, menu entry highlighted correctly
   (module + permission gating renders the item at all, confirming `autocount.pull.read` reached
   this tenant's Admin - see the setup section of the final report). **PASS.** Screenshot
   `01-pull-page-keys-1280.png`.
2. **Keys** segment (a `SearchSelect`, not a tab strip) shows columns Name / Companies / Created /
   Last used / Status, default state "No data available" (0 rows). **PASS** shape-wise.
3. **Issue key** opens a `ResourceForm`-style dialog: Name (free text) + Companies (`MultiSelect`,
   searchable, offered "Sorento SRT S40" - the only company in this tenant). **PASS.** Screenshots
   `02-issue-key-dialog-1280.png`, `03-issue-key-filled-1280.png` (name filled, company chip
   selected).
4. **DEFECT:** clicking the dialog's **Issue key** submit button closes/resets the dialog to a
   blank state - no plaintext-key reveal screen appears (the "shown once with a copy control" UX
   in AC-10-38 never renders), and the Keys table still reads "No data available" (0 rows)
   immediately afterward, with no reload in between. No network request fired for the submit
   (confirmed via `network requests` - consistent with this surface being mock-bound as documented
   in the brief), so this is a mock-wiring gap: the mock service's "issue key" mutation does not
   append to its own in-memory list, and the plaintext-reveal screen is never reached. This is
   different from the brief's flagged "mock state resets on reload" - here the mutation does not
   even take effect within the SAME session before any reload. Screenshot `04-issue-key-plaintext-
   1280.png` shows the reset (empty) dialog immediately after submit. Reported to the coder; not
   fixed here.
5. Switched segment **Keys -> Snapshots** via the SearchSelect: selection/search cleared, columns
   changed to Entity / Company / Status / Records / Complete / Built / Expires (grid scrolls
   internally for the extra columns). **PASS** against "selection clears on view switch."
   Screenshot `05-snapshots-segment-1280.png`.
6. **Build snapshot** opens a dialog with Company + Entity `SearchSelect`s. **DEFECT:** the Company
   picker offers **zero options** ("No matches." - confirmed via the popover's own empty state, not
   a search-filter artifact; no network call fired on open, so this is fixture data, not a live
   read). This makes the primary CTA of the Snapshots segment non-functional in this session:
   there is no way to proceed to entity selection, matched/missed testing, or a status
   walkthrough (building/ready/failed/expired) because the flow cannot start. Screenshot
   `06-build-snapshot-dialog-1280.png`.
7. Given findings 4 and 6, the deeper checks this journey was scoped to (active + revoked key
   rows with `StatusBadge`, Issue-key plaintext copy-then-gone, Revoke deferred-action grace
   window + undo, snapshot building/ready/failed/expired states, the `PUSH_ACTIVE` 409 render,
   product/stock snapshot detail with counters and excluded rows) **could not be reached** - the
   mock fixtures described in AC-10-48 ("no keys, one active and one revoked key, a building/
   ready/failed/expired snapshot, a stock snapshot with exclusions and negative pairs, and a 409
   PUSH_ACTIVE") are not observable anywhere in this build: every list starts and stays empty, and
   the one interactive path this session tried (Issue key, Build snapshot) did not progress past
   its own dialog.

## Responsive (375px)

- Pull page (Keys segment) at 375px: no page-level horizontal scroll
  (`document.documentElement.scrollWidth == clientWidth == 360`), grid scrolls internally, Issue
  key button and toolbar wrap sensibly. **PASS.** Screenshot `07-pull-page-375.png`.
- Dialogs were not re-verified at 375px given they could not be progressed past their initial
  state at 1280px either (see findings above) - re-testing at the smaller width would not surface
  new information about the same underlying gap.

## House rules

- No hint/instructional copy visible. **PASS.**
- Segment switch and both dialog pickers are searchable `SearchSelect`/`MultiSelect`. **PASS.**
- No "Foundryx" branding visible. **PASS.**
- Console: only the pre-existing benign `DialogContent` a11y warning across this journey; no page
  errors. **PASS.**

## AC verdicts

- **AC-10-38 [FE]:** PARTIAL. Page reachable via the gated sidebar entry, `ResourceList` shell with
  the Keys|Snapshots `SearchSelect` segment, both dialogs (Issue key, Build snapshot) render with
  the right fields and searchable pickers. FAIL on the interactive core: issuing a key does not
  produce the required plaintext-shown-once screen and does not add a row; the deferred-action
  Revoke flow could not be reached at all (no key ever exists to revoke).
- **AC-10-48 [FE]:** FAIL on the "mock fixtures cover every state" clause - none of the described
  fixture rows (active/revoked keys, building/ready/failed/expired/stock snapshots, 409
  PUSH_ACTIVE) were observed; every list is empty by default and stays empty after the only
  mutating actions available in the UI.
- **AC-10-49 [FE]:** NOT VERIFIABLE - no snapshot could be created or opened in this session, so
  the detail surface (header facts, metadata blocks, excluded-row list, preview grid reuse) was
  never rendered.
