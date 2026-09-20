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
