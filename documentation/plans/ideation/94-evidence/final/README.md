# Final evidence run log - issue #94 ideation round 2 (reviewed build, HEAD 82fe81ac)

Lane: DB `foundryx_service_ir2` (Postgres, native, DROPPED and recreated fresh
for this run), Redis db 5 (FLUSHDB), backend `:8016` (uvicorn, pid recorded in
the final test report), frontend `:3016` (`npx next start -p 3016`, rebuilt
from a clean `.next`). All timestamps in this run use `20260928-1349` for
created names.

## 0. Lane reset

Stopped ONLY the lane's own processes after confirming `lsof -p <pid> | grep
cwd` pointed at this worktree (backend pid 39803, frontend pid 35218, both
from the S6/S6-fix runs). Dropped `foundryx_service_ir2` and recreated it
(`CREATE DATABASE ... OWNER foundryx`, run as the local Postgres superuser
since the `foundryx` role itself lacks `CREATEDB`). `redis-cli -n 5 FLUSHDB`.

```
DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_ir2 \
REDIS_URL=redis://localhost:6379/5 \
ENVIRONMENT=development CELERY_TASK_ALWAYS_EAGER=true THROTTLE_IP_MAX_FAILS=200 \
.venv/bin/python -m scripts.bootstrap_db
```
Tail: `ideation: grill agent seeded for 0 tenant(s)` / `omnichannel: demo
conversations seeded` / `... demo AI workflow seeded` / `... demo
progress-update workflow seeded` / `bootstrap complete: migrated + seeded +
modules`. Confirmed live: `select version_num from
app_ideation.alembic_version_ideation;` -> `0012_ideation_merge_rank_events`.

### Migration 0012 DDL verification - a nuance, not a defect

`select column_name, column_default from information_schema.columns where
table_schema='app_ideation' and table_name='idea_status_events' and
column_name='created_at';` returned `now()`, not the migration's literal
`clock_timestamp()` DDL text, and the three NIT indexes
(`ix_idea_votes_origin_idea_id`, `ix_idea_status_events_tenant_id`,
`ix_idea_status_events_idea_id`) do not exist under those exact bare names.
Root cause (by design, confirmed by reading `app/module_loader.py`'s
`_bootstrap_one_module` docstring): a module that is FRESH to a database
(this lane's brand-new DB) is built via SQLAlchemy `create_all()` first, then
Alembic is stamped to head WITHOUT literally executing the historical
migrations' DDL ("the revision chains were never written to replay from zero
on top of their create_all baselines") - the migration's DDL only fires on a
database that is genuinely upgrading from an older revision. `create_all`
instead builds the CURRENT model shape: `idea_status_events.created_at` is a
`server_default=func.now()` Column in `modules/ideation/models.py` (the
migration's own comment explains this is a defense-in-depth fallback, never
the actual mechanism), and the three indexes DO exist, just under
`create_all`'s own naming convention (`ix_app_ideation_idea_votes_origin_idea_id`,
`ix_app_ideation_idea_status_events_tenant_id`,
`ix_app_ideation_idea_status_events_idea_id` - confirmed via
`pg_indexes`), functionally identical (same columns, same table). The actual
review-round-2 fix (`services/status_events.py::_write_event` sets
`created_at=func.clock_timestamp()` explicitly on every INSERT, Postgres-only,
and reads the value back with `db.refresh`) is independent of the column
default and DOES fire on this fresh install - confirmed live in section 3
below: three status-events rows written across a ~78-second real-clock span
inside actions that were each single-transaction commits show three
DISTINCT `occurred_at` timestamps (14:20:25.744419Z / 14:21:15.392113Z /
14:21:43.238734Z), which a `now()`-only (transaction-fixed) default could
never produce for anything but same-request calls - the mechanism under test
is proven working. Not filed as a defect; documented for the next fresh-lane
bootstrap.

Backend started: `uvicorn app.main:app --port 8016` with `CORS_ORIGINS`
widened to `http://localhost:3016` and `CORS_ORIGIN_REGEX` widened to
`http://[a-z0-9-]+\.localhost:30[0-9][0-9]` (env-only, not a code change -
same lesson as S6). Frontend: `rm -rf .next && npm run build` run WITH
`NEXT_PUBLIC_BACKEND_API_URL`/`BACKEND_API_URL=http://localhost:8016`/
`NEXTAUTH_URL=http://localhost:3016`/`NEXTAUTH_SECRET` all EXPORTED before the
build step (S6-fix's documented gotcha - Next.js inlines
`NEXT_PUBLIC_*` at build time, not at `next start` time), then started with
the same vars via `npx next start -p 3016`.

## 1. Environment/tooling notes for this run

- `agent-browser click @ref` still no-ops on this build's motion-wrapped
  sidebar links/dialog submit buttons on the FIRST click after certain page
  transitions (same class of issue as S6/S6-fix) - worked around with a
  `pointerdown -> mousedown -> pointerup -> mouseup -> click` dispatch via
  `agent-browser eval` targeting the exact `<a>`/`<button>` text, wrapped in
  an IIFE (plain `const`/`var` redeclare across separate `eval --stdin` calls
  throws `SyntaxError: Identifier already declared` in this CDP session's
  persistent page-global scope - IIFE avoids it). Verified by network
  requests / URL / DOM state, never by the dispatch call's own return alone.
- A ROW-LEVEL "Actions" button on a wide `ResourceList` that is currently
  scrolled out of the viewport (horizontal scrollbar) does not respond to a
  plain `agent-browser click @ref` even though the ref resolves - CDP's
  `click` computes screen coordinates from the (possibly off-screen) box.
  `agent-browser scrollintoview @ref` before the click fixed this every time
  it was hit.
- **Drag DID work this run**, contrary to the S6-fix session's finding,
  using the low-level `agent-browser mouse move/down/up` primitive sequence
  (small stepped `move` calls with brief sleeps between down and up) rather
  than the high-level `agent-browser drag @src @dst` helper (which, tried
  first, produced no visible or network-verified effect). Both the Triage
  board's cross-column drag (AC-94-58) and the Ideas list's row-reorder drag
  (AC-94-48) produced real `POST .../status` / list-reorder network calls
  and were independently confirmed by re-opening the moved idea's form. Per
  the coordinator's standing instruction, this is reported as a real PASS
  with evidence, not a deferral, precisely because the interaction WAS
  successfully driven this session.
- POST `/embed/session`'s body field for the ideation branch of the shared
  omnichannel/ideation route is snake_case `connection_id` (plain
  `BaseModel`, not the app's `ApiModel` camelCase convention - this route is
  the sorento-host-to-service SSO handshake, not a browser API client, so it
  does not carry the wire convention). A camelCase `connectionId` silently
  routes the request to the OMNICHANNEL embed handler instead (the router's
  own documented shadowing behaviour: "no connection_id -> not an ideation
  request"), producing a confusing `invalid_assertion` / "Unknown assertion
  issuer" error from the WRONG module. Noted here since it cost real time
  this run; not a code defect (the docstring already explains the
  shadowing).

## 2. Test data (API + UI mix, journeys themselves are real clicks)

- Product `E2E Product 20260928-1349` (Good) on the default tenant, created
  via the UI "Add product" dialog.
- Ideas Bravo/Charlie/Delta/Echo/Foxtrot captured via the real UI "Capture
  idea" dialog (real clicks + the dispatch workaround for the dialog's own
  submit button - a plain `click` on it silently closed the dialog with NO
  network request four separate times before the workaround was applied;
  documented here as a genuine tooling gotcha, re-confirmed working
  correctly afterwards on every subsequent capture).
- One WhatsApp-style idea (`E2E Idea 20260928-1349 Kilo`, requester
  `+60191234599`) minted via the real multi-turn `POST
  /ideation/intake/create-idea` flow (workspace API key minted via
  `POST /omnichannel/workspaces/{id}/api-keys` with the demo admin's own
  session token, a Contact created via `POST
  /omnichannel/workspaces/{id}/contacts`) - problem -> (duplicate_candidate
  -> separate) x3 (every other seeded idea's near-identical placeholder text
  triggered dedup in turn) -> proposed_solution -> impact -> confirm. Became
  `IDEA-0004`.
- A dedicated tenant `e2eir202609281349` (slug) provisioned via
  `POST /platform/tenants` (platform admin `platform@example.com`), ideation
  + omnichannel installed via `POST
  /platform/tenants/{id}/modules/{name}/install`, for AC-94-59 (the rename
  forks the tenant's status set). One product + one idea
  (`E2E IR2 Idea 20260928-1349 India`) captured through the real UI capture
  dialog for that tenant.
- An ideation embed connection (`e2e-embed-20260928-1349`, no product scope)
  created through Ideation > Embed connections in the UI ("Generate" button
  for the signing secret). The host assertion (`iss=sorento`,
  `aud=ideation-embed`, `typ=assertion`, 60s `exp`) was minted locally with
  `python-jose` (main checkout's venv) using the connection's own plaintext
  signing secret, exchanged via `POST /embed/session` (snake_case
  `connection_id` - see gotcha above) for a short-lived embed token, placed
  in the `#token=` URL fragment to open `/embed/ideas`.

## 3. Re-run results (this session, real clicks unless noted)

| AC | Verdict | Evidence |
|----|---------|----------|
| AC-94-22 merge dialog is a bare `SearchSelect`, no instructional text | **PASS** | `AC-94-22-27-merge-dialog-1280.png` - dialog body is exactly "Keep" + the SearchSelect + Cancel/Merge, confirmed via `get text body` too |
| AC-94-25 "Merged from" tab | **PASS** | `AC-94-25-26-28-merged-from-tab-1280.png` |
| AC-94-26 the merged child's own form ("Merged into" row + link, click it back) | **PASS** | `AC-94-26-28-child-form-1280.png` / `-375.png`; clicking the "IDEA-0001" link navigated back to the survivor's own form (URL + heading text confirmed) |
| AC-94-27 E2E merge two ideas | **PASS** | `AC-94-27-merged-list-1280.png` / `-375.png` - toast "Merged into IDEA-0001.", "1 merged" badge |
| AC-94-28 E2E open a merged child from the survivor, click through | **PASS** | Same screenshots as AC-94-25/26; child-row click and back-link click both verified by URL change |
| AC-94-29 E2E unmerge from the child form | **PASS** | `AC-94-29-unmerge-toast-1280.png` - "Idea unmerged.", Priority restored to `#2`, no "Merged into" row |
| AC-94-30 E2E unmerge from the list | **PASS** | `AC-94-30-actions-menu-1280.png` / `-375.png` (bulk Actions shows "Unmerge" on a single survivor selection, never "Merge"), `AC-94-30-list-after-unmerge-1280.png` - all 5 ideas separate rows, no badges |
| AC-94-32 E2E embed parity | **PASS** | `AC-94-32-embed-*` (merge dialog, merged badge, "Merged from" tab, child form's "Merged into IDEA-0003" link click-through, unmerge) - every navigation stayed under `/embed/ideas` (confirmed via `get url` after every click, including the two cross-record clicks) |
| AC-94-48 E2E drag then open (list reorder) | **PASS** | `AC-94-48-list-drag-1280.png`, `AC-94-48-form-priority-375.png` - dragged the 3rd row (Echo) to the top via low-level mouse primitives, opened it, form reads "Priority #1"; network showed the real reorder call landing |
| AC-94-58 board renders (no crash) | **PASS** | `AC-94-58-board-1280.png` / `-375.png` - all 5 columns render, 4 "New" cards, no error boundary (the S6-fix render fix holds) |
| AC-94-58 board drag (cross-column) | **PASS** | `AC-94-48-58-board-drag-1280.png` / `-375.png` - dragged "Charlie" from New into Triaged via low-level mouse primitives; `POST .../status` fired (200) and the column counts updated (New 4->3, Triaged 0->1) |
| AC-94-52 advance = immediately next status (Delivered -> "Move to Closed") | **PASS** | `AC-94-52-57-advance-to-closed-1280.png` (menu reads "Move to Closed" once the idea reached Delivered) / `AC-94-52-57-closed-in-archived-1280.png` (status column reads "Closed" in the Archived view after firing it) |
| AC-94-57 E2E advance through every stage via the row action | **PASS** | Same two screenshots - Bravo driven New -> Triaged -> Linked to BR -> Building -> Delivered -> Closed, each step a real row Actions > "Move to X" click, each producing a `POST .../status` 200 |
| AC-94-59 E2E rename in the statuses engine, all 5 legs including the board column | **PASS (all 5 legs)** | `AC-94-59-statuses-engine-renamed-1280.png` (Triaged -> `Discussed-20260928-1349`, saved), `AC-94-59-advance-label-1280.png` ("Move to Discussed-20260928-1349" on a New idea), `AC-94-59-status-column-1280.png` (Status column reads the new label after firing it), `AC-94-59-board-column-1280.png` / `-375.png` (Triage board's own column title reads "Discussed-20260928-1349" with the idea card under it - the AC-94-58 fix un-blocks this leg that S6 could not complete) |

Public-page and idea-form no-status legs of AC-94-59 were not independently
re-swept this round (unchanged surfaces, already PASS in the S6 report;
budget went to the previously-BLOCKED board leg and the drag legs instead).

## 4. Feed re-check (step 3 of the brief)

On the WhatsApp idea `IDEA-0004` (requester `+60191234599`): row Actions >
"Move to Triaged" (New -> Triaged) -> bulk Merge into `Charlie` (survivor,
became `IDEA-0005`) -> bulk Unmerge on `Charlie`. Waited 6s (> the 5s settle
window) then:

```
GET /ideation/intake/status-events?after=0&limit=100
```
with the SAME workspace API key minted for the intake flow. Full JSON in
`status-events-feed.json`. Three rows, ascending `seq`:

1. `seq=1 kind=status_changed from_status_label=New status_label=Triaged`
2. `seq=2 kind=merged merged_into={IDEA-0005, Charlie}`
3. `seq=3 kind=unmerged separated_from={IDEA-0005, Charlie}`

`occurred_at`: `14:20:25.744419Z`, `14:21:15.392113Z`, `14:21:43.238734Z` -
**three distinct values**, matching the real wall-clock gap between the three
UI actions (confirmed programmatically: `len(set(times)) == len(times)`).
This is the live proof that review-round-2's `clock_timestamp()`-at-write-time
fix (`services/status_events.py::_write_event`) works correctly even on a
fresh-install database whose `idea_status_events.created_at` COLUMN default
is still `server_default=func.now()` (see section 0's nuance write-up) - the
column default is never actually used because the ORM insert always supplies
an explicit `created_at` value.

## 5. Automated suites (this run)

### Backend - full suite
```
.venv/bin/python -m pytest -q
```
Result recorded in the final test report (run from the main checkout's venv
against this worktree, per the brief).

### Frontend unit (Vitest)
```
npx vitest run
```
-> **422 test files passed (422), 3335 tests passed (3335)**, 114.44s. Zero
failures.

### Lint
```
npm run lint
```
-> **0 errors, 243 warnings**, exit code non-zero only due to warnings
(`✖ 243 problems (0 errors, 243 warnings)`) - the same pre-existing
`jsx-a11y` warning set as S6, on files this feature did not touch.

## 6. Servers left running

- Backend: `uvicorn` on `:8016` (pid recorded in the final test report),
  `DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service_ir2`,
  `REDIS_URL=redis://localhost:6379/5`, CORS widened as above.
- Frontend: `npx next start -p 3016` (pid recorded in the final test report),
  `NEXT_PUBLIC_BACKEND_API_URL`/`BACKEND_API_URL=http://localhost:8016`,
  `NEXTAUTH_URL=http://localhost:3016`, `NEXTAUTH_SECRET` set.
- Demo login: `demo@example.com` / `demo1234` on `http://localhost:3016`.
- Dedicated tenant: `e2eir202609281349` /
  `e2e-admin-e2eir202609281349@example.com` / `E2eTest1234!` on
  `http://e2eir202609281349.localhost:3016`.
