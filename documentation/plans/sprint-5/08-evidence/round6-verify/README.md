# Round-6 verify - Defect 3 closed + warning link

Lane s37, backend `:8007` (HEAD `90d08bc4`, not restarted this pass - already at `90d08bc4`
per `git rev-parse HEAD` on the running pid's `cwd`), frontend `:3007` (fresh `90d08bc4` prod
build, not rebuilt this pass, same confirmation). DB `foundryx_service_s37` (`auth_throttle`
was already empty, no cleanup needed). Browser: `agent-browser --session s37-verify6`,
headless, real clicks from `/` via the sidebar (never a deep URL). Run date 2026-09-12 (UTC+8
lane clock).

**Tooling note (repeats round-4/round-5 findings, confirmed again this pass):** plain
`click`/CDP mouse dispatch did not open Radix sidebar accordion triggers, tab triggers, or the
row `Actions` dropdown in this session; a full synthetic pointer sequence (`pointerdown` ->
`mousedown` -> `pointerup` -> `mouseup` -> `click`, dispatched via `element.dispatchEvent` at
the element's real `getBoundingClientRect()` center, `pointerType: 'mouse'`) opened every one
reliably. Plain `element.click()` worked for ordinary links/buttons (Test, Save task, Cancel,
Activate, the "Open company" link). Environment/tooling quirk only - still drives the real
component tree, router and permission checks, never a URL shortcut.

Company used: `Mocha 20260912T004004Z` (`d0b58883-6a87-46a3-abf1-0fe5aef8dd55`, `sinkImpl:
logging`) - the SAME logging-sink company used throughout this plan's evidence. Task:
`unit_of_measure` (`autocount_http`, `/itembypage`, `distinctOf` on `value`) - the SAME task
created during the round-5 staleness probe (left in `draft` at `last_preview_at
2026-09-12 12:24:00+09`), reused per the brief rather than creating a new one.

## Check 1 - Defect 3 closed (Activate enabled immediately, same mount) + unsaved-edit survival

Real clicks: Companies list -> `Mocha 20260912T004004Z` row -> Entities tab -> Unit of
measure row's Actions menu -> "Configure source" -> task editor opens on the Source tab (view
mode, path `/itembypage` locked, `Test` button available).

1. **Source tab before** (`01-source-before-{1280,375}.png`): view mode, path
   `/itembypage`, `Test` enabled.
2. **Test** (real click): succeeded - preview grid shows `UNIT`/`DZ`/`SET`. Confirmed via
   `psql`: `last_preview_at` advanced to `2026-09-12 12:52:22+09`.
3. **Edit** -> **Save task** (real click, no field changes): succeeded, "Task saved." toast,
   returns to view mode. No console errors (`agent-browser errors` empty).
4. **Test again** (same Source tab, still mounted, no navigation): succeeded -
   `02-source-tested-twice-1280.png`. Confirmed via `psql`: `last_preview_at` advanced again
   to `2026-09-12 12:52:49+09`, `etl_status` still `draft`.
5. Click **Review & Activate** directly (full pointer-sequence dispatch on the tab trigger,
   same mounted `TaskEditorView`, no route change - `get url` unchanged before/after):
   **`Activate` renders ENABLED immediately**
   (`document.querySelector` matched button `disabled: false`) -
   `03-activate-enabled-same-mount-{1280,375}.png`. **This is Defect 3 CLOSED**: at round 5
   the identical sequence (Test -> Save -> Test again -> Review & Activate, same mount) left
   `Activate` disabled until a fresh route mount; at `90d08bc4` it is enabled on the first
   render of the same mount.
6. **Activate** (real click, after re-entering the task via the real click path a second time
   to also confirm the fresh-mount case still works): status flips **in place** to
   `Pause`/`Run now` with **no navigation, no reload, no console errors**
   (`agent-browser errors` and `console` both empty) -
   `05-activated-status-flip-{1280,375}.png`. Confirmed via `psql`:
   `etl_status = 'active'` for this task immediately after the click.
7. **Unsaved edit survives a Test**: back on the Source tab, clicked **Edit**, changed the
   path from `/itembypage` to `/itembypage/` (a real, curl-verified 200 variant of the same
   endpoint - confirmed independently: `curl -s -o /dev/null -w '%{http_code}' https://
   hapi.sorento.cc.cd/api/db2/itembypage/` -> `200`), clicked **Test**: succeeded (preview
   grid re-populated with `UNIT`/`DZ`/`SET`, `last_preview_at` advanced again in `psql` to
   `2026-09-12 12:57:27+09`, confirming `onHttpPreviewSuccess`'s `reload()` fired) - **the
   input still shows the edited `/itembypage/` after the Test completed, not reseeded back to
   the saved `/itembypage`** - `06-unsaved-path-edit-survives-test-{1280,375}.png`. This is
   exactly the scenario the round-6 fix's own code comment describes (`reload()` only
   replaces `task`; the working `config` reseeds off a `baselineKey` derived from the
   server's `sourceConfig` alone, which did not change since this edit was never saved).
   Clicked **Cancel** afterward to discard the unsaved edit without persisting it; confirmed
   via `psql` the saved `path` is still `/itembypage` (task's real config untouched by this
   probe).

**Verdict: Defect 3 CLOSED at `90d08bc4`.** `Activate` renders enabled on the FIRST render of
the same task-editor mount after Test -> Save -> Test again, with zero navigation/reload
needed; an unsaved path edit is never reseeded by a Test's post-success refetch. No crash, no
console error at any step.

## Check 2 - Warning link ("Open company")

On the same task's Review & Activate tab (a logging-sink company, so the non-blocking sink
warning renders): `document.querySelectorAll('a')` filtered to text `"Open company"` resolved
to `href="/autocount/companies/d0b58883-6a87-46a3-abf1-0fe5aef8dd55"` - the exact company id
of the company under test. Clicked it (`element.click()`): landed on
`http://localhost:3007/autocount/companies/d0b58883-6a87-46a3-abf1-0fe5aef8dd55` (the real
company detail page, confirmed via `get url`), zero console errors -
`04-open-company-link-lands-{1280,375}.png`.

**Verdict: PASS.** The warning's "Open company" link points at `acCompanyHref(task.companyId)`
and real-navigates to the company page.

## Check 3 - Vitest + lint (see report body for the exact commands/output)

- `npx vitest run` on `task-editor-view.http-test-refresh.test.tsx` (3 tests),
  `activate-tab.test.tsx` (31 tests), `services/autocount-service.real.test.ts` (8 tests):
  **42 passed, 0 failed** (1.71s).
- `npm run lint`: **0 errors**, 239 pre-existing `jsx-a11y` warnings on unrelated files (same
  count/class as the round-5 pass) - not new, not blocking.

## Servers left running (per the brief, NOT touched this pass)

- Backend `:8007` (uvicorn, `app.main:app`), pid `81585`, cwd
  `.claude/worktrees/s37/service_backend`, HEAD `90d08bc4`.
- Frontend `:3007` (`npx next start -p 3007`), pid `9149`, cwd
  `.claude/worktrees/s37/service_frontend`, serving the fresh `90d08bc4` prod build.
- `agent-browser --session s37-verify6` closed at the end of this pass (not `close --all`).
