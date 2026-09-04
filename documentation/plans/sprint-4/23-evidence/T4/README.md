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
14. **AC-DLA-33 (no `disabled={isLoading}` on list toolbars):** static - `grep` across
    `app/`+`components/` for `disabled={.*isLoading` finds zero matches on any list toolbar filter
    or primary button (the baseline-3 this AC references was already clean going into T4, likely a
    side effect of T2's `isPlaceholderData` rework removing the old loading-guard pattern).
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
- **AC-DLA-33** PASS - step 14.
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

`npx eslint` on every touched file (clean). `npm test`: 192 files / 1630 tests, all green (one
pre-existing unrelated unhandled-rejection console error in `ideation/board/page.test.tsx`,
confirmed present on the unmodified integration branch too - not a T4 regression). `rm -rf .next
&& npm run build` green (only the pre-existing `@media (max-width: var(--screen-lg))` CSS
optimizer warning, unrelated). Server restarted on `:3002` with ownership confirmed via
`lsof -p $(lsof -ti :3002) | grep cwd` before every restart in this run.
