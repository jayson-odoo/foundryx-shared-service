# 08 AutoCount open REST API source - S1 frontend-mock evidence

Lane s37, backend :8007, frontend :3007, DB `foundryx_service_s37`. Run date 2026-09-12
(UTC). Real clicks only via `agent-browser --session s37`, never deep URLs (except the two
noted debug re-checks during bug triage, called out below). `autocount-service.ts` is bound
to `.mock` for this slice (PHASE 1 MOCK, swap in S5).

## Run log

1. Logged in as `demo@example.com` at `http://localhost:3007`.
2. Services (App Store) -> AutoCount ESB -> Actions -> Install (real click, module install).
3. Settings -> Integrations -> Connect integration -> picked provider "AutoCount": confirmed
   the provider form still only offers the Basic-auth fields (AppId/User ID/Password) - the
   backend's `auth` select is S2 work, not yet present live. `showWhen` itself is proven via
   Vitest against a fabricated fixture field (`connection-schema.test.ts`,
   `connection-form-fields.test.tsx`), not reachable live in S1 (documented, not a defect).
   Screenshot `01-integrations-list-1280.png`.
4. AutoCount -> Companies -> Connect company -> Source "AutoCount API" -> connection picker
   showed `Sorento REST (No auth)` / `AutoCount Vendor API (Basic auth)`, each auth-badged
   (AC-08-09) -> picked Sorento REST -> "Reference prefix" field appeared, pre-filled
   `SORENTO_REST`, exact helper text "Prefixes every record reference sent to the consumer.
   Cannot be changed later." -> edited label + prefix to a timestamped value -> Create company
   -> toast "Connected SORENTO_005100." -> company detail Integration row read "API (no
   auth)" (AC-08-10). Screenshots `02a-connect-form-ref-prefix-1280.png`,
   `02-open-company-created-1280.png`.
5. AutoCount -> Companies -> **Mocha** (pre-seeded open company, `sourceKind: 'http'`) ->
   Entities -> Add entity: picker offered exactly the six confirmed masters (Product,
   Customer, Warehouse, Product category, Brand, Unit of measure) -> picked **Product** ->
   Configure -> task editor opened on tab **Source** (renamed from Query), API segment
   selected, connection locked to "Mocha REST" with "No auth" badge, endpoint path
   pre-filled `/itembypage`, Key columns `ItemCode` / Watermark `LastModified` pre-picked
   (AC-08-16 preset, AC-08-21) -> Edit -> Test -> "Paged - 11,826 total - 12 pages of 1000 - a
   run walks every page" (D14 exact wording) + preview grid (reused `SqlPreviewGrid`) showing
   ItemCode/Description/Desc2/ItemGroup/ItemBrand/BaseUOM + sample rows -> Save task -> toast
   "Task saved.", header badge flipped **Database -> Open API**. Screenshots
   `03-product-test-paged-1280.png`, `04-mocha-product-test-1280.png`,
   `05-product-saved-open-api-1280.png`.
6. Mapping tab: seeded rows ItemCode->Code, Description->Name, Desc2->Description,
   ItemGroup->Category code, ItemBrand->Brand code, BaseUOM->Uom code, IsActive->Is active,
   Discontinued->Is discontinued (AC-08-16 table, byte for byte). Screenshot
   `06-mapping-tab-preset-1280.png`.
7. Schedule tab: Incremental every 5 minutes with NO "15-minute floor" warning (the task DOES
   carry a watermark). Screenshot `07-schedule-tab-1280.png`.
8. Review & Activate tab: no "No query saved yet." false warning; only the genuinely-true
   "no delivery target (logging only)" and "no active category/UOM task yet" (dependency-order,
   expected). Screenshot `08-review-activate-tab-1280.png`.
9. Back to Entities: Product row now BORN with badge "Open API" (AC-08-18 Source column).
   Screenshot `09-entities-list-product-born-1280.png`.
10. Add entity **Brand** -> Configure -> Test -> "List - 6 rows - one request" (D14, list
    envelope) -> preview grid ItemBrand/Description, sample brands DAIKIN/PANASONIC/...
    Screenshot `10-brand-test-list-envelope-1280.png`. (Not saved - left as a reachable
    draft state, proving "Add entity" never force-saves.)
11. Add entity **Unit of measure** -> Configure -> Test -> "Paged - 11,826 total - 12 pages -
    a run walks every page" reusing `/itembypage`, "Derived from distinct values of" chips
    BaseUOM/SalesUOM/PurchaseUOM, distinct-projected `value` column (UNIT/BOX/SET/PCS), Key
    columns pre-picked `value` (D6). Screenshot `11-unit-of-measure-distinctof-1280.png`.
12. AutoCount -> Companies -> **Sorento Trading** (existing DB company, untouched SQL
    SO/PO/SPO tasks) -> Entities -> Add entity **Product category** -> Configure -> Source
    tab opened on **Database** (the company default, AC-08-18) with the SAME schema
    tree/SQL editor unchanged. Screenshot `12-sorento-db-company-database-default-1280.png`.
13. Toggled Database -> **API** -> connection picker FREE (not locked, AC-08-13) listed
    `Sorento REST (No auth)` and `Mocha REST (No auth)` (both open connections of the
    tenant), the vendor Basic-auth connection excluded (`product_category` is not
    API-capable) -> picked Sorento REST -> path pre-filled `/ItemGroup` -> Test -> "List - 50
    rows - one request", preview GRP01..GRP08/AIRCOND 1.. (AC-08-36). Screenshot
    `13-sorento-mixed-db-company-api-toggle-1280.png`.
14. Cancelled without saving -> dirty-guard "Discard changes?" fired correctly (the toggle +
    Test genuinely dirtied the task) -> Discard changes -> confirmed the existing SQL
    PO/SO/SPO tasks on Sorento Trading were never touched by this run (no save occurred).
15. Set viewport 375x812, reopened the app fresh (this reset the in-memory mock - expected,
    documented behaviour, not a defect): Companies list, Connect company + reference-prefix
    reveal, Mocha Product Source tab (locked connection + badge), and the Test/paged-preview
    result all render cleanly with no clipping and no horizontal page overflow (the preview
    grid scrolls WITHIN its own bounded container). Screenshots `14-companies-list-375.png`,
    `15-connect-form-ref-prefix-375.png`, `16-source-tab-api-375.png`,
    `17-source-tab-test-paged-375.png`.
16. `agent-browser console` at the end of the run: **zero console errors** - two pre-existing
    Radix `DialogContent` description warnings only (unrelated to this slice, present on the
    formula-builder dialog before this plan).
17. Closed the session (`agent-browser --session s37 close`).

## Bugs found live and fixed (not caught by the pre-existing Vitest suite)

All three were genuine logic bugs in the S1 mock/task-editor-view wiring, each reproduced via
the click flow above, then fixed with a red-first regression test before re-verifying live:

1. **`defaultEtlConfig`'s default parameter silently defaulted a non-DB company's blank task's
   `connectionId` to a SQL connection id** (`conn-sql-1`) even though the locked-connection
   DISPLAY read correctly from `lockedApiConnection` - Test/Save used the wrong connection and
   422'd "Choose an open (no-auth) AutoCount connection." Fixed: the default is now `null`.
   Regression: `services/autocount-service.mock.http.test.ts` "getEtlTask - blank draft on a
   non-db company".
2. **A never-configured HTTP task's Source tab pre-fill was baked into `baseline` itself**, so
   `config` matched `baseline` from the first render and the shell's dirty flag read `false` -
   clicking Save showed "Task saved." while `onSave`'s `if (configDirty || sourceKindDirty)`
   gate silently skipped the real `save()` call; nothing persisted (confirmed live: the
   Entities list stayed "No data available" after a "successful" save). Fixed: the preset now
   seeds the WORKING `config` only, leaving `baseline` as the genuinely-saved (blank) state.
   Regression: `task-editor-view.http-preset-dirty.test.tsx` (new file, 3 tests).
3. **`bornEntities()` gated a row's existence on `sourceConfig.query.trim()` only** - an HTTP
   task never has a `query` (only `path`), so a saved HTTP task never appeared on the Entities
   list. Fixed: the gate now accepts either `query` or `path`. Regression:
   `autocount-service.mock.http.test.ts` "the saved task is BORN on the Entities list".
4. **The Mapping tab showed the generic vendor-API master view (AccNo/CompanyName/...) instead
   of the AC-08-16 HTTP preset rows** - `mockMappingView` had no HTTP-preset branch.
   Fixed: `HTTP_PRESETS` in `lib/autocount-etl.ts` now carries each entity's canonical field
   mapping too (one source of truth with the Source-tab preset), and the mock dispatches on
   the resolved `sourceImpl` for the one collision (`customer`, reachable via either the
   legacy vendor path or the open API). Regression: 4 new tests in
   `autocount-service.mock.http.test.ts`.
5. **ScheduleTab's incremental-floor check reads `watermarkColumn` (the SQL field name)
   unconditionally** - an HTTP task's `watermarkField` pick left `watermarkColumn` null, so
   Schedule wrongly showed "At least 15 minutes without a watermark column." even though a
   watermark WAS picked. Fixed: every HTTP watermark write (preset seed + operator pick) now
   mirrors onto `watermarkColumn` too, so ScheduleTab (AC-08-19: "the existing component,
   untouched") keeps working with no code change of its own. Regression: an assertion added to
   `task-editor-view.http-preset-dirty.test.tsx`.

None of these were visible from the mock's own unit tests in isolation - only the live click-
through flow surfaced them, which is exactly why this evidence run exists as a mandatory step
before "done".
