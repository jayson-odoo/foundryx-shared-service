# Round-7 verify - Defect 4 closed (change-the-endpoint flow)

Lane s37, backend `:8007` (HEAD `2326510b`, restarted this pass: killed pid `81585` after
confirming its `cwd` was `s37/service_backend`, started `.venv/bin/python -m uvicorn
app.main:app --port 8007` from `service_backend/`, new pid `18339`). Frontend `:3007` (HEAD
`2326510b`, rebuilt this pass: killed pid `9149` after confirming its `cwd` was
`s37/service_frontend`, `rm -rf .next && npm run build` (clean, exit 0), `npx next start -p
3007` (never `npm start`), new pid `18628`). DB `foundryx_service_s37` (`auth_throttle` already
empty, no cleanup needed). Browser: `agent-browser --session s37-verify7`, headless, real
clicks from `/` via the sidebar (never a deep URL). Run date 2026-09-12 (UTC+8 lane clock).

**Tooling note (repeats round-4/5/6 findings, confirmed again this pass):** plain `click`/CDP
mouse dispatch did not open the sidebar `AutoCount` accordion, the "Companies" sidebar link,
tab triggers (`Review & Activate`), or the row/header `Actions` dropdown (open AND item-select
both needed it) in this session; a full synthetic pointer sequence (`pointerdown` -> `mousedown`
-> `pointerup` -> `mouseup` -> `click`, dispatched via `element.dispatchEvent` at the element's
real `getBoundingClientRect()` center, `pointerType: 'mouse'`) opened/selected every one
reliably. Plain `agent-browser click`/`fill` worked for ordinary buttons/links/inputs (Test,
Edit, Save task, Cancel, Activate/Resume/Pause once a menu item or tab had already landed via
the real-dispatch method, table rows). Environment/tooling quirk only - still drives the real
component tree, router and permission checks, never a URL shortcut.

Company used: `Mocha 20260912T004004Z` (`d0b58883-6a87-46a3-abf1-0fe5aef8dd55`, `sinkImpl:
logging`) - the SAME logging-sink company used throughout this plan's evidence. Tasks used:
`warehouse` (`autocount_http`, saved path `/location`, was `active` at the start of this pass)
and `unit_of_measure` (`autocount_http`, saved path `/itembypage`, was `active` at the start of
this pass, left over from round 6).

## Check 1 - Defect 4 closed (change-the-endpoint flow: Save stays enabled at an edited path,
all the way through Activate)

Real clicks: Companies list -> `Mocha 20260912T004004Z` row -> Entities tab -> Warehouse row's
Actions menu -> "Configure source" -> task editor opens on the Source tab (view mode, path
`/location`, task `active`).

1. **Warehouse before** (`01-warehouse-before-{1280,375}.png`): view mode, path `/location`,
   `Test` enabled, task active.
2. **Pause** (header Actions menu -> "Pause", real click): succeeded, confirmed via `psql`
   (`etl_status = 'paused'`), zero console errors.
3. **Edit** -> changed the path field to a DIFFERENT valid path B. First attempt,
   `/location?x=1` (curl-verified 200, same JSON shape as `/location`), was rejected by the
   backend's own path-rule gate - `POST /autocount/http/preview` returned a 422
   `{"path": "The path may not include a query string - page params are ours."}`
   (`validate_http_path` in `service_backend/modules/autocount/http_source/preview.py`
   correctly rejects any `?` in an operator-typed path; this is EXISTING, documented AC-08-13
   behaviour, not a defect - it just meant path B needed a different valid variant). Switched
   to path B = `/location/` (a curl-verified-200 trailing-slash variant of the same endpoint,
   same JSON shape, same pattern round 6 used for `/itembypage/`) -
   (`02-warehouse-edited-path-before-test-1280.png`, `Save task` correctly DISABLED before
   Test: `{"disabled": true}`).
4. **Test** on path B (real click): succeeded (`POST /autocount/http/preview` 200, preview grid
   repopulated with the real Location rows). `Save task` immediately read `{"disabled": false}`
   - `03-save-enabled-immediately-after-test-1280.png`.
5. **Waited 3 seconds, re-checked `Save task`'s `disabled` property: still `{"disabled":
   false}`** - `04-save-still-enabled-after-3s-{1280,375}.png`. **This is Defect 4 CLOSED**: at
   the pre-round-7 HEAD (per the coordinator's brief) `Save` would have re-disabled itself after
   the Test's success handler reseeded `httpPreviewedFor` off `task.sourceConfig` (the SAVED
   pair, `/location`) rather than the just-tested UNSAVED pair (`/location/`) - the round-7 fix
   (`task-editor-view.tsx`'s seed-once effect, `setHttpPreviewedFor((prev) => prev ?? seeded)`)
   stops that reseed from ever overwriting a value the Test handler already set. Zero console
   errors at any point in this sequence (`agent-browser errors` empty).
6. **Save** (real click): succeeded, `PUT .../etl-task` 200
   (`05-source-tested-twice-after-save-1280.png` was actually taken on the SECOND Test below;
   confirmed via `psql`: path persisted as `/location/`, `etl_status` remained `paused`
   unaffected by the save of an already-paused task).
7. **Test again** on the saved path B (real click, still the same Source tab, no navigation):
   succeeded (`POST /autocount/http/preview` 200) -
   `05-source-tested-twice-after-save-1280.png`.
8. Clicked **Review & Activate** directly (full pointer-sequence dispatch on the tab trigger,
   same mounted `TaskEditorView`, `get url` unchanged before/after): the task was `paused`, so
   the action button reads **Resume** (the same gate `Activate` reads on a `draft` task) -
   rendered **ENABLED** on the first render (`{"disabled": false}`) -
   `06-review-activate-resume-enabled-same-mount-{1280,375}.png`.
9. **Resume** (real click, `POST .../etl-task/resume` 200): status flipped **in place** to
   `active` with **no navigation, no reload, no console errors** (`agent-browser errors` and
   `console` both empty; `get url` unchanged) -
   `07-resumed-active-status-flip-{1280,375}.png`. Confirmed via `psql`:
   `etl_status = 'active'`, `path = '/location/'` immediately after the click.
10. **Restored path A**: Edit -> changed the path back to `/location` -> Test (succeeded,
    `POST .../preview` 200) -> **Save** (`PUT .../etl-task` 200; per AC-08-28's documented
    "editing an ACTIVE task's source config demotes it to draft" rule, `etl_status` correctly
    read `draft` immediately after this save - `08-path-a-restored-1280.png`) -> re-entered
    Edit, re-ran Test on the now-saved path A (succeeded), Save (idempotent, no field change,
    the app closed edit mode client-side with no new `PUT` - the prior Test's `last_preview_at`
    stamp was already current) -> Review & Activate (same mount, `Activate` read `{"disabled":
    false}`) -> **Activate** (`POST .../etl-task/activate` 200): task restored to its EXACT
    starting state, `etl_status = 'active'`, `path = '/location'`
    (`09-warehouse-fully-restored-active-1280.png`, confirmed via `psql`). Zero console errors
    throughout the restoration.

**Verdict: Defect 4 (Save re-disabled after Test at an edited path) CLOSED at `2326510b`.**
`Save task` renders enabled immediately after a Test at an EDITED (unsaved) path and stays
enabled through a 3-second wait with no reseed; Save -> Test -> Review & Activate -> Activate/
Resume all completed in the same mount with zero navigation and zero console errors; the
warehouse task was fully restored to its pre-check state (`active`, `/location`) afterward.

## Check 2 - Defect 3 regression check (Test -> Save -> Test -> Review & Activate, same mount)

Real clicks: Companies -> Mocha company -> Entities tab -> Unit of measure row's Actions menu
-> "Configure source" (task was `active`, saved path `/itembypage`, left over from round 6).

1. Header Actions -> **Pause** (real click): succeeded, `psql` confirms `etl_status = 'paused'`.
2. **Test** on the saved path (view-mode Test button, real click): succeeded (`POST
   .../preview` 200) - `10-uom-before-{1280,375}.png` (before), then Test ran.
3. **Edit** -> **Save task** (no field changes; the app closed edit mode client-side with no
   new `PUT` fired - the immediately-prior Test had already stamped `last_preview_at`, `psql`
   shows `updated_at` matching that Test's timestamp, not a later one).
4. **Test again** (view-mode Test button, same Source tab, no navigation): succeeded (`POST
   .../preview` 200) - `11-uom-tested-twice-1280.png`.
5. Click **Review & Activate** directly (full pointer-sequence dispatch, same mounted
   `TaskEditorView`, `get url` unchanged): **`Resume` (the paused-task equivalent of
   `Activate`) rendered ENABLED on the first render** (`{"disabled": false}`) -
   `12-uom-activate-enabled-same-mount-{1280,375}.png`.

**Verdict: PASS - Defect 3 (Review & Activate staleness, closed at round 6) has NOT regressed
at `2326510b`.** Identical to the round-6 finding: `Activate`/`Resume` reads fresh state within
the same task-editor mount right after a Test succeeds, with no remount needed.

Restored: clicked **Resume** (`POST .../etl-task/resume` 200) to return `unit_of_measure` to
its starting `active` status; `psql` confirms `etl_status = 'active'` afterward.

## Check 3 - Unsaved edit survives Test

On the same `unit_of_measure` task (now `active` again): Source tab -> **Edit** -> changed the
path from `/itembypage` to `/itembypage/` (a curl-verified-200 variant, same one round 6 used)
-> **Test** (real click): succeeded (`POST .../preview` 200, preview grid repopulated) - **the
endpoint-path input still showed the edited `/itembypage/` after the Test completed**
(`agent-browser get value` returned `/itembypage/`, not reseeded back to the saved
`/itembypage`) - `13-unsaved-path-edit-survives-test-{1280,375}.png`. Clicked **Cancel**
afterward to discard the unsaved edit; `psql` confirms the task's real persisted state is
unaffected: `etl_status = 'active'`, `path = '/itembypage'`.

**Verdict: PASS.** Matches the round-6 finding exactly - a Test's post-success refetch/apply
never reseeds an unsaved, in-progress edit.

## Check 4 - Backend + frontend suites, lint

- Backend, full `tests/test_autocount_*.py` glob, run ONCE from `s37/service_backend` (network-
  free, real Postgres lane DB): **1365 passed, 0 failed** (518.97s) at `2326510b`. (Count is
  +2 over round 6's 1363 - `test_autocount_http_task_config.py` gained assertions in the round-7
  fix per `git show 2326510b --stat`.)
- Frontend, `npx vitest run` on every `task-editor-view*.test.tsx`, `source-tab.test.tsx`,
  `activate-tab.test.tsx` under the task editor components dir, plus
  `services/autocount-service.real.test.ts` and `hooks/use-autocount-http.test.ts` (11 files):
  **110 passed, 0 failed** (3.49s). Pre-existing `AnimatePresence`/act() console warnings in
  `source-tab.test.tsx` (filter-formula dialog tests) - not new, not assertion failures, same
  class noted in earlier rounds' reports for other files.
- `npm run lint`: **0 errors**, 239 pre-existing `jsx-a11y` warnings on unrelated files (same
  count/class as rounds 5 and 6) - not new, not blocking.

## Servers left running

- Backend `:8007` (uvicorn, `app.main:app`), pid `18339`, cwd
  `.claude/worktrees/s37/service_backend`, HEAD `2326510b` (restarted this pass).
- Frontend `:3007` (`npx next start -p 3007`), pid `18628`, cwd
  `.claude/worktrees/s37/service_frontend`, serving a fresh `2326510b` prod build (rebuilt this
  pass).
- `agent-browser --session s37-verify7` left running for report authoring; will be closed
  (`agent-browser --session s37-verify7 close`, never `close --all`) once this report is
  filed.
