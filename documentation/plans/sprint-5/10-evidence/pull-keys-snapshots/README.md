# Run 4 (HEAD 17dc2c61, 2026-09-20 UTC, approx 13:00-13:15Z) - re-verify Revoke end to end + the grace-window owner question + AC-10-85 bonus check

Lane: backend `:8009`, frontend `:3009` (already running from the same session's `pull-setup`/
`pull-stock`/`flip-push` work - no restart between runs, `rm -rf .next && npm run build` had
already run once this session). DB `foundryx_service_s40`. Tenant/user: `default`,
`demo@example.com` (Admin). Scope: full Revoke journey at BOTH viewports (Run 3 only covered
375px + a single 1280px list screenshot without exercising Revoke itself at 1280px), plus the
owner's own open question from the brief ("record whether the key still works DURING the grace
window") and the AC-10-85 bonus connection-fields check.

## Revoke, end to end, both viewports - now fully working (Run 3's 404 is fixed)

Run 3 found Revoke reachable via a real `ActionMenu` but every attempt 404'd
(`autocount_pull_api_key 'pull-key-active' not found.`) because the Pull page's list data was
still the Phase-1 mock overlay while the mutation correctly targeted the real backend - a pure
read/write mismatch, not a backend bug (see Run 3's own root-cause writeup below, still accurate
history). That gap is now closed: the phase-2 swap landed (`994ca215`, an ancestor of this HEAD),
so the Keys/Snapshots list IS the real backend data.

This run issued its OWN fresh, timestamped keys (`S6 pull-setup 20260920T124430Z` at 375px,
`AC-10-50 pull-setup 1280 20260920T131041Z` at 1280px - see `pull-setup/README.md` for the Issue
key journey) and revoked each one plus every leftover key found in the Keys list at session start
(residue from earlier tester sessions this lane: `AC-10-50 pull-setup 1280 20260920T105051Z`,
`AC-10-50 pull-setup 20260920T103828Z`, `S6 live replay 20260920T095117Z`, plus `S6 flip-push
probe 20260920T130458Z` issued and consumed by `flip-push/README.md`'s own journey) - 6 keys
revoked in total this run, leaving the Keys list clean of active residue.

**375px:** Keys segment -> target row's "..." **Actions** menu (required `scrollintoview` to reach
the Actions column, off-screen by default) -> **Revoke** menuitem.
`run4-01-key-actions-menu-375.png`. Clicking it immediately shows a deferred-action toast
**"Revoking in 9s / Cancel"** (no error this time - contrast Run 3's 404).
`run4-02-revoke-grace-window-375.png`. After the countdown, the toast resolves to "Key revoked."
and the row's Status column flips to `Revoked`. `run4-03-after-error-row-state-375.png` (filename
kept from the original brief naming; this run's capture shows the FINAL post-revoke row state, not
an error - Run 3's error is fully retired). A `curl GET .../snapshots/{id}` using the now-revoked
key returns `401 {"code":"INVALID_API_KEY","message":"Missing, malformed, unknown or revoked
key."}`. **PASS.**

**1280px:** identical journey, independent key. `run4-04-key-actions-menu-1280.png` (Actions menu
open), `run4-05-revoke-grace-window-1280.png` ("Revoking in 9s" toast), `run4-06-after-revoke-row-
state-1280.png` (Status `Revoked`, confirmed via `get text`: 6 `Revoked` rows total by the end of
this run, one per key). A second `curl GET .../snapshots/{id}` using THIS revoked key also returns
`401 INVALID_API_KEY`. **PASS.**

## The grace-window owner question, answered: YES, a key still works during the 9s countdown

While revoking the FIRST key of this run (375px pass), a `curl POST .../snapshots
{"companyCode":"SRT","entity":"products"}` using that SAME key was issued deliberately DURING the
visible "Revoking in 9s" countdown (originally intended only to probe whether a revoked key could
still reach the endpoint, before realising the revoke had not yet actually committed). The call
succeeded: `HTTP 202 {"snapshotId":"b7b1e8de-...","status":"ready",...}` - the gateway accepted a
brand-new build request using the key. Cross-checked against the DB immediately after: the key's
`ac_pull_api_key.revoked_at` timestamp is `2026-09-20 21:57:46.817+09`, while the snapshot row this
same call created carries `created_at 2026-09-20 21:57:46.003+09` - **the gateway accepted the
request ~0.8 SECONDS BEFORE the revoke actually committed to the database.** This confirms
definitively: the deferred-action countdown is not merely a UI affordance layered on top of an
already-committed mutation - the ACTUAL backend revoke does not fire until the countdown
completes (or would have been cancelled entirely by clicking the toast's own **Cancel**). A key
issued moments before a Revoke click remains fully live and usable for the full ~9 second grace
window. This is not filed as a defect (it is consistent with, and arguably the whole point of, a
deferred/undoable action), but it IS a fact the plan owner should know when reasoning about how
fast a compromised-key revocation actually takes effect - flagged as a design note in
`pull-setup/README.md` Finding B as well.

## AC-10-85 bonus check (1280 only, cross-referenced from `pull-setup/README.md` Finding C)

Settings -> Integrations -> the lane's open AutoCount connection (`S40 db1 SRT ...`) -> Edit:
`Page size` and `Request timeout (seconds)` number fields ARE present, correctly gated to render
only for an open (`auth: none`) connection. Screenshot lives in `pull-setup/28-connection-sizing-
fields-1280.png` (not duplicated here). Both fields render blank with no default-value placeholder
- see `pull-setup/README.md` Finding C for the full writeup. No changes saved (Cancel clicked).
**PASS on presence + gating, minor UX finding on the missing placeholder.**

## AC verdict (Run 4)

- **AC-10-38 [FE] Revoke:** **PASS**, fully, both viewports - the Phase-2 swap (already landed
  before this HEAD) closes the gap Run 3 found; Revoke now round-trips against the real backend
  end to end (menu -> grace countdown -> commit -> `401` on the revoked key) with no defects.
- Owner question (grace-window key validity): **answered - YES, the key remains valid for the
  full countdown window**, documented above and in `pull-setup/README.md` Finding B.
- **AC-10-85 [BE]/[FE] bonus:** **PASS** on presence/gating; minor UX finding (Finding C in
  `pull-setup/README.md`) on the missing default placeholder, not a hard fail.

---

# Run 3 (HEAD 29c02190, 2026-09-20 UTC) - re-verify SF8 (Revoke reachability), AC-10-38

Lane: backend `:8009`, frontend `:3009` (fresh `rm -rf .next && npm run build` + `npx next start
-p 3009`), DB `foundryx_service_s40`. Tenant/user: `default`, `demo@example.com` (Admin). Scope:
ONLY the Revoke action re-run requested for this pass (SF8 from round 3 review) - the rest of this
file's Run 2 findings (Issue-key dialog, Build-snapshot picker, snapshot detail) were NOT
re-exercised here and their verdicts stand as last recorded below.

## Revoke IS now reachable (run 2's "no Revoke action" gap is fixed) - but the commit 404s

Run 2 found NO way to trigger Revoke at all (missing `ActionMenu` column in
`use-pull-list-config.tsx`). On this HEAD that gap is closed: the Keys segment's row now carries a
working "..." **Actions** menu with a single, correctly-styled destructive **Revoke** menuitem,
confirmed by real clicks (open Actions -> menu renders "Revoke" -> click). Screenshots
`run3-01-key-actions-menu-375.png` (375px, menu open over the "Sorento production" row),
`run3-04-pull-page-1280.png` (1280px Keys table before revoking, "Sorento production" = Active,
"Old staging key" = Revoked).

Clicking **Revoke** immediately surfaces an error toast: **`autocount_pull_api_key 'pull-key-
active' not found.`** - at BOTH 375px (`run3-02-revoke-grace-window-375.png`) and 1280px
(`run3-05-revoke-error-1280.png`). The row's Status stays `Active` afterward (no optimistic update
applied or it was rolled back) - screenshot `run3-03-after-error-row-state-375.png`. Reproduced
identically twice (once per viewport), same exact error text both times.

**Root cause, confirmed by reading the source (read-only, no edits made):** the Pull page's list
DATA still comes entirely from the frontend Phase-1 mock overlay
(`services/autocount-service.mock.ts`, `withPhase1PullMock` - its own top comment still reads
"Only the human-invoked pull surface ... has no backend yet"), which seeds the Keys table with two
fixture rows whose ids are the LITERAL strings `pull-key-active` / `pull-key-revoked` bound to a
fixture company id `ac-pull-fixture-company` (rendered as "Pull demo (mock)"). Meanwhile the real
backend for this exact surface IS fully implemented and mounted (confirmed via `GET /openapi.json`
on this lane's running `:8009`): `GET/POST /autocount/pull/keys`, `POST
/autocount/pull/keys/{key_id}/revoke`, `GET/POST /autocount/pull/snapshots`, plus the public
gateway `/api/v1/autocount/snapshots...` - all present and routable. A direct authenticated probe
confirms the real DB has ZERO pull keys and ONE real company (`Sorento SRT S40`, not "Pull demo
(mock)"): `GET /autocount/pull/keys` -> `[]` (HTTP 200), `GET /autocount/companies` -> 1 row.

The Revoke action itself is wired correctly to the CORE deferred-action engine exactly as AC-10-38
specifies (`use-pull-list-config.tsx`: `deferred: { actionKey: 'autocount_pull_api_key.revoke',
entityType: 'autocount_pull_api_key' }`, `getEntityId: (row) => row.id` - explicitly commented
"the deferred-actions engine parks against the BACKEND row id, never the shell's own prefixed
`getRowId`"). That engine commits straight to the REAL backend's
`POST /autocount/pull/keys/{id}/revoke` using whatever id the row carries. Since the row's id is
the MOCK's fixture string `pull-key-active` and no such row exists in the real `ac_pull_api_key`
table, the real backend correctly 404s with exactly the message observed
(`autocount_pull_api_key 'pull-key-active' not found.` matches this codebase's standard
"`<table> '<id>' not found.`" 404 phrasing). **This is not a backend bug** - Group C/D's backend
(AC-10-18..38) is fully built and behaving correctly against real data; the gap is purely that the
Pull page's LIST READS were never swapped from `withPhase1PullMock` to `realAutocountService`
(the Phase 2 swap `autocount-service.ts` already documents as pending: "Phase 2 swap = `export
const autocountService = realAutocountService`"), so every read/write pairing on this page is now
internally inconsistent - reads show mock fixture rows, but the ONE mutation this AC requires
(Revoke, via the core deferred-action engine) always targets the real backend by design and can
never find a mock row's id there. The same mismatch would affect **Issue key** and **Build
snapshot** the moment their mutations also target real ids that a mock-sourced picker could offer
(see Run 2's Issue-key finding below, which is a different symptom of the same underlying gap).

## AC verdict (Run 3, Revoke re-run only)

- **AC-10-38 [FE] Revoke:** STILL FAIL, but the FAILURE MODE HAS CHANGED and NARROWED since Run 2:
  Revoke is now reachable via a real `ActionMenu` (Run 2's gap is fixed), the deferred-action
  commit correctly targets the real backend per the AC's own wording ("the server-side target of
  the deferred-action commit"), and the real backend correctly rejects an unknown id - but the
  action can never succeed in this build because the row ids it operates on come from mock fixture
  data that was never persisted server-side. The remaining fix is the Phase 2 swap of the Pull
  page's list source (`autocountService` binding) from `withPhase1PullMock` to
  `realAutocountService`, not a further Revoke-specific change.

---

# Run 2 (HEAD 7618bb33, 2026-09-20 UTC) - re-verify AC-10-38, AC-10-48, AC-10-49

Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`. Tenant/user: `default`,
`demo@example.com` (Admin). Sidebar AutoCount -> Pull (synthetic dispatch; real click was a
no-op, same CDP flake as the other two READMEs).

## Fixture fix confirmed (AC-10-48)

Keys segment on load: "Sorento production" (Active) + "Old staging key" (Revoked), both scoped
to a fixture company "Pull demo (mock)" - matches the coder's fix commit `6ec3f258`. Screenshot
`run2-01-pull-keys-1280.png`. Snapshots segment: 5 rows - Product Building, Stock balance Ready
(12,133), Product Ready (11,830), Product Failed, Product Ready (11,812) - every AC-10-48 state
(building/ready/failed, product + stock) now reachable. Screenshot
`run2-08-snapshots-segment-1280.png`. The Companies list (`/autocount/companies`) also now shows
"Pull demo (mock)" as a real row, since the fixture is appended to `listCompanies`.

## Defect 3 investigation: Issue-key dialog "resets to blank" (AC-10-38)

**Root cause found - this was a TEST-SCRIPT bug in BOTH run 1 and this run's first three
attempts, not an application defect.** The Pull page renders TWO buttons with the identical
accessible name "Issue key": the `ResourceList` header's own CREATE button (opens a fresh,
blank dialog) and the dialog's SUBMIT button (`closest('[role=dialog]')` true). A selector that
matches "the first button whose text is 'Issue key'" - which is what both a plain `find text
"Issue key" click` and an un-scoped synthetic-dispatch helper do - hits the OUTER button every
time, even while the dialog is already open. Re-clicking the outer button does not resubmit the
form; it fires `setIssueOpen(true)` again on an already-open dialog, and (most likely via Radix's
outside-pointerdown detection treating the outer button as "outside" the dialog content) the
dialog visibly flashes closed-then-reopened, which is exactly the "resets to blank, no reveal, no
new row, no network call" behaviour BOTH this run's first three attempts and run 1's evidence
recorded. Confirmed by instrumenting `document.querySelectorAll('button')` and checking
`.closest('[role=dialog]')`: index 0 = the outer button (`closestDialog: false`), index 1 = the
real submit (`closestDialog: true`).

**Re-tested correctly (scoped to `document.querySelector('[role=dialog]')` for every element):**
filled Name + selected company "Pull demo (mock)" (MultiSelect, searchable) -> clicked the
DIALOG's own "Issue key" button (synthetic dispatch, scoped) -> the dialog switched to "Key
issued" with the plaintext key shown ONCE (`fxa_live_8na8gsrwsgx`) + a Copy button + the warning
"Copy this key now - it will not be shown again.", AND a new row "Diag key take3 035723" appeared
in the Keys table immediately, behind the dialog. Screenshot
`run2-04-key-issued-plaintext-1280.png`. Clicked "Done" -> dialog closed, plaintext no longer
anywhere in `document.body.innerText` (confirmed via `eval`), the new key row persists in the
table (now Active, "Never" last-used). Screenshot `run2-05-key-row-persisted-1280.png`.

**DEFECT NOT FIXED / STILL BROKEN: no way to reach it.** Confirmed both **not fixed AND
newly-precisely-located**: the run-1 "resets to blank" symptom was a TEST bug (ambiguous button
match), but investigating it surfaced a REAL, separate, previously-undetected defect: **the
Revoke action for pull API keys is completely unreachable in the browser.**
`use-pull-list-config.tsx`'s `actions` array declares `{ id: 'revoke', surfaces: { row: true },
deferred: {...} }`, but neither `keyColumns` nor `snapshotColumns` defines an `id: 'actions'`
column rendering `<ActionMenu surface="row" .../>` (contrast
`use-entities-list-config.tsx`, which does exactly this at its own `id: 'actions'` column). The
shell's card view WOULD render `ActionMenu` automatically, but this page renders as a `DataGrid`
table, not cards. There is also no per-row selection checkbox column anywhere in this codebase
(`grep -rl getToggleSelectedHandler` = zero hits) and Key rows use `rowHref: '#'` (the shell's
documented navigation opt-out), so a row click is intentionally inert. Net result: the table has
NO "..." menu, NO checkbox, and NO clickable row for a Key - there is no click path anywhere in
the UI that can invoke Revoke. Confirmed via `document.querySelector('table').querySelectorAll
('th')` -> exactly `Name, Companies, Created, Last used, Status`, no Actions column; confirmed
via a DOM scan of every `<tr>` for `<button>` descendants -> zero. Screenshot
`run2-07-DEFECT-no-revoke-action-1280.png` (full Keys table, 3 rows, no action affordance
anywhere). Repro: Pull page -> Keys segment -> any row -> there is nothing to click. Reported to
the coder; not fixed here (tester does not edit application code).

## Snapshot detail re-verify (AC-10-49)

- Stock snapshot (`snap-stock-ready`, ready, 12,133 records): header facts (entity, status,
  company code "PULLFX", records, complete "Yes", built, expires, content hash) + stock-specific
  metadata (56,422 zero pairs, 42 negative pairs, 0 fractional, 0 excluded-nonzero) + the negative
  pair pill list (`SRT-01 . MBS . -3`, `AC-EXP-006 . HQ . -2437`) + excluded rows (5,
  `uom_rate_unresolved` reason shown) + the first page of the preview grid
  (`source_ref/item_code/item_description/location_code/uom_code/qty` columns). **PASS.**
  Screenshot `run2-09-stock-snapshot-detail-1280.png`.
- Product snapshot (`snap-product-ready`, ready, 11,830 records): header facts identical shape +
  product-specific metadata (5,129 zero list price, 121 negative list price CLAMPED, 1 enrich
  miss) + excluded rows (10, `mapping_failed` reason with the `name: this field is required`
  message) + preview grid (`source_ref/code/name/description/category_code/brand_code`).
  **PASS.** Screenshot `run2-10-product-snapshot-detail-1280.png`.
- Build -> PUSH_ACTIVE 409: Build snapshot dialog -> Company "Pull demo (mock)" -> Entity
  "Product" (push + active per the fixture) -> Build -> inline error "This book is now
  automatic." rendered in the dialog, exactly the R6/A6 contract text. **PASS.** Screenshot
  `run2-11-build-push-active-1280.png`.
- Build -> building -> ready walkthrough: same dialog -> Entity "Stock balance" (pull-capable) ->
  Build -> dialog closed, navigated straight to the new snapshot's detail page showing "Building"
  -> re-checked ~2s later -> "Ready" with header facts populated. **PASS.** Screenshot
  `run2-12-build-to-ready-1280.png`.
- Segment switch clears selection/search: Keys -> Snapshots via the `SearchSelect` - confirmed
  shape-wise again this run (columns swap fully, no residual Keys-segment state).

## Responsive (375px)

Pull page, Keys segment: no page-level horizontal scroll
(`document.documentElement.scrollWidth == clientWidth == 375`), grid scrolls internally, "Issue
key" button and toolbar wrap sensibly. **PASS.** Screenshot `run2-13-pull-page-375.png`.

## House rules (Run 2)

Console: only the pre-existing benign `DialogContent` a11y warning across every journey in this
run (Issue key dialog x2, Build snapshot dialog x2); no page errors. **PASS.**

## AC verdicts (Run 2)

- **AC-10-38 [FE]:** PASS on Issue-key (the run-1 "resets to blank" report is retracted - it was
  a test-script defect, not an app defect; the real submit -> plaintext-reveal -> Done -> gone ->
  new row persisted flow all work correctly, confirmed with a properly-scoped click). **NEW FAIL**
  on Revoke: the deferred-action grace-window action is registered but has no reachable trigger
  anywhere in the table UI (missing `ActionMenu` column in `use-pull-list-config.tsx`) - this is
  a genuine, newly-found frontend defect, reported above.
- **AC-10-48 [FE]:** PASS. Every fixture state named in the AC (no-keys-state now superseded by
  the seeded active+revoked pair, building/ready/failed/stock snapshots, 409 PUSH_ACTIVE) is
  observed live in the browser this run.
- **AC-10-49 [FE]:** PASS at 1280px for both product and stock snapshot detail surfaces (header
  facts, mode-specific metadata blocks, excluded-row list with reasons, negative-pair list,
  preview grid reuse). 375px not separately re-verified for the detail surface this run (time
  budget went to the Keys/Issue-key root-cause investigation above); the Keys/Snapshots LIST view
  was confirmed clean at 375px.

---

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
