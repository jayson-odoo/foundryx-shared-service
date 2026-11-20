# Round-8 verify - Defect 5 closed (Cancel re-derives the previewed pair)

Lane s37, backend `:8007` (HEAD `c1ea9d47`, containing round-8 code commit `88106ace`;
restarted this pass: killed pid `18339` after confirming its `cwd` was
`s37/service_backend`, started `.venv/bin/python -m uvicorn app.main:app --port 8007` from
`service_backend/`, new pid `28393`). Frontend `:3007` (same HEAD, rebuilt this pass: killed
pid `18628` after confirming its `cwd` was `s37/service_frontend`, `rm -rf .next && npm run
build` (clean, exit 0), `npx next start -p 3007` (never `npm start`), new pid `28718`). DB
`foundryx_service_s37`. Browser: `agent-browser --session s37-verify8`, headless, real clicks
from `/` via the sidebar (never a deep URL). Run date 2026-09-12.

**Tooling note (repeats round-4..7 findings, confirmed again this pass):** plain
`click`/CDP mouse dispatch did not open the sidebar `AutoCount` accordion, the "Companies"
sidebar link, the company row link, or a row's `Actions` dropdown (open AND item-select both)
in this session; a full synthetic pointer sequence (`pointerdown` -> `mousedown` -> `pointerup`
-> `mouseup` -> `click`, dispatched via `element.dispatchEvent` at the element's real
`getBoundingClientRect()` center, `pointerType: 'mouse'`) opened/selected every one reliably.
Plain `agent-browser click`/`fill` worked for ordinary buttons/tabs/inputs once the page/menu
had already landed via the real-dispatch method (Entities tab trigger, task-editor Edit/Test/
Cancel/Save/Actions header button, the header Actions menu's own items). Environment/tooling
quirk only - still drives the real component tree, router and permission checks, never a URL
shortcut.

Company used: `Mocha 20260912T004004Z` (`d0b58883-6a87-46a3-abf1-0fe5aef8dd55`, `sinkImpl:
logging`) - the SAME logging-sink company used throughout this plan's evidence. Task used:
`warehouse` (`autocount_http`, saved path `/location`, was `active` at the start of this pass,
restored to `active`/`/location` per round 7).

## Check 1 - Defect 5 closed (Cancel re-derives the previewed pair)

Real clicks: sidebar `AutoCount` -> `Companies` -> `Mocha 20260912T004004Z` row -> `Entities`
tab -> Warehouse row's `Actions` menu -> `Configure source` -> task editor opens on the Source
tab (view mode, path `/location`, task `active`).

1. **Warehouse before** (`01-warehouse-before-{1280,375}.png`): view mode, path `/location`,
   `Test` enabled, task active.
2. Header `Actions` -> **Pause** (real click): succeeded, confirmed via `psql`
   (`etl_status = 'paused'`), zero console errors.
3. **Edit** -> changed the path field to `/location/` (a curl-verified-200 trailing-slash
   variant, the same path round 7 used) -> **Test** (real click): succeeded (`POST
   /autocount/http/preview` 200); `Save task` read `{"disabled": false}` immediately
   (`02-edited-path-tested-save-enabled-1280.png`).
4. **Cancel** (real click): the dirty-guard `AlertDialog` appeared, "Discard changes?"
   (`03-discard-changes-dialog-1280.png`) -> **Discard changes** (real click): succeeded, zero
   console errors, back to VIEW mode showing the original path `/location` (never the edited,
   discarded `/location/`) - `04-after-discard-read-mode-location-{1280,375}.png`.
5. **Edit again** (real click, second Edit entry, NO new Test this time) -> changed the path
   field to `/location/` then immediately back to `/location` (an unrelated-field-equivalent
   dirty/undirty round trip, per the check's own wording "change an unrelated field or the
   path back and forth so the form is dirty"):
   - After typing `/location/` (differs from the re-derived previewed pair `/location`):
     `Save task` correctly read `{"disabled": true}` (needs a Test at the NEW value) - matches
     the documented gate, not a regression.
   - After typing it back to `/location` (matches the baseline/previewed pair exactly, NO new
     Test call was made in this Edit session): `Save task` read **`{"disabled": false}`**
     immediately - `05-dirty-form-save-enabled-no-new-test-{1280,375}.png`. **This is the
     round-8 fix under test**: at the pre-round-8 HEAD, `onCancel` left `httpPreviewedFor`
     pointed at whatever the LAST Test inside the discarded edit had proved (`/location/`),
     so re-entering Edit and typing the SAVED, already-proved path (`/location`) would have
     found the previewed pair mismatched (`/location/` != `/location`) and kept `Save task`
     disabled, forcing one redundant Test on a value the server had already verified. The
     round-8 fix's `onCancel` now re-derives `httpPreviewedFor` from the baseline task
     (`task.resultColumns.length > 0 && ...` guard) BEFORE `draft.reset()`, so the very next
     Edit session starts with the previewed pair pointed at the SAVED config, not the
     discarded edit's last-tested one. `agent-browser errors`/`console` both empty throughout
     steps 2-5.
6. **Cancel** (real click, no dialog this time - the path was typed back to its exact
   baseline value, so the draft was not dirty by the time Cancel was clicked): returned
   straight to view mode, `psql` confirms the task was untouched by the whole probe
   (`etl_status = 'paused'`, `path = '/location'`).
7. Header `Actions` -> **Resume** (real click): flipped the task back to `active` in place,
   zero console errors, confirmed via `psql` (`etl_status = 'active'`, `path = '/location'`)
   - `06-warehouse-restored-active-1280.png`. Task fully restored to its exact starting state.

**Verdict: Defect 5 (Cancel leaves a stale previewed pair, forcing a redundant Test on the
already-proved saved config) CLOSED at `88106ace`.** Save is enabled the moment a re-entered
Edit session's field values match the SAVED, already-Tested config, with NO new Test call
required; the fix does not regress the "Save disabled until Tested at a genuinely NEW value"
gate (step 5's first sub-check). Zero console errors across the whole sequence; the `warehouse`
task was restored to its exact pre-check state (`active`, `/location`) afterward.

## Check 2 - Preview 404 mapping (API-level, curl)

`POST /auth/login` on `:8007` with `demo@example.com`/`demo1234` -> bearer token. `POST
/autocount/http/preview` with a RANDOM UUID `companyId` (`15df0e81-c4fa-4e7a-9431-5f7c3009637d`,
never a real row), a real no-auth connectionId (`3c9c43b8-08ec-4bc4-a87b-2805a77adf6f`, "Mocha
REST"), `path: "/location"`, `entityType: "warehouse"`:

```
HTTP_STATUS:404
{"detail":"That AutoCount company was not found."}
```

Backend log for the request: a single tenant-scoped `SELECT ... FROM app_autocount.ac_company
WHERE ... tenant_id = %(tenant_id_1)s AND id = %(id_1)s` (the random UUID), then `ROLLBACK`,
then `INFO: 127.0.0.1 - "POST /autocount/http/preview HTTP/1.1" 404 Not Found` - no traceback,
no 500. **Verdict: PASS.** The round-8 fix (`preview_http` now routes `AutocountServiceError`
through the same `_raise` translator `routers/companies.py` uses) maps an other-tenant/unknown
`companyId` to a clean 404 JSON body, never a bare 500.

## Suites

- Backend, the coordinator's named file set: `.venv/bin/python -m pytest -q
  tests/test_autocount_http_task_config.py tests/test_autocount_http_lifecycle.py
  tests/test_autocount_etl_routes.py` -> **67 passed, 0 failed** (58.02s; only
  `StarletteDeprecationWarning`/SQLAlchemy date-adapter warnings, none new).
- Frontend, all files named by the brief (11 files): `task-editor-view.http-preset-dirty.
  test.tsx`, `source-tab.test.tsx`, `task-editor-view.save-sequencing.test.tsx`,
  `task-editor-view.locked-connection.test.tsx`, `task-editor-view.test.tsx`,
  `task-editor-view.http-save-gate.test.tsx`, `task-editor-view.http-test-refresh.test.tsx`,
  `task-editor-view.http-source-badge.test.tsx`, `services/autocount-service.mock.http.
  test.ts`, `services/autocount-service.mock.test.ts`, `services/autocount-service.real.
  test.ts` -> **124 passed, 0 failed** (15.10s; 2 pre-existing "not wrapped in act()"
  `AnimatePresence` stderr notices in `source-tab.test.tsx`, not new, that file's own tests
  all pass).
- `npm run lint` -> **0 errors** (239 pre-existing `jsx-a11y` warnings on unrelated files,
  the same count as rounds 5-7, not new).

## Servers left running

- Backend `:8007` (uvicorn, `app.main:app`) at HEAD `c1ea9d47` (pid `28393`, cwd
  `s37/service_backend`, RESTARTED for this pass - killed pid `18339` after confirming its
  `cwd`).
- Frontend `:3007` (`npx next start -p 3007`, pid `28718`) serving a fresh `c1ea9d47` prod
  build (REBUILT for this pass - `rm -rf .next && npm run build`, clean; killed pid `18628`
  after confirming its `cwd`).
- `agent-browser --session s37-verify8` closed at the end of this pass (plain `close`, never
  `close --all`).
