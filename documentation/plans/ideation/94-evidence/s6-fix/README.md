# S6 fix evidence - Triage board live render crash (AC-94-58, issue #94)

Lane reused from S6: backend :8016 (pid 39803, untouched, left running), frontend
rebuilt + restarted on :3016 (new pid recorded in the commit's PR/report). DB
`foundryx_service_ir2`, same seeded data as the S6 run (default tenant, `demo@example.com`).

## Root cause

`TriageBoard` kept its Kanban-controlled `columns` state in sync with the
server-driven column set (`useIdeas({ withBoard: true })`) via a `useEffect`.
On the FIRST render after `loading` flips from true to false (the moment the
real `GET /ideation/ideas/board` response actually arrives), `source` (the
column list, derived via `useMemo` from the fresh `columns`/`ideas`) already
reflects the real 5-column shape, but the `columns` STATE that gets passed to
`<Kanban value={columns}>` was still the value computed at MOUNT time
(`buildColumns([], [])` = `{}`, since nothing had loaded yet) - the sync
`useEffect` only fires AFTER that render commits, one tick too late. The
shared `Kanban` primitive's `KanbanColumnContent` reads
`columns[value].map(getItemId)` with no `?? []` guard
(`components/ui/kanban.tsx:450`), so that one render threw exactly the
reported `TypeError: Cannot read properties of undefined (reading 'map')`,
caught by the app's generic error boundary. `board/page.test.tsx` never saw
this because it mocks `useIdeas()` wholesale with already-resolved data,
never exercising the loading -> loaded transition.

## Fix

`app/(protected)/ideation/board/triage-board.tsx`: replaced the
`useEffect`-based sync with React's documented "adjust state during render"
pattern - `columns` is reset to the freshly memoized `computed` value
synchronously, on the SAME render `source`/`ideas` change, so the Kanban
primitive never sees a `columns` object missing a key `source` already
carries. No change to `handleMove`/`onMove`/drag-drop logic itself.

## Regression test

`app/(protected)/ideation/board/triage-board.live.test.tsx` (new) - renders
`TriageBoard` through the REAL `useIdeas` hook and the REAL bound
`ideationService` (`realIdeationService`, not the mock), mocking only
`apiFetch` at the wire boundary with the EXACT live response shape (every
column populated with `ideas: [...]`, full `IdeaOut` fields). Confirmed RED
against the pre-fix `triage-board.tsx` (`git stash` the fix, rerun - fails
with the identical `TypeError` at `kanban.tsx:450`), GREEN after.

## Live verification (agent-browser --session ir2)

Rebuilt with the CORRECT env (see gotcha below) and restarted `next start`
on :3016; logged in as `demo@example.com`, navigated Ideation > Triage board
via the sidebar (real clicks, not a URL jump).

- **1280px**: `AC-94-58-board-fixed-1280.png` - all 5 columns render
  ("New" 10 cards, "Triaged"/"Linked to BR"/"Building"/"Delivered" empty with
  "Drop ideas here"), no crash, no error boundary.
- **375px**: `AC-94-58-board-fixed-375.png` - same, columns stack
  horizontally-scrollable, cards readable, no clipping.
- Confirmed via `network requests` that `GET /ideation/ideas?filter=all`,
  `GET /products`, `GET /ideation/ideas/board` all return 200 and the board
  renders the returned cards under "New" (10 real E2E-seeded ideas from the
  S6 run, including the merged survivor "India" showing "1 merged").

### Drag verification - NOT completed (tooling limitation, not a product finding)

Attempted a card drag from "New" into "Triaged" via `agent-browser drag`,
a hand-rolled `dnd-kit`-targeted pointer-event sequence (`pointerdown` on the
exact `[data-slot="kanban-item-handle"]` node, stepped `pointermove`s, then
`pointerup` over `[data-slot="kanban-column-content"]`), and the low-level
`agent-browser mouse move/down/up` primitives. None produced a column
change. Diagnostic: added a `window`-level capture-phase listener for
`mousedown`/`mouseup`/`mousemove`/`pointermove` and re-ran `agent-browser
mouse down`/`up` and `agent-browser find text "Home" hover` (a plain nav
link, nothing dnd-kit-related) - **zero events were captured for ANY of
these**, while my own `element.dispatchEvent(...)` calls (used earlier in
this same session to work around the documented click-on-motion-wrapper
gotcha for the sidebar menu and the sign-in button) demonstrably worked
(confirmed by URL/DOM changes). This isolates the failure to this
`agent-browser` session's CDP-level mouse input delivery in general, not to
dnd-kit or to this fix - it reproduces on a trivial, non-drag element too.
Not filed as a product defect; the fix's own regression test
(`triage-board.live.test.tsx`) plus the unchanged `canMoveTo`/`handleMove`
code (only the state-sync mechanism changed, not the move logic) are the
evidence of record for the drag path. Left for a future lane with a
`--headed` session or a different CDP target if a live drag screenshot is
still wanted.

## Environment gotcha found while rebuilding (not a product bug)

`NEXT_PUBLIC_BACKEND_API_URL` is inlined by Next.js at BUILD time, not read
at `next start` time. The first rebuild attempt set the env vars only for
`npx next start` (matching a literal reading of the original S6 README),
which produced a build still pointed at the DEFAULT backend origin
(`http://localhost:8000`, not `:8016`) - the app loaded but every ideation
fetch failed silently (`Failed to fetch`, cross-origin to the wrong, unlisted
port). Re-ran `rm -rf .next && npm run build` WITH
`NEXT_PUBLIC_BACKEND_API_URL`/`BACKEND_API_URL`/`NEXTAUTH_URL`/
`NEXTAUTH_SECRET` all exported for the build step itself, then started with
the same vars - confirmed via `network requests` that every ideation call
now hits `:8016`. Documented here so a future rebuild of this lane sets the
vars before `npm run build`, not just before `next start`.
