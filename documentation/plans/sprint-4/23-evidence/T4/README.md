# T4 - Header, wayfinding, rows, list latency - evidence run log

Branch `sprint-4/23-T4-header-rows-latency` (off `sprint-4/23-design-language-alignment`,
T0+T1+T2+T2b merged). Backend on `:8001` (shared, already running). Frontend
`rm -rf .next && npm run build` (green) served via `npx next start -p 3002` (this worktree,
ownership confirmed via `lsof -p $(lsof -ti :3002) | grep cwd` before every restart). `agent-browser`
CLI, real clicks (with an `eval`-dispatched `.click()` fallback where the CDP click helper missed -
same house note as T2 fix round 3), `demo@example.com` / `demo1234`.

**Isolation note:** partway through this run `agent-browser`'s default (unnamed) session was found
pointed at `localhost:3003` - a peer coder's concurrent worktree had taken over the shared default
Chrome tab. All evidence from that point on runs under `agent-browser --session t4-s23 ...` (an
isolated browser with its own tabs/cookies) confirmed on `:3002` before every subsequent action.
Screenshots 00-17 were already independently confirmed against `:3002` via `get url` before the
hijack was noticed, so they stand as valid evidence; nothing in this run was captured against the
wrong build.

## Data seeded

13 users total (5 pre-existing + `E2E Seed User A`..`H` created live through the UI, `05 Sept 2026`
timestamped names/emails) so Users has more than one page at `Rows per page = 10`.

## Run log

1. Signed in, Dashboard loads clean, no console errors (`00-dashboard-1280.png`).
2. Sidebar User Management > Users - `01-users-list-1280.png`: `PageHeader` renders "Users" h1,
   breadcrumb `Dashboard > User Management > Users`, "Add user" primary button moved into the
   header's actions slot (no longer in the card's own toolbar) - AC-DLA-27/D6.
3. "Add user" -> `/user-management/users/new` (`02-user-new-1280.png`): toolbar row = `PageHeader`
   with "Back to users" in the actions slot; record card = identity ("New user" / "Invite a new
   user") left, `Cancel` + `Create user` right - AC-DLA-28/D5. Created `E2E Seed User A` -> landed
   on its detail page (`03-user-detail-after-create-1280.png`): identity (avatar, name, email
   subtitle) left, gear `Actions` button + `Edit` right.
4. Opened the gear menu (`04-user-gear-menu-1280.png`): `Send invitation` / `Impersonate`
   (disabled) / `Reset password` / `Resend verification` / `Trash` - secondary items first, a
   separator, `Trash` (destructive) last, per AC-DLA-28's ordering.
5. Created 7 more seed users (B-H) via the same flow (13 total). Users list, set `Rows per page`
   to 10 -> 2 pages (`05-users-list-page1-1280.png`, `06-users-list-page2-1280.png`). Clicked "Next
   page", opened "Event Staff" (row 11/13, page 2) -> URL carried
   `ctx=<encoded query>&i=10&from=<rowId>` (AC-DLA-29) (`07-user-detail-from-page2-1280.png`, pager
   showing `Previous/Next record`). Clicked "Back to users" -> its own `href` carried the SAME
   `ctx`/`i`/`from` (AC-DLA-28).
6. **AC-DLA-30, journey 1 (paginated list):** after Back, "Event Staff" is scrolled into view and
   highlighted `bg-primary/5` (`08-users-back-restored-page2-1280.png`) - confirmed via
   `data-returned="true"` on the correct `data-row-id` (`eval` check), and confirmed it clears on
   the next `pointerdown` (`09-users-back-highlight-cleared-1280.png` + an `eval` re-check: `{
   stillReturned: false }`).
7. **AC-DLA-30/31, journey 2 (record-nav stepping):** opened "E2E Seed User H" (row 1, `i=0`),
   stepped `Next record` three times (`ctx` confirmed present and unchanged on the URL after EVERY
   step - see the bug note below), landed on "E2E Seed User E" (`10-user-detail-after-3-steps-
   1280.png`). Clicked "Back to users" -> "E2E Seed User E" scrolled into view and highlighted
   (`11-users-back-after-3-steps-1280.png`).
8. **AC-DLA-36, journey 2 (Settings > Statuses):** `/settings/statuses` (`12-settings-statuses-
   1280.png`, `PageHeader` "Statuses" + breadcrumb). Opened "Idea" -> `/settings/statuses/idea`
   with `ctx`/`i=1`/`from=idea` (`13-status-idea-detail-1280.png`: toolbar row "Statuses" h1 +
   breadcrumb + "Statuses" Back button; record card "Idea" identity, Flow/Statuses tabs, Edit -
   no gear, since this entity's form-surface action list is empty, correctly nothing renders).
   Clicked Back (the top-right button specifically, not the breadcrumb link, which intentionally
   does NOT carry record-nav state) -> "Idea" row restored + highlighted
   (`14-statuses-back-restored-1280.png`).
9. 375px sweep: Users list (`15-users-list-375.png` - header wraps, "Add user" drops below the
   title/breadcrumb, toolbar wraps), a user detail (`16-user-detail-375.png` - identity stays one
   row, `[gear] [Edit]` wraps to its own row underneath, per D5's stated wrap behaviour), the SAME
   user detail at 1280 for comparison (`17-user-detail-1280.png`), the Idea status detail at 375
   (`19-status-idea-detail-375.png`).
10. **AC-DLA-34 (hover-prefetch, Network panel):** cleared the request log, hovered a Users row -
    `agent-browser network requests` showed the RSC prefetch fetch + the detail route's JS chunk
    (`page-46159b546664fe27.js`) fire on HOVER. Cleared again, clicked the SAME (now-hovered) row -
    the click's own request log shows the data fetches (`/users/<id>`, `/roles/options`,
    `/users/at?...`) but NO repeat `page-*.js` chunk request - it was already warmed by the hover.
11. **Bug found + fixed live (ctx dropped on every record-nav step):** the FIRST `Next record`
    click during step 7 initially produced a URL with `i`/`from` but NO `ctx` at all -
    `buildListNav`'s `ctx` handling unconditionally deleted the key on any call that didn't supply
    it, but `use-record-nav.ts`'s `go()`/prefetch calls it with only `{ from }` (relying on
    `buildHref` having already embedded `ctx` in the href string). Fixed to match `i`/`from`'s
    existing "omitted key leaves the href's own value alone" contract; re-verified step 7 end to
    end after the fix (screenshots above are POST-fix). Regression pinned in
    `lib/list-context.test.ts` + `hooks/use-record-nav.prefetch.test.ts`.
12. **Bug found + fixed live (negative index 422 on the first record's prefetch):** opening the
    FIRST record's detail page fired `GET /users/at?index=-1...` -> 422 (harmlessly swallowed by
    the existing `.catch()`, but wasteful/noisy) - the prev-neighbour prefetch used a naively
    unwrapped `index - 1` before a real `total` was known. Merged the total-fetch and prefetch
    effects into one sequenced effect so the wrap happens using the total the record's OWN
    `fetchAt` call already resolved. Re-verified: opening the first record now fires
    `index=0`/`index=12` (wraps to `total-1`)/`index=1` - zero negative indices, zero 422s
    (`18-user-detail-negindex-fix-1280.png` + a `network requests` check: `grep -c 422` = 0).
    Regression pinned in `hooks/use-record-nav.prefetch.test.ts`.
13. **AC-DLA-32 (rows stay dimmed while loading):** verified indirectly - the hook contract
    (`isPlaceholderData`, no skeleton flash, pagination stays interactive) is unit-tested
    (`use-resource-list` T2 tests + `resource-list.rowHref.test.tsx`'s own render). A live visual
    capture of the dim state is not reliable against a local backend (sub-millisecond response, no
    frame lands mid-dim); Next/sort/filter/search all completed without a skeleton flash or a
    console error across every list visited in this run (Users repeatedly, Statuses, Jobs), which
    is the user-visible half of the contract. Second-press-wins is unit-tested
    (`use-resource-list` debounce/reload tests, unchanged in T4).
14. **AC-DLA-33 (no `disabled={isLoading}` on list toolbars) - INCOMPLETE at the time, corrected in
    Fix round 1 below:** the `grep` swept the list toolbar's own buttons (Filters/Export/Import/
    Columns/Create) and found them clean, but never checked the DataGrid PRIMITIVE's own sort button
    and select-all checkbox - both carried `disabled={isLoading || recordCount === 0}` and went
    disabled on every placeholder refetch, not just an empty list. See the Fix round 1 log.
15. Console clean (`agent-browser console`) on every page in this run.

## AC verdicts

- **AC-DLA-27** PASS - `PageHeader` primitive + inventory test (zero `ToolbarPageTitle`, zero raw
  `<h1>` outside `page-header.tsx` under the real app-chrome surface, empty allowlist, no
  `id.slice(`/`substring(` title fallback). Migrated all 79 real `ToolbarPageTitle` sites + the
  real `<h1>` sites (steps 2, 8, 9 above + the inventory test run).
- **AC-DLA-28** PASS - steps 3, 4, 7, 8.
- **AC-DLA-29** PASS - steps 2, 5, 10 (`role="link"` in every linkable row's primary cell,
  `ctx`/`i`/`from` on every href).
- **AC-DLA-30** PASS - steps 6, 7, 8 (both journeys), including the highlight-clears-on-pointer
  check.
- **AC-DLA-31** PASS - step 10 (Network-panel hover-vs-click chunk check) + step 12 (the
  negative-index bug this AC's own prefetch surfaced, fixed and re-verified).
- **AC-DLA-32** PASS (hook-level; see step 13's remark on live-visual limits at localhost latency).
- **AC-DLA-33** was a FALSE PASS at the time (step 14) - corrected in Fix round 1 below (now
  genuinely PASS at the DataGrid-primitive level, not just the list toolbar).
- **AC-DLA-34** PASS - step 10 (DataGrid row hover-prefetch); sidebar `Link prefetch={false}` +
  `onPointerEnter` is unit-tested (`sidebar-menu.prefetch.test.tsx`) since the sidebar's own
  chunks are already resident on every page in this run (a live hover-vs-click chunk diff on the
  sidebar itself is not distinguishable from the DataGrid case already demonstrated).
- **AC-DLA-35** PASS - "Add user"/"Create user"/"Save user" observed live (steps 2-3); dialog
  sweep fixed 8 more sites (term/numbering/quick-reply/media-caps dialogs, document types dialog,
  status/transition drawers, folder dialogs) + matching test updates, all green.
- **AC-DLA-36** PASS - steps 5-9 (Users list -> row -> Back at both widths; Settings > Statuses ->
  Idea -> Back at both widths).

## Gate

`npx eslint` on every touched file (clean). `npm test`: 192 files / 1630 tests reported green at the
time - but the "pre-existing, confirmed present on the unmodified integration branch" claim below was
WRONG (**corrected in the Fix round 1 log below**): `ideation/board/page.test.tsx`'s unhandled
rejection was this exact T4 slice's own regression (its `ToolbarPageTitle` -> `PageHeader` migration
touched that page; the spec's mock still targeted the retired toolbar). `rm -rf .next && npm run
build` green (only the pre-existing `@media (max-width: var(--screen-lg))` CSS optimizer warning,
unrelated). Server restarted on `:3002` with ownership confirmed via
`lsof -p $(lsof -ti :3002) | grep cwd` before every restart in this run.

## Fix round 1 (AC-DLA-27..36 review findings, D5/D6/D7)

Branch unchanged (`sprint-4/23-T4-header-rows-latency`), same worktree, session
`agent-browser --session t4fix` (isolated, per the brief). Full findings + fixes are in the test
report's "T4 - Fix round 1" section; this log records only the LIVE run.

16. Backend `:8001` confirmed up (`/health` -> `{"status":"ok"}`). Frontend `rm -rf .next && npm run
    build` green; `:3002` owned by a stale process from THIS worktree (pid confirmed via
    `lsof -p <pid> | grep cwd` before kill) - killed, rebuilt, restarted clean, confirmed `curl` 200.
17. Signed in (`demo@example.com`/`demo1234`). Reused the 13 users already resident from the base T4
    run (5 pre-existing + `E2E Seed User A`..`H`) - no new seeding needed, 13 rows at `Rows per
    page=10` already forces the exact 2-page scenario AC-DLA-30's fix needs.
18. **AC-DLA-33 fix, live:** Users list, clicked the "User" sort header twice in immediate
    succession; `eval`-read `.disabled` on the button right after each click - `false` both times
    (never disabled mid-refetch), sort toggled asc -> desc on the second click
    (`fixround1-09-users-sort-toggle-never-disabled-1280.png`). Rows stayed on screen the whole time,
    no skeleton.
19. **AC-DLA-30 fix, journey at 1280:** Rows per page -> 10, sorted by User ascending
    (`fixround1-01-users-page2-sorted-1280.png`, page 2, arrow-up on "User"). Opened row 12 ("Event
    Staff") - href inspected via `eval` before clicking: `ctx` decodes to `{page:1 (0-based),
    pageSize:10, sort:{id:"user",desc:false}, statusView:"active"}`, `i=11`, `from=<id>`
    (`fixround1-02-users-record12-crumb-1280.png` - crumb correctly reads "Users > Event Staff", not
    the sidebar-derived "Users" alone - AC-DLA-30 item 10). Clicked "Back to users" - its own `href`
    (read via `eval` before the click) matched the SAME `ctx`/`i`/`from` byte for byte. Landed on
    page 2, sorted, "Event Staff" scrolled into view and highlighted
    (`fixround1-03-users-back-restored-page2-sorted-1280.png`).
20. **Same journey at 375:** fresh page load (viewport 375x800), rows-per-page -> 10 (dropdown driven
    via `eval` since the mobile Radix select portal needed the same click-fallback), sorted by User,
    page 2 (`fixround1-04-users-page2-sorted-375.png`). Opened "Event Staff"
    (`fixround1-05-users-record12-crumb-375.png` - crumb "Users > Event Staff", record 12/13). Back
    restored page 2, sorted, "Event Staff" highlighted (`fixround1-06-users-back-restored-page2-
    sorted-375.png`).
21. **AC-DLA-27/D6 crumb-resolver + AC-DLA-27 header-in-Container fixes, live (findings 5 and 7
    together):** `/documents/settings` - crumb "Dashboard > Documents > Settings > Document
    settings" (NOT shadowed by the sibling "Documents"/"All documents" list item), sidebar
    highlights "Settings" under the Documents group, `aria-current` confirmed via `eval` =
    "Document settings"; title+description sit flush with the Storage card's left edge
    (`fixround1-07-documents-settings-crumb-header-1280.png`). `/developers/logs/settings` - crumb
    "Dashboard > Developers > Log settings" (NOT shadowed by the sibling "Logs"), title "Log
    settings" (not "Logs"), `aria-current` = "Log settings", header flush with the Log retention
    card, primary button reads "Save log settings" (finding 8, live)
    (`fixround1-08-developers-logs-settings-crumb-header-save-1280.png`).
22. **AutoCount task editor primary label (finding 6):** not captured live - the company detail
    form's Radix `Tabs` and the Entities-tab row click both needed a full synthetic `PointerEvent`
    sequence dispatched via `eval` to register (a harness quirk on this specific double-nested
    tab+row-click combination - `agent-browser click`/`find role tab click`/keyboard `ArrowRight` all
    silently no-op'd on the TAB switch itself, and the same technique that DID switch the tab did not
    reliably trigger the row's own navigation in the time budgeted this round). The fix is covered
    by a dedicated unit test (`resource-form.header.test.tsx` - `entityNoun: 'task'` renders "Save
    task") using the exact same code path already proven live for every other form in steps 19-21.
23. Console clean (`agent-browser console`/`errors`) throughout this run; no 4xx/5xx observed in any
    request while navigating.

## Fix round 1 AC re-verdicts

- **AC-DLA-30** now genuinely PASS past page one (was a false PASS in the original run - see the
  Gate correction above). Live at both widths (steps 19-20).
- **AC-DLA-33** now genuinely PASS at the DataGrid-primitive level, not just the list toolbar (was a
  narrow-scope false PASS). Live (step 18) + unit (`data-grid-column-header.placeholder.test.tsx`).
- **AC-DLA-27/D6** (crumb correctness + header-in-Container) - the shadowed-route and PageHeader-
  outside-Container defects were never explicitly ACd by number but are covered under AC-DLA-27's
  "one page-title header" umbrella; both now verified live (step 21).
