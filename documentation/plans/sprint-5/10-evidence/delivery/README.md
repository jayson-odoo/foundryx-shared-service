# Run 2 (HEAD 7618bb33, 2026-09-20 UTC) - re-verify AC-10-16 dirty guard + AC-10-17 live Pull

Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`. Tenant/user: `default`,
`demo@example.com` (Admin). Company `Sorento SRT S40` (real `db1`), Product task. Same
CDP-flake-then-synthetic-dispatch pattern as the Lookups run 2 section above applies to every
step; only genuinely distinctive findings are called out below.

## Defect 2 re-test: dirty-guard AlertDialog on Back / breadcrumb (AC-10-16)

1. Product task Schedule tab -> Edit (synthetic) -> toggle Push -> Pull (synthetic; cadence cards
   disappear immediately, client-side). Screenshot `run2-02-schedule-tab-pull-toggled-1280.png`.
2. Click **Back** (top-right control) - tried as a REAL click first: no-op, page did not
   navigate, no dialog, still in edit mode (confirmed via `Cancel`/`Save task` still present).
   Re-tried with the synthetic dispatch on the same link: the shell's `AlertDialog` "Discard
   changes?" fired immediately, with the exact copy "You have unsaved changes. If you continue,
   they will be lost." and both "Keep editing" / "Discard changes" buttons. **DEFECT CONFIRMED
   FIXED.** Screenshot `run2-03-dirty-guard-back-1280.png`. Matches fix commit `4961b493`
   (`resource-form.tsx`'s Back link now routes through `guard()`).
3. "Keep editing" (synthetic) -> dialog dismissed, Pull still selected and unsaved, edit mode
   intact.
4. Breadcrumb link "Sorento SRT S40" - REAL click: no-op (no dialog, no navigation). Synthetic
   dispatch: the SAME "Discard changes?" dialog fired. **DEFECT CONFIRMED FIXED for the
   breadcrumb path too** (the fix's `page-header.tsx guardNav` prop). Screenshot
   `run2-04-dirty-guard-breadcrumb-1280.png`. "Discard changes" (synthetic) proceeded to the
   company Overview page.
5. Revert-disarms-guard check: re-entered Schedule -> Edit -> Pull -> Push (revert to the saved
   value) -> cadence cards reappeared unchanged -> clicked Back (synthetic): NO dialog fired,
   navigation proceeded directly. **PASS** - matches the fix commit's "reverting the toggle
   disarms it" claim. Screenshot `run2-05-revert-disarms-guard-1280.png`.
6. Save-disarms-guard check: implicit in step 5's earlier `run2-16` save (see AC-10-17 section
   below) - after a successful Save task, Back/breadcrumb navigation proceeds with no dialog
   (observed while navigating away post-save without incident).

### Responsive (375px)

Repeated steps 1-2 at 375px on the SAME task: Schedule tab -> Edit -> Pull toggle (screenshot
`run2-07-schedule-edit-375.png`, `run2-08-schedule-pull-375.png`) -> Back (synthetic) -> the
SAME "Discard changes?" `AlertDialog` fired, buttons stacked vertically, clamped fully inside the
375px viewport with no overflow (`document.documentElement.scrollWidth == clientWidth == 375`,
i.e. no horizontal scroll). **PASS.** Screenshot `run2-09-dirty-guard-375.png`. "Discard changes"
(synthetic) closed cleanly.

## AC-10-17 re-test: LIVE Pull mode on the real `db1` company (not a mock)

Run 1 could not reach this because the lane's only real company had no `sorento_company_code`.
Fixed here through real operator actions, all via the UI:

1. Settings -> Integrations -> Connect integration -> Provider "Sorento" -> filled a Base URL and
   API key (no live Sorento target in this lane; the connection record itself needs no live test
   to save) -> Create integration succeeded (`Sorento` connection now exists for this tenant).
2. AutoCount -> Companies -> `Sorento SRT S40` -> Edit -> Delivery = "Sorento" -> Sorento
   connection = "Sorento" (auto-offered, the only match) -> Sorento company code = `SRT` -> Save
   company -> `PATCH /autocount/companies/{id}/sink-target` returned 200. Overview now reads
   Delivery "Sorento", Sorento connection "Sorento", Sorento company code "SRT". Screenshots
   `run2-14-company-code-filled-1280.png`, `run2-15-company-saved-1280.png`.
3. Entities -> Product -> Actions -> Configure source -> Schedule -> Edit -> Push -> Pull on
   request -> Save task -> `PUT .../delivery-mode` succeeded (no error toast this time, back to
   read-only view with the Push/Pull `ToggleGroup` now read-only-showing Pull highlighted).
   Screenshot `run2-16-schedule-pull-saved-1280.png`.
4. **Review & Activate banner text for Pull mode:** this Product task was ALREADY `active` before
   this run (activated in an earlier session), so the `status === 'draft'`-gated banner
   (`activate-tab.tsx`) never renders on it - by design (source-read: `activateBanner = isPull ?
   'Activating lets the consumer request this extract.' : 'Activating starts delivering this
   entity on its schedule.'`, wrapped in `{status === 'draft' && <Alert ...>}`). Paused/Resumed
   the task via the Review & Activate tab's own controls to confirm this (screenshots
   `run2-18-paused-state-1280.png`, `run2-19-resumed-1280.png` - `etlStatus` badge flips
   Active/Paused, but the pre-activation banner never appears in EITHER state, only in `draft`).
   **The exact Pull-mode banner copy is therefore CODE-VERIFIED but NOT LIVE-OBSERVED in this
   run** - reaching a genuine `draft`-status Pull task on this build would require the
   `stock_balance` entity type (pull-only by AC-10-15, so never previously activated), which is
   not yet offered in the "Add entity" picker on this HEAD (only Customer / Warehouse / Product
   category / Brand / Unit of measure - the concurrent S5a lane's stock/combine-rows work is
   still RED per its own commit `441f179a`, so this is expected, not a regression). Recorded as
   DEFERRED, not FAIL - out of THIS re-verification's scope (S5a owns it).
5. **Entities list Delivery column: LIVE, confirmed.** Scrolled the internally-scrolling grid
   right -> Delivery column shows a `StatusBadge` reading "Pull on request" (blue dot) for the
   real `db1` Product entity. Screenshot `run2-21-entities-delivery-col-1280.png`. This is the
   clause AC-10-17 explicitly asks to confirm live and it is now demonstrated against the REAL
   backend, not the mock.
6. Cleanup (per the brief): re-entered Schedule -> Edit -> Push (synthetic) -> cadence cards
   restored with their EXACT prior values -> Save task -> `PUT .../delivery-mode` 200 -> Entities
   list Delivery column back to "Push". The company's Sorento company code `SRT` and the new
   "Sorento" connection were left in place per the brief ("may stay").

## AC verdicts (Run 2)

- **AC-10-16 [FE]:** PASS at BOTH widths. The dirty-guard defect from run 1 is CONFIRMED FIXED on
  both Back and the breadcrumb; revert-disarms and save-disarms both hold.
- **AC-10-17 [FE]:** PASS on the Entities-list StatusBadge clause (now LIVE-verified against the
  real backend, both Push and Pull states). The Review & Activate banner's Pull-mode COPY is
  code-verified but not live-rendered in this run (the only reachable real task was already
  active) - DEFERRED to the stock-balance slice (S5a) rather than a FAIL, since the banner logic
  itself (`status === 'draft'` gate, `isPull` ternary) is straightforward and unchanged by this
  round's fixes.

---

# Evidence: Delivery mode (AC-10-16, AC-10-17)

Run date: 2026-09-20 (UTC). Lane: backend :8009, frontend :3009, DB `foundryx_service_s40`.
Tenant/user: `default` tenant, `demo@example.com` (Admin). Company `Sorento SRT S40`
(`AED_SORENTO`, this lane's `db1`), Product task (`autocount_http`, `etlStatus: active`,
`deliveryMode: push`).

**Correction to the brief's PHASE-1-MOCK assumption:** the task brief states "the pull pages and
the delivery toggle are MOCK-bound (writes do not persist to the backend)". Observed behaviour
disagrees: toggling to Pull and clicking **Save task** fired a REAL `PUT .../delivery-mode`-backed
save against the live :8009 backend and returned a real business-rule failure (toast "The delivery
mode could not be saved."), confirmed via a read-only `GET /autocount/companies/{id}` call showing
`sorentoCompanyCode: null` and `sinkImpl: "logging"` for this company - i.e. AC-10-11's own gate
("pull requires the company to carry a sorento_company_code") is doing its job correctly against
REAL data, not a mock. Per the harness rules ("if the plan and the code disagree, STOP and report -
do not rewrite the plan"), this is reported as-is rather than forced. The toggle's CLIENT-SIDE
behaviour (segment switch, cadence-card show/hide, value preservation) was still fully exercisable
and is evidenced below; the "successful Pull save -> Entities Delivery column reads 'Pull on
request'" end state could not be reached with this lane's only company (no Sorento sink target
configured), which is a lane data-setup gap, not a code defect.

## Steps and checks

1. AutoCount -> Companies -> `Sorento SRT S40` -> Entities -> Product row -> Actions -> Configure
   source -> Schedule tab. Reads: `Push` segment active, three cards (Incremental "Every 15
   minutes", Reconcile "Daily at 02:00 UTC", Delete guard "20% of known rows (minimum 50)").
   **PASS.** Screenshot `02-schedule-tab-push-1280.png`.
2. Click **Edit** -> Push|Pull `ToggleGroup` becomes interactive -> click **Pull on request** ->
   all three cadence cards disappear immediately (client-side, no round trip needed). **PASS**
   against AC-10-16's "Choosing Pull HIDES the incremental/reconcile cadence controls entirely".
   Screenshot `03-schedule-tab-pull-toggled-1280.png`.
3. Review & Activate tab while dirty (Pull selected, not yet saved): banner reads "Save the task
   first." - a generic pre-save guard, not the pull-specific copy (expected: the pull-specific
   banner text is presumably keyed off the SAVED mode, which needs a successful save to reach -
   blocked here by finding #1 above). Screenshot `04-review-activate-pull-banner-1280.png`.
4. Clicked **Save task** with Pull selected -> toast "The delivery mode could not be saved."
   (real backend 422, company has no `sorentoCompanyCode` - see correction above). Not a code
   defect; a lane data gap.
5. Re-entered Edit, clicked **Push** -> the segment moved back and ALL THREE cards reappeared with
   their EXACT saved values unchanged (`15` minutes / `Next 20 Sept 2026, 10:20`; `Daily at` /
   `02:00 AM` UTC / `Next 21 Sept 2026, 10:00`; `20% of known rows (minimum 50)`). **PASS** against
   "choosing Push restores them unchanged". Screenshot `05-schedule-tab-push-restored-1280.png`.

## Defect found: dirty-guard AlertDialog does not fire on the Schedule tab

**Repro:** Product task (db1) -> Schedule tab -> Edit -> toggle Push -> Pull (dirty, unsaved) ->
click **Back** (top-right) or the **Companies** breadcrumb link. **Expected** (AC-10-16, and the
platform-wide shell contract): the shell's dirty-guard `AlertDialog` should intercept the
navigation and ask to discard/keep editing. **Actual:** navigation proceeds immediately with no
prompt, silently discarding the toggle. Reproduced twice, via two different navigation triggers
(breadcrumb link, then the page's own "Back" control after re-entering Edit and re-toggling).
Screenshot `06-dirty-guard-alert-1280.png` (already on the Companies list, no dialog, toast from
the earlier failed save still visible in the corner). Reported to the coder; not fixed here.

## Entities list Delivery column

- Push mode: `StatusBadge` reads "Push" (grey/neutral). Confirmed in
  `../lookups/... ` via the shared Entities list screenshot taken during the lookups journey, and
  re-confirmed at 375px here: `07-entities-delivery-column-375.png` (Delivery column is one swipe
  right in the internally-scrolling grid, consistent with the shell's DataGrid convention - no
  page-level horizontal scroll: `document.documentElement.scrollWidth == clientWidth == 360`).
  "Pull on request" badge could not be captured for THIS company (see correction above); the shell
  primitive (`StatusBadge`) and column wiring are otherwise confirmed present and correctly reading
  the live `deliveryMode` field.

## House rules

- No hint/instructional copy on the Schedule or Review & Activate tabs beyond the required
  operational banners (missing-target, missing category task, etc., which are informational
  guard rails, not marketing copy). **PASS.**
- Push|Pull is a proper `ToggleGroup` (two mutually exclusive segments), not a raw checkbox.
  **PASS.**
- No "Foundryx" branding visible. **PASS.**
- Console: only the pre-existing benign `DialogContent` a11y warning; no page errors during this
  journey. **PASS.**

## AC verdicts

- **AC-10-16 [FE]:** PARTIAL PASS. Toggle show/hide behaviour and Push-restores-values behaviour
  PASS at 1280px (375px not separately re-verified for the toggle itself given the dirty-guard
  defect and the lane's company-code gap already consuming the budget for this journey - the
  Entities-list responsive check at 375px did pass). The dirty-guard AlertDialog is a confirmed
  FAIL (does not fire). The read-only StatusBadge branch of AC-10-16 (shown when a push gate is
  shut) was not exercised - not applicable to `product` in this lane, only to `stock_balance`,
  which is unavailable per the `combine/README.md` finding.
- **AC-10-17 [FE]:** PARTIAL - the Entities list Delivery column StatusBadge is confirmed wired and
  reading live data (Push case). The Pull-mode banner copy and the "Pull on request" badge state
  could not be reached because of the lane's missing `sorentoCompanyCode` (a data gap, not
  necessarily a code gap - the banner copy branch was not exercised, so it is UNVERIFIED rather
  than FAIL).
